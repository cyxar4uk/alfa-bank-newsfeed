"""Картинка и полный текст со страницы материала — для новостей, у которых их нет из ленты.

Со страницы берём только ссылку на картинку (og:image) и — у лент с `full_text = "page"`, где условия издателя это
разрешают, — текст открытой страницы. Пейволлы не обходим: страницы платных материалов не запрашиваем вовсе.
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx

from ingest.news.article import MIN_BLOCK_CHARS, _decode, clean_body, extract_article
from ingest.news.fetch import USER_AGENT

MAX_PAGE_BYTES = 3_000_000
WORKERS = 6
# столько ошибок соединения подряд — сети нет, остаток пачки не запрашиваем: новости останутся на следующий круг
MAX_TRANSPORT_ERRORS = 8


@dataclass(frozen=True)
class PageJob:
    id: str
    url: str
    want_text: bool
    container: str = ""


@dataclass
class PageMedia:
    image: str | None = None
    text: str | None = None


class PageUnavailable(Exception):
    """Сайт сейчас не отдаёт страницу (нет соединения, 429, 5xx): спросим на следующем круге."""


@dataclass
class Page:
    data: bytes
    content_type: str
    url: str  # адрес, по которому страница открылась (после редиректов) — от него считаем относительные ссылки


def read_page(client: httpx.Client, url: str) -> Page | None:
    """HTML-страница не больше MAX_PAGE_BYTES. 404 — None (попробуем другой вариант ссылки); 429 и 5xx —
    PageUnavailable; прочие ответы, не HTML и слишком большая страница — пустая Page: картинки и текста нет."""
    try:
        with client.stream("GET", url) as resp:
            if resp.status_code == 404:
                return None
            if resp.status_code == 429 or resp.status_code >= 500:
                raise PageUnavailable(f"{resp.status_code}")
            content_type = resp.headers.get("content-type", "")
            if resp.status_code != 200 or "html" not in content_type.lower():
                return Page(b"", content_type, str(resp.url))
            data = bytearray()
            for chunk in resp.iter_bytes():
                data += chunk
                if len(data) > MAX_PAGE_BYTES:
                    return Page(b"", content_type, str(resp.url))
            return Page(bytes(data), content_type, str(resp.url))
    except httpx.TransportError as exc:
        raise PageUnavailable(str(exc)) from exc


def url_variants(url: str) -> list[str]:
    """Ссылка как в базе и её варианты: каноничная ссылка всегда https и без «/» в конце, а government.ru
    по https не отвечает, у nalog.gov.ru без «/» — 404."""
    parts = urlsplit(url)
    slash = [] if parts.path.endswith("/") or parts.query else [urlunsplit(parts._replace(path=parts.path + "/"))]
    plain = [urlunsplit(urlsplit(u)._replace(scheme="http")) for u in [url, *slash]] if parts.scheme == "https" else []
    return [url, *slash, *plain]


def page_media(client: httpx.Client, job: PageJob) -> PageMedia:
    """Варианты ссылки перебираем только после 404 или ошибки соединения. Ни один не ответил — PageUnavailable."""
    page, unavailable = None, None
    for url in url_variants(job.url):
        try:
            page = read_page(client, url)
        except PageUnavailable as exc:
            unavailable = exc
            continue
        if page is not None:
            break
    if page is None and unavailable is not None:
        raise unavailable
    if page is None or not page.data:
        return PageMedia()
    article = extract_article(_decode(page.data, page.content_type), page.url, job.container or None)
    text = clean_body(article.body) if job.want_text else ""
    return PageMedia(image=article.image, text=text if len(text) >= MIN_BLOCK_CHARS else None)


def fetch_pages(jobs: list[PageJob], timeout: float = 15.0) -> dict[str, PageMedia]:
    """Страницы параллельно. В ответе нет id, если страница сейчас недоступна: её спросим ещё раз.
    Ответила, но без картинки и текста (404, не HTML, битая разметка) — пустой PageMedia: больше не спрашиваем."""
    out: dict[str, PageMedia] = {}
    transport_errors = 0

    def one(job: PageJob) -> tuple[PageJob, PageMedia | None]:
        if transport_errors >= MAX_TRANSPORT_ERRORS:
            return job, None
        try:
            return job, page_media(client, job)
        except PageUnavailable:
            return job, None
        except Exception:  # noqa: BLE001 — битая ссылка или разметка одной страницы не должна ронять сбор
            return job, PageMedia()

    headers = {"User-Agent": USER_AGENT}
    # короткий таймаут соединения: сайт, который не отвечает по https, иначе держал бы поток на весь timeout
    limits = httpx.Timeout(timeout, connect=5.0)
    with (
        httpx.Client(timeout=limits, follow_redirects=True, headers=headers) as client,
        ThreadPoolExecutor(WORKERS) as pool,
    ):
        for job, media in pool.map(one, jobs):
            if media is None:
                transport_errors += 1
                continue
            transport_errors = 0
            out[job.id] = media
    return out


Fetcher = Callable[[list[PageJob]], dict[str, PageMedia]]
