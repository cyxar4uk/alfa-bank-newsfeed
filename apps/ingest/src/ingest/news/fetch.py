"""Загрузка RSS-лент. Недоступная лента не роняет сбор — попадает в отчёт."""

import html
import re
import tomllib
from dataclasses import dataclass
from importlib import resources
from urllib.parse import urljoin, urlsplit

import feedparser
import httpx

from ingest.news.article import html_paragraphs, usable_image

RELIABILITY = frozenset({"official", "agency", "business_media", "other"})
FULL_TEXT = frozenset({"", "rss", "page"})
USER_AGENT = "Mozilla/5.0 (compatible; alfa-newsfeed-ingest/0.1)"


@dataclass(frozen=True)
class Feed:
    id: str
    publisher: str
    url: str
    priority: int = 5
    enabled: bool = True
    terms: str = ""
    reliability: str = "other"
    # домены ссылок ленты: запись с чужого домена (спорт-сайт, партнёрский журнал) не берём — иначе в карточке
    # был бы не тот издатель
    hosts: tuple[str, ...] = ()
    icon: str = ""  # значок издания
    # полный текст, где его разрешают условия: "rss" — из ленты (content:encoded), "page" — со страницы материала
    full_text: str = ""
    text_container: str = ""  # класс элемента со статьёй на странице, если общий разбор берёт не то


@dataclass
class RawItem:
    feed_id: str
    publisher: str
    priority: int
    title: str
    summary: str
    link: str
    published: str | None
    reliability: str = "other"
    image: str | None = None  # картинка из ленты: media:content, media:thumbnail, enclosure, <img> в описании
    icon: str | None = None
    text: str | None = None  # полный текст из ленты — только у лент с full_text = "rss"


@dataclass
class FeedReport:
    feed_id: str
    publisher: str
    url: str
    ok: bool
    items: int = 0
    error: str | None = None


def load_feeds(path: str | None = None) -> list[Feed]:
    if path:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    else:
        data = tomllib.loads(resources.files("ingest.news").joinpath("sources.toml").read_text("utf-8"))
    feeds = []
    for item in data.get("feed", []):
        feed = Feed(**{**item, "hosts": tuple(item.get("hosts", ()))})
        if feed.reliability not in RELIABILITY:
            raise ValueError(f"лента {feed.id}: reliability должен быть одним из {sorted(RELIABILITY)}")
        if feed.full_text not in FULL_TEXT:
            raise ValueError(f"лента {feed.id}: full_text должен быть одним из {sorted(FULL_TEXT)}")
        feeds.append(feed)
    return feeds


_IMG = re.compile(r"<img\b[^>]*>", re.I)
_SRC = re.compile(r"\bsrc\s*=\s*[\"']([^\"']+)", re.I)
# счётчик посещений — картинка 1×1, а не иллюстрация
_PIXEL = re.compile(r"\b(?:width|height)\s*=\s*[\"']?[01][\"'\s/>]", re.I)


def _http(url: str | None, base: str) -> str | None:
    if not url or not isinstance(url, str):
        return None
    return usable_image(urljoin(base, url.strip()))


def entry_image(entry: dict, base: str = "") -> str | None:
    """Картинка записи RSS: media:content (картинка), media:thumbnail, вложение-картинка, первый <img> в тексте."""
    for media in entry.get("media_content") or []:
        kind = (media.get("medium") or media.get("type") or "image").lower()
        if kind.startswith("image") and (url := _http(media.get("url"), base)):
            return url
    for thumb in entry.get("media_thumbnail") or []:
        if url := _http(thumb.get("url"), base):
            return url
    for link in entry.get("links") or []:
        if (
            link.get("rel") == "enclosure"
            and (link.get("type") or "").startswith("image")
            and (url := _http(link.get("href"), base))
        ):
            return url
    for raw in (entry.get("summary") or "", *(c.get("value", "") for c in entry.get("content") or [])):
        for tag in _IMG.findall(raw):
            if not _PIXEL.search(tag) and (m := _SRC.search(tag)) and (url := _http(html.unescape(m.group(1)), base)):
                return url
    return None


def entry_text(entry: dict) -> str | None:
    """Полный текст из content:encoded, абзацами; первой строкой — автор, если он есть в ленте (Forbes разрешает
    перепечатку с указанием автора). Пусто — None."""
    raw = next((c.get("value", "") for c in entry.get("content") or [] if c.get("value")), "")
    text = html_paragraphs(raw)
    author = html_paragraphs(entry.get("author") or "")
    return (f"Автор: {author}\n{text}" if author and text else text) or None


def parse_feed(feed: Feed, content: bytes) -> list[RawItem]:
    parsed = feedparser.parse(content)
    items = []
    for entry in parsed.entries:
        link = entry.get("link", "")
        host = (urlsplit(link).hostname or "").removeprefix("www.")
        if feed.hosts and host not in {h.removeprefix("www.") for h in feed.hosts}:
            continue
        items.append(
            RawItem(
                feed_id=feed.id,
                publisher=feed.publisher,
                priority=feed.priority,
                reliability=feed.reliability,
                title=entry.get("title", ""),
                summary=entry.get("summary", "") or entry.get("description", ""),
                link=link,
                published=entry.get("published") or entry.get("updated"),
                image=entry_image(entry, link),
                icon=feed.icon or None,
                text=entry_text(entry) if feed.full_text == "rss" else None,
            )
        )
    return items


def fetch_all(feeds: list[Feed], timeout: float = 20.0) -> tuple[list[RawItem], list[FeedReport]]:
    items: list[RawItem] = []
    reports: list[FeedReport] = []
    with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        for feed in feeds:
            try:
                resp = client.get(feed.url)
                resp.raise_for_status()
                got = parse_feed(feed, resp.content)
                if not got:
                    raise ValueError("в ленте нет записей")
            except (httpx.HTTPError, ValueError) as exc:
                reports.append(FeedReport(feed.id, feed.publisher, feed.url, ok=False, error=_short(exc)))
                continue
            items.extend(got)
            reports.append(FeedReport(feed.id, feed.publisher, feed.url, ok=True, items=len(got)))
    return items, reports


def _short(exc: Exception) -> str:
    text = str(exc) or type(exc).__name__
    return text.splitlines()[0][:200]
