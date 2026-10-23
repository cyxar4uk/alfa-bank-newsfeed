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
    replaced_by_vlm: int = 0
    added_from_vlm: int = 0


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


_TABLE_RULE = re.compile(r"^[|\s:-]+$")


def is_table(text: str) -> bool:
    """Таблица от мультимодальной модели: строки с ячейками через « | »."""
    return sum(" | " in line for line in text.splitlines()) >= 2


def clean_table(text: str) -> str:
    """Убирает строки-разделители Markdown («|---|---|») из таблицы; обычный текст не меняет."""
    if not is_table(text):
        return text
    return "\n".join(line for line in text.splitlines() if not _TABLE_RULE.match(line))


def classify_table(text: str) -> str | None:
    """Таблица без подписанных строк — это оцифрованные оси графика («01.02.19 | 01.07.19 | …»), а не данные."""
    rows = [line for line in text.splitlines() if " | " in line]
    labelled = [row for row in rows if sum(c.isalpha() for c in row.split(" | ")[0]) >= 3]
    return None if rows and len(labelled) / len(rows) >= 0.5 else "оси и легенды графика"


def _attach_captions(blocks: list[OcrBlock]) -> list[OcrBlock]:
    """Подпись «Табл.2: …» перед таблицей становится её заголовком, а не отбрасывается как подпись к графику."""
    out: list[OcrBlock] = []
    for block in blocks:
        if out and is_table(block.text) and _CAPTION.match(out[-1].text.strip()):
            caption = out.pop()
            block = OcrBlock(f"{caption.text.strip()}\n{block.text}", block.confidence, block.bbox)
        out.append(block)
    return out


def _is_heading(text: str) -> bool:
    return len(text) <= HEADING_MAX_CHARS and not text.rstrip().endswith((".", ";", ",", "…"))


def split_long(text: str, limit: int = MAX_CHARS, target: int = TARGET_CHARS) -> list[str]:
    if len(text) <= limit or is_table(text):
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


def page_fragments(page: int, blocks: list[OcrBlock], allow_tables: bool = False) -> tuple[list[Fragment], PageReport]:
    """allow_tables — для текста мультимодальной модели: её таблицы читаемы, их оставляем вместе с подписью."""
    report = PageReport(page=page, blocks=len(blocks), kept=0)
    if allow_tables:
        blocks = [OcrBlock(clean_table(b.text), b.confidence, b.bbox) for b in _attach_captions(blocks)]
    # индекс блока на странице нужен, чтобы склеивать только соседние блоки: тогда любое предложение фрагмента
    # стоит в тексте страницы подряд и цитату банка можно сверить дословно
    kept: list[tuple[int, OcrBlock]] = []
    for idx, block in enumerate(blocks):
        reason = classify_table(block.text) if allow_tables and is_table(block.text) else classify(block)
        if reason:
            report.dropped[reason] = report.dropped.get(reason, 0) + 1
        else:
            kept.append((idx, block))

    pieces: list[tuple[Fragment, int, int]] = []  # фрагмент, первый и последний блок
    heading: tuple[str, float, int, int] | None = None  # текст, уверенность, первый и последний блок

    def flush_heading() -> None:
        if heading and len(heading[0]) >= MIN_CHARS:
            pieces.append((Fragment(page=page, text=heading[0], confidence=heading[1]), heading[2], heading[3]))

    for idx, block in kept:
        text = block.text.strip()
        if heading and heading[3] != idx - 1:
            # между заголовком и этим блоком что-то отброшено — склеивать нельзя
            flush_heading()
            heading = None
        if _is_heading(text):
            # подряд идущие заголовки склеиваем: «Макростатистика 7М26» + «Данные по рынку труда…»
            if heading:
                heading = (f"{heading[0]}\n{text}", min(heading[1], block.confidence), heading[2], idx)
            else:
                heading = (text, block.confidence, idx, idx)
            continue
        first, conf = idx, block.confidence
        if heading:
            text, conf, first = f"{heading[0]}\n{text}", min(conf, heading[1]), heading[2]
            heading = None
        for part in split_long(text):
            pieces.append((Fragment(page=page, text=part, confidence=conf), first, idx))
    flush_heading()

    # короткий хвост приклеиваем к соседнему предыдущему фрагменту, одиночный короткий — выбрасываем
    merged: list[tuple[Fragment, int, int]] = []
    for frag, first, last in pieces:
        if len(frag.text) < MIN_CHARS:
            prev = merged[-1] if merged else None
            if prev and prev[2] in (first - 1, first) and len(prev[0].text) + len(frag.text) <= MAX_CHARS:
                prev[0].text += " " + frag.text
                prev[0].confidence = min(prev[0].confidence, frag.confidence)
                merged[-1] = (prev[0], prev[1], last)
            else:
                report.dropped["слишком короткий"] = report.dropped.get("слишком короткий", 0) + 1
            continue
        merged.append((frag, first, last))
    report.kept = len(merged)
    return [frag for frag, _, _ in merged], report
