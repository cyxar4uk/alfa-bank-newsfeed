"""Прокси картинок новостей: браузер берёт их у нас (Коммерсантъ не отдаёт картинки чужим сайтам).

Только хосты изданий из лент парсера и их поддомены (im2.kommersant.ru для www.kommersant.ru); адрес должен
разрешаться в публичный IP — никаких внутренних сетей; редирект — только на разрешённый хост; ответ — image/*
не больше 2 МБ, за 8 с. Картинка кэшируется на диске (IMG_CACHE_DIR, в compose — том кэша).
Адрес проверяется перед каждым запросом; подмена DNS между проверкой и соединением не закрыта — хосты и так
ограничены изданиями из каталога.
"""

import hashlib
import ipaddress
import json
import os
import socket
import time
import tomllib
from functools import lru_cache
from importlib import resources
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

import httpx

MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 8.0
MAX_REDIRECTS = 3
CACHE_FILES = 2000  # картинок в кэше, не больше (≈ до 4 ГБ в худшем случае, обычно — десятки МБ)
PROXY_PATH = "/api/img"
# растровые форматы; SVG не отдаём — в нём бывает скрипт, а отдаём мы со своего адреса
IMAGE_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/avif",
        "image/x-icon",
        "image/vnd.microsoft.icon",
    }
)


class ImageError(Exception):
    """Картинку не отдаём: чужой хост, внутренний адрес, не картинка, больше 2 МБ, источник молчит."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _base(host: str) -> str:
    """Домен издания: последние две части имени, у *.gov.ru и т. п. — три («nalog.gov.ru»)."""
    parts = host.lower().strip(".").split(".")
    keep = 3 if len(parts) >= 3 and parts[-2] in ("gov", "com", "co", "org") else 2
    return ".".join(parts[-keep:])


@lru_cache(maxsize=1)
def allowed_domains() -> frozenset[str]:
    """Домены изданий из лент парсера: хосты ссылок, адрес ленты и значка."""
    raw = resources.files("ingest.news").joinpath("sources.toml").read_text("utf-8")
    domains = set()
    for feed in tomllib.loads(raw).get("feed", []):
        hosts = list(feed.get("hosts") or [])
        hosts += [urlsplit(u).hostname or "" for u in (feed.get("url"), feed.get("icon")) if u]
        domains.update(_base(h) for h in hosts if h)
    return frozenset(domains)


def is_allowed(url: str) -> bool:
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        port = parts.port  # нечисловой или больше 65535 — ValueError
    except ValueError:
        return False  # битая ссылка в новости не роняет ленту
    if parts.scheme not in ("http", "https") or not host or parts.username or parts.password:
        return False
    if port is not None and port not in (80, 443):
        return False
    return any(host == d or host.endswith("." + d) for d in allowed_domains())


def proxied(url: str | None) -> str | None:
    """Ссылка на картинку через наш прокси; хост не из каталога — ссылка как есть."""
    if not url or not is_allowed(url):
        return url
    return f"{PROXY_PATH}?u={quote(url, safe='')}"


def _check_public(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, None)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ImageError(502, f"не удалось найти {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise ImageError(403, "адрес картинки ведёт во внутреннюю сеть")


def _cache_paths(cache_dir: Path, url: str) -> tuple[Path, Path]:
    key = hashlib.sha256(url.encode()).hexdigest()
    return cache_dir / f"{key}.bin", cache_dir / f"{key}.json"


def fetch(url: str, cache_dir: Path, client: httpx.Client | None = None) -> tuple[bytes, str]:
    """Картинка и её тип: из кэша или у издателя с проверками; ImageError — почему нет."""
    if not is_allowed(url):
        raise ImageError(403, "хост картинки не из каталога источников")
    body_path, meta_path = _cache_paths(cache_dir, url)
    if body_path.is_file() and meta_path.is_file():
        try:
            return body_path.read_bytes(), json.loads(meta_path.read_text("utf-8"))["type"]
        except (OSError, ValueError, KeyError):
            pass  # битая запись кэша — берём заново
    own = client is None
    deadline = time.monotonic() + TIMEOUT * 2  # общий срок: медленный источник не держит поток
    client = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
    try:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            _check_public(urlsplit(current).hostname or "")
            with client.stream("GET", current, headers={"User-Agent": "alfa-newsfeed/1.0"}) as response:
                if response.is_redirect:
                    current = urljoin(current, response.headers.get("location", ""))
                    if not is_allowed(current):
                        raise ImageError(403, "редирект на хост не из каталога источников")
                    continue
                if response.status_code != 200:
                    raise ImageError(502, f"источник ответил {response.status_code}")
                kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if kind not in IMAGE_TYPES:
                    raise ImageError(415, "по ссылке не картинка")
                length = response.headers.get("content-length") or "0"
                if length.isdigit() and int(length) > MAX_BYTES:
                    raise ImageError(413, "картинка больше 2 МБ")
                data = bytearray()
                for chunk in response.iter_bytes():
                    data += chunk
                    if len(data) > MAX_BYTES:
                        raise ImageError(413, "картинка больше 2 МБ")
                    if time.monotonic() > deadline:
                        raise ImageError(504, "источник картинки отвечает слишком медленно")
                break
        else:
            raise ImageError(502, "слишком много редиректов")
    except ImageError:
        raise
    except Exception as exc:  # сеть, неверный адрес у httpx и прочее — ответ 502, а не 500
        raise ImageError(502, "источник картинки не ответил") from exc
    finally:
        if own:
            client.close()
    _store(cache_dir, body_path, meta_path, bytes(data), kind, url)
    return bytes(data), kind


def _store(cache_dir: Path, body_path: Path, meta_path: Path, data: bytes, kind: str, url: str) -> None:
    """Запись в кэш через временный файл (параллельный читатель не увидит обрезанный); старое — вычищается."""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        for path, content in (
            (body_path, data),
            (meta_path, json.dumps({"type": kind, "url": url}).encode()),
        ):
            tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
            tmp.write_bytes(content)
            os.replace(tmp, path)
        files = sorted(cache_dir.glob("*.bin"), key=lambda p: p.stat().st_mtime)
        for old in files[: max(0, len(files) - CACHE_FILES)]:  # диск не резиновый: самые старые — прочь
            old.unlink(missing_ok=True)
            old.with_suffix(".json").unlink(missing_ok=True)
    except OSError:
        pass  # кэш — ускорение, без него картинка всё равно отдаётся
