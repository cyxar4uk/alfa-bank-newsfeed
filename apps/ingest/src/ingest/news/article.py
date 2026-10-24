"""Текст и картинка статьи из HTML: заголовок, дата, издатель, абзацы без меню и скрытых блоков, og:image.

Общий код для парсера (полный текст и картинки новостей из лент) и для разбора своей новости в API
(`api.search.analyze`). Страница — только данные: ничего по её содержимому не выполняется.
"""

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

from ingest.news.normalize import clean_text, strip_dateline


def _charset(content_type: str, head: bytes) -> str | None:
    m = re.search(r"charset=([\w-]+)", content_type, re.I) or re.search(
        rb"<meta[^>]+charset=[\"']?([\w-]+)", head, re.I
    )
    if not m:
        return None
    value = m.group(1)
    return value.decode("ascii", "ignore") if isinstance(value, bytes) else value


def _decode(data: bytes, content_type: str) -> str:
    for enc in (_charset(content_type, data[:4096]), "utf-8"):
        if enc:
            try:
                return data.decode(enc)
            except (LookupError, UnicodeDecodeError):
                continue
    return data.decode("cp1251", errors="replace")


# --- Текст статьи из HTML -------------------------------------------------------------------------

_SKIP = {
    "script", "style", "noscript", "template", "svg", "nav", "header", "footer", "aside", "form", "button",
    "iframe", "select", "figure", "figcaption",
}  # fmt: skip
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_BLOCK = {
    "p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "article", "section", "blockquote", "br", "td",
    "tr", "ul", "ol", "main", "dd", "dt", "pre",
}  # fmt: skip
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)
MIN_BLOCK_CHARS = 60


@dataclass
class Article:
    title: str = ""
    description: str = ""
    site: str = ""
    published: str | None = None
    body: str = ""
    image: str | None = None  # og:image, twitter:image или картинка из JSON-LD — абсолютной ссылкой http(s)
    meta: dict[str, str] = field(default_factory=dict)


