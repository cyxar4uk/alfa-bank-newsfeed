"""Загрузка RSS-лент. Недоступная лента не роняет сбор — попадает в отчёт."""

import tomllib
from dataclasses import dataclass
from importlib import resources
from urllib.parse import urlsplit

import feedparser
import httpx

RELIABILITY = frozenset({"official", "agency", "business_media", "other"})
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
        feeds.append(feed)
    return feeds


def parse_feed(feed: Feed, content: bytes) -> list[RawItem]:
    parsed = feedparser.parse(content)
    items = []
    for entry in parsed.entries:
        host = (urlsplit(entry.get("link", "")).hostname or "").removeprefix("www.")
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
                link=entry.get("link", ""),
                published=entry.get("published") or entry.get("updated"),
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
