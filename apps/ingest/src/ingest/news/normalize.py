"""Приведение записей лент к единому виду: чистый текст, лид до 500 знаков, каноничная ссылка, дата в МСК."""

import hashlib
import html
import re
from datetime import UTC, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ingest.models import LEAD_MAX_CHARS, Source

if TYPE_CHECKING:  # fetch берёт разбор статьи из article, а тот — clean_text отсюда
    from ingest.news.fetch import RawItem

MSK = timezone(timedelta(hours=3), "MSK")

_TAG = re.compile(r"<[^>]+>")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_SPACES = re.compile(r"\s+")
_MONTHS = "января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря"
# «22 октября. FINMARKET.RU - », «Москва. 23 октября. INTERFAX.RU - »
_DATELINE = re.compile(
    rf"^(?:[А-ЯЁ][\w\-]+(?:\s[А-ЯЁ][\w\-]+)?\.\s+)?\d{{1,2}}\s+(?:{_MONTHS})\.?\s+[A-ZА-ЯЁ][A-ZА-ЯЁ.\-]*\s*[-–—]\s*"
)
_TRACKING_PARAMS = re.compile(r"^(utm_\w+|fbclid|yclid|gclid|from|ref|rss|_openstat)$", re.I)


def clean_text(raw: str) -> str:
    text = _COMMENT.sub(" ", raw or "")
    text = _TAG.sub(" ", text)
    text = html.unescape(text).replace("\xa0", " ").replace("​", "")
    return _SPACES.sub(" ", text).strip()


def strip_dateline(text: str) -> str:
    return _DATELINE.sub("", text, count=1)


def make_lead(summary: str, title: str = "", limit: int = LEAD_MAX_CHARS) -> str:
    lead = strip_dateline(clean_text(summary))
    if not lead or lead.casefold() == title.casefold():
        return ""
    if len(lead) <= limit:
        return lead
    cut = lead[: limit - 1]
    # конец предложения в последней трети — режем по нему, иначе по слову
    sentence_end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if sentence_end > limit * 0.6:
        return cut[: sentence_end + 1]
    space = cut.rfind(" ")
    return (cut[:space] if space > 0 else cut).rstrip(" ,;:—-") + "…"


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING_PARAMS.match(k)]
    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    scheme = "https" if parts.scheme in ("http", "https") else parts.scheme
    return urlunsplit((scheme, parts.netloc.lower(), path, urlencode(query), ""))


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(MSK)


def news_id(url: str) -> str:
    return "src:news:" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def normalize(item: "RawItem") -> Source | None:
    # «Импортный алкоголь подорожает | New Retail» — название издания в заголовке дублирует подпись карточки
    title = clean_text(item.title).removesuffix(f" | {item.publisher}").strip()
    url = canonical_url(item.link) if item.link else ""
    if not title or not url:
        return None
    lead = make_lead(item.summary, title)
    return Source(
        id=news_id(url),
        kind="news",
        title=title,
        publisher=item.publisher,
        reliability=item.reliability,
        url=url,
        published_at=parse_date(item.published),
        fragment=lead or title,
        image_url=item.image,
        source_icon_url=item.icon,
        text=item.text or None,
    )