class _Extractor(HTMLParser):
    """Блоки текста вне служебных и скрытых элементов; мета-теги; JSON-LD статьи."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip: list[str] = []
        self.blocks: list[tuple[str, int]] = []  # (текст, символов в ссылках)
        self.buf: list[str] = []
        self.link_chars = 0
        self.in_link = 0
        self.meta: dict[str, str] = {}
        self.title = ""
        self.h1 = ""
        self.time: str | None = None
        self.in_title = False
        self.in_h1 = False
        self.ld: list[str] = []
        self.in_ld = False

    def _flush(self) -> None:
        text = clean_text(" ".join(self.buf))
        if text:
            self.blocks.append((text, self.link_chars))
        self.buf, self.link_chars = [], 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if key and a.get("content") and key not in self.meta:
                self.meta[key] = a["content"]
            return
        if tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self.in_ld = True
            self.ld.append("")
            return
        if tag == "time" and a.get("datetime") and self.time is None:
            self.time = a["datetime"]
        if tag in _VOID:
            if tag == "br" and not self.skip:
                self._flush()
            return
        hidden = "hidden" in a or a.get("aria-hidden", "").lower() == "true" or _HIDDEN_STYLE.search(a.get("style", ""))
        if self.skip or tag in _SKIP or hidden:
            self.skip.append(tag)
            return
        if tag in _BLOCK:
            self._flush()
        if tag == "a":
            self.in_link += 1
        self.in_title = tag == "title"
        self.in_h1 = tag == "h1" or self.in_h1

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.in_ld:
            self.in_ld = False
            return
        if self.skip:
            # незакрытые <p> и <li> внутри пропускаемого блока не должны держать пропуск до конца страницы
            if tag in self.skip:
                while self.skip.pop() != tag:
                    pass
            return
        if tag in _BLOCK:
            self._flush()
        if tag == "a" and self.in_link:
            self.in_link -= 1
        if tag == "title":
            self.in_title = False
        if tag == "h1":
            self.in_h1 = False

    def handle_data(self, data: str) -> None:
        if self.in_ld:
            self.ld[-1] += data
            return
        if self.in_title:
            self.title += data
            return
        if self.skip:
            return
        if self.in_h1:
            self.h1 += data
        self.buf.append(data)
        if self.in_link:
            self.link_chars += len(data.strip())

    def close(self) -> None:
        super().close()
        self._flush()


def _ld_article(chunks: list[str]) -> dict[str, Any]:
    """Первая статья из JSON-LD (NewsArticle, Article, ReportageNewsArticle…)."""
    stack: list[Any] = []
    for raw in chunks:
        try:
            stack.append(json.loads(raw))
        except ValueError:
            continue
    while stack:
        node = stack.pop(0)
        if isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, dict):
            kind = node.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            if any(isinstance(k, str) and k.endswith("Article") for k in kinds):
                return node
            stack.extend(v for k, v in node.items() if k == "@graph")
    return {}


def _mostly_digits(text: str) -> bool:
    """Телефоны, курсы и котировки в шапке сайта: букв меньше 60 % значащих знаков."""
    chars = [c for c in text if not c.isspace()]
    return sum(c.isalpha() for c in chars) < 0.6 * len(chars)


def container_html(html: str, css_class: str) -> str | None:
    """HTML элемента с классом css_class (первого) — по парным тегам того же имени. Нет такого — None."""
    cls = rf"(?<![\w-]){re.escape(css_class)}(?![\w-])"
    m = re.search(rf"<(\w+)\b[^>]*\bclass\s*=\s*[\"'][^\"']*{cls}[^\"']*[\"'][^>]*>", html)
    if not m:
        return None
    tag, depth = m.group(1).lower(), 1
    for t in re.finditer(rf"<(/?){tag}\b[^>]*>", html[m.end() :], flags=re.I):
        depth += -1 if t.group(1) else 1
        if depth == 0:
            return html[m.start() : m.end() + t.end()]
    return html[m.start() :]


def extract_article(html: str, url: str = "", container: str | None = None) -> Article:
    """container — класс элемента со статьёй, если общий разбор берёт не то (у government.ru — календарь)."""
    parser = _Extractor()
    parser.feed(html)
    parser.close()
    meta = parser.meta
    ld = _ld_article(parser.ld)
    publisher = ld.get("publisher") if isinstance(ld.get("publisher"), dict) else {}

    blocks = parser.blocks
    # всё до заголовка статьи — шапка сайта (телефоны, меню); сам заголовок идёт в title, не в текст
    h1 = clean_text(parser.h1)
    start = next((i for i, (text, _) in enumerate(blocks) if h1 and text == h1), -1)
    inner = container_html(html, container) if container else None
    if container:
        part = _Extractor()
        part.feed(inner or "")
        part.close()
        blocks, start = part.blocks, -1
    seen, kept = set(), []
    for text, link_chars in blocks[start + 1 :]:
        # меню, подписи и списки ссылок короткие или почти целиком из ссылок
        if len(text) < MIN_BLOCK_CHARS or link_chars > len(text) / 2 or text in seen or _mostly_digits(text):
            continue
        seen.add(text)
        kept.append(text)
    body = "\n".join(kept)
    ld_body = clean_text(str(ld.get("articleBody") or ""))
    if len(ld_body) > len(body) * 0.8 and len(ld_body) >= MIN_BLOCK_CHARS:
        body = ld_body

    host = (urlsplit(url).hostname or "").removeprefix("www.")
    return Article(
        title=clean_text(meta.get("og:title") or str(ld.get("headline") or "") or parser.h1 or parser.title),
        description=clean_text(meta.get("og:description") or meta.get("description") or ""),
        site=clean_text(meta.get("og:site_name") or str(publisher.get("name") or "") or host),
        published=meta.get("article:published_time")
        or meta.get("datepublished")
        or (str(ld["datePublished"]) if ld.get("datePublished") else None)
        or parser.time,
        body=body,
        image=_image(meta, ld, url),
        meta=meta,
    )


def _image(meta: dict[str, str], ld: dict[str, Any], url: str) -> str | None:
    """Картинка статьи: og:image, twitter:image, image из JSON-LD — первая, что похожа на ссылку http(s)."""
    raw = ld.get("image")
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if isinstance(raw, dict):
        raw = raw.get("url")
    for candidate in (meta.get("og:image"), meta.get("og:image:url"), meta.get("twitter:image"), raw):
        if candidate and isinstance(candidate, str) and (image := usable_image(urljoin(url, candidate.strip()))):
            return image
    return None


# общие заглушки вместо картинки материала: логотип издания, «картинка для соцсетей» сайта (share-1.jpg у ЦБ)
_PLACEHOLDER = re.compile(r"(?:^|[_.-])(?:logo|dummy|placeholder|no[_-]?image|share)(?:[_.-]|$)", re.I)


def usable_image(url: str) -> str | None:
    """Ссылка на картинку материала, если она http(s) и не похожа на общую заглушку сайта, иначе None."""
    parts = urlsplit(url)
    # смотрим только имя файла и целые слова: «/sites/default/files/…» и «ecologo.jpg» — обычные фотографии
    if parts.scheme not in ("http", "https") or _PLACEHOLDER.search(parts.path.rsplit("/", 1)[-1]):
        return None
    return url


_INVISIBLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")


def html_paragraphs(html: str) -> str:
    """Все абзацы фрагмента HTML (полный текст из ленты): без скрытого и служебного, короткие абзацы не выбрасываем."""
    parser = _Extractor()
    parser.feed(html or "")
    parser.close()
    return clean_body("\n".join(text for text, _ in parser.blocks))


def clean_body(text: str) -> str:
    """Убрать невидимые символы (ими прячут текст), выровнять пробелы, абзацы оставить."""
    text = _INVISIBLE.sub("", text.replace("\r\n", "\n"))
    # «Москва. 23 октября. INTERFAX.RU - » в начале абзаца — служебная строка ленты, как в лидах парсера
    paragraphs = (strip_dateline(clean_text(p)) for p in re.split(r"\n\s*", text))
    return "\n".join(p for p in paragraphs if p)
