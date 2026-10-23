"""Абзацы распознанной страницы → фрагменты для поиска: без дисклеймеров и колонтитулов, заголовок вместе с текстом."""

import re
from dataclasses import dataclass, field

from ingest.analytics.ocr import OcrBlock

MIN_CHARS = 80
MAX_CHARS = 1500
TARGET_CHARS = 900
HEADING_MAX_CHARS = 140
MIN_CONFIDENCE = 55.0
MIN_LETTER_SHARE = 0.55

_BOILERPLATE = re.compile(
    "|".join(
        [
            r"все права защищены",
            r"генеральная лицензия",
            r"аффилированные лица",
            r"исключительной собственностью",
            r"несанкционированное копирование",
            r"не является деятельностью по инвестиционному",
            r"индивидуальной инвестиционной рекомендаци",
            r"контакты и дисклеймер",
            r"^центр макроэкономического анализа$",
            r"^аналитика альфа-киб",
            r"^\d{1,3}$",
        ]
    ),
    re.I,
)
# «Рис. 3: …», «Табл.2: …», «Источники: Росстат» — подписи к графикам и таблицам, сами графики не распознаём
_CAPTION = re.compile(r"^(рис|puc|табл|график|источник|примечание)\w*\.?\s*\d*\s*[:.]", re.I)
MAX_DEBRIS_SHARE = 0.3
_SHORT_WORDS = frozenset(
    "в и к с о у а я на по за до из от не же ли бы но то во со об ко ни их ее её он мы вы ты".split()
    + ["г", "гг", "т", "тч", "млн", "млрд", "%", "—", "–", "-", "м/м", "г/г", "н/н", "п.п"]
)
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=[«\"(А-ЯЁA-Z0-9])")


@dataclass
class Fragment:
    page: int
    text: str
    confidence: float


@dataclass
class PageReport:
    page: int
    blocks: int
    kept: int
    dropped: dict[str, int] = field(default_factory=dict)


def letter_share(text: str) -> float:
    visible = [c for c in text if not c.isspace()]
    if not visible:
        return 0.0
    return sum(c.isalpha() for c in visible) / len(visible)


def _is_debris(token: str) -> bool:
    word = token.strip('.,:;()«»"')
    if len(word) > 2 or word.lower() in _SHORT_WORDS:
        return False
    # «ЦБ», «РФ», «ЕС» — аббревиатуры, а не обрывки
    return not (len(word) == 2 and word.isalpha() and word.isupper())


def debris_share(text: str) -> float:
    """Доля обрывков в 1–2 знака, кроме предлогов и аббревиатур: у подписей осей и легенд графиков она высокая."""
    tokens = text.split()
    if not tokens:
        return 1.0
    return sum(_is_debris(t) for t in tokens) / len(tokens)


def classify(block: OcrBlock) -> str | None:
    """Почему блок не годится во фрагмент, или None, если годится."""
    text = block.text.strip()
    if _BOILERPLATE.search(text):
        return "дисклеймер или колонтитул"
    if _CAPTION.match(text):
        return "подпись к графику"
    if letter_share(text) < MIN_LETTER_SHARE:
        return "таблица или цифры"
    if debris_share(text) > MAX_DEBRIS_SHARE:
        return "оси и легенды графика"
    if block.confidence < MIN_CONFIDENCE:
        return "низкая уверенность распознавания"
    return None


def _is_heading(text: str) -> bool:
    return len(text) <= HEADING_MAX_CHARS and not text.rstrip().endswith((".", ";", ",", "…"))


def split_long(text: str, limit: int = MAX_CHARS, target: int = TARGET_CHARS) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for sentence in _SENTENCE_END.split(text):
        if current and len(current) + len(sentence) + 1 > target:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return parts


def page_fragments(page: int, blocks: list[OcrBlock]) -> tuple[list[Fragment], PageReport]:
    report = PageReport(page=page, blocks=len(blocks), kept=0)
    kept: list[OcrBlock] = []
    for block in blocks:
        reason = classify(block)
        if reason:
            report.dropped[reason] = report.dropped.get(reason, 0) + 1
        else:
            kept.append(block)

    fragments: list[Fragment] = []
    heading: OcrBlock | None = None
    for block in kept:
        text = block.text.strip()
        if _is_heading(text):
            # подряд идущие заголовки склеиваем: «Макростатистика 7М26» + «Данные по рынку труда…»
            if heading:
                conf = min(heading.confidence, block.confidence)
                heading = OcrBlock(f"{heading.text}. {text}", conf, heading.bbox)
            else:
                heading = block
            continue
        conf = block.confidence
        if heading:
            text = f"{heading.text.strip()}\n{text}"
            conf = min(conf, heading.confidence)
            heading = None
        for part in split_long(text):
            fragments.append(Fragment(page=page, text=part, confidence=conf))

    if heading and len(heading.text) >= MIN_CHARS:
        fragments.append(Fragment(page=page, text=heading.text.strip(), confidence=heading.confidence))

    # короткий хвост приклеиваем к предыдущему фрагменту, одиночный короткий — выбрасываем
    merged: list[Fragment] = []
    for frag in fragments:
        if len(frag.text) < MIN_CHARS:
            if merged and len(merged[-1].text) + len(frag.text) <= MAX_CHARS:
                merged[-1].text += " " + frag.text
                merged[-1].confidence = min(merged[-1].confidence, frag.confidence)
            else:
                report.dropped["слишком короткий"] = report.dropped.get("слишком короткий", 0) + 1
            continue
        merged.append(frag)
    report.kept = len(merged)
    return merged, report
