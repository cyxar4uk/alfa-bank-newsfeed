"""Сверка Tesseract с Qwen3-VL: исправление слов, распознанных латиницей или с «и» вместо «й».

Tesseract на русских сканах путает похожие буквы: «конец» читает как «KOHeL», «Рис.» — как «Puc.», «этом» — как
«stom», «руб.» — как «py6.», а «й» — как «и» («воздеиствовать»). Такие слова попадают в цитату банка, которую видит
пользователь. У каждой страницы есть второй, независимый текст — Qwen3-VL; он читает буквы правильно, но местами
пересказывает, поэтому целиком его не берём.

Правило: слово Tesseract заменяется, только если его нет в тексте Qwen той же страницы, а исправленный вариант там
есть, и вариант единственный. Числа, коды с цифрами, аббревиатуры до трёх букв (рейтинги BBB, «МТС» латиницей) не
трогаем; короткие слова («Ha», «He») — только внутри русской фразы. Каждая замена записывается в `ocr_fixes`
страницы: исправление видно и проверяемо.
"""

import re
from collections import Counter
from dataclasses import dataclass, field, replace

from ingest.analytics.ocr import OcrBlock

TOKEN = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+")
_LAT = re.compile(r"[A-Za-z]")
_CYR = re.compile(r"[А-Яа-яЁё]")
_DIGIT = re.compile(r"[0-9]")
# латинская буква (и цифра внутри слова) → русские буквы, за которые её принимает Tesseract
LOOKALIKE: dict[str, str] = {
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М", "O": "О", "P": "Р", "T": "Т", "X": "Х",
    "Y": "У", "F": "Г",
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у", "r": "г", "n": "п", "u": "и", "k": "к",
    "t": "т", "m": "тм", "b": "ьб", "6": "б", "3": "з",
}  # fmt: skip
_VOWELS = set("аеоуыэюя")
# сколько латинских букв без пары («L» в «KOHeL») допускаем: каждая — любая русская буква
MAX_UNKNOWN = 1


def _norm(word: str) -> str:
    return word.lower().replace("ё", "е")


@dataclass
class Reference:
    """Эталон страницы (текст Qwen): написание слов и пары соседних слов — чтобы выбрать из «этот» и «этом»."""

    forms: dict[str, str] = field(default_factory=dict)
    pairs: set[tuple[str, str]] = field(default_factory=set)
    text: str = ""
    variants: dict[str, Counter] = field(default_factory=dict)  # все написания слова у Qwen

    def cased(self, word: str, start: bool) -> str:
        """Написание слова: имя собственное и аббревиатура — как у Qwen, остальное — строчное, с заглавной
        только в начале предложения. Регистр Tesseract у латиницы не верен: «основного» он читает как «OCHOBHOFO»."""
        variants = self.variants.get(word)
        if not variants:
            return self.forms[word]
        if all(v[:1].isupper() for v in variants):
            return variants.most_common(1)[0][0]
        lower = next(v for v, _ in variants.most_common() if v[:1].islower())
        return lower[0].upper() + lower[1:] if start else lower

    def __contains__(self, word: str) -> bool:
        return word in self.forms

    def __getitem__(self, word: str) -> str:
        return self.forms[word]

    def get(self, word: str) -> str | None:
        return self.forms.get(word)


def reference(text: str | None) -> Reference:
    """Слова эталонного текста: нормализованное → самое частое написание (с регистром), и пары соседних слов."""
    words = TOKEN.findall(text or "")
    forms: dict[str, Counter] = {}
    for w in words:
        forms.setdefault(_norm(w), Counter())[w] += 1
    pairs = {(_norm(a), _norm(b)) for a, b in zip(words, words[1:], strict=False)}
    return Reference({k: c.most_common(1)[0][0] for k, c in forms.items()}, pairs, text or "", forms)


def _latin_word(
    word: str, ref: Reference, prev: str | None = None, nxt: str | None = None, start: bool = False
) -> str | None:
    unknown = 0
    pattern = []
    for ch in word:
        if _CYR.match(ch):
            pattern.append(re.escape(_norm(ch)))
        elif ch in LOOKALIKE:
            pattern.append("[" + _norm(LOOKALIKE[ch]) + "]")
        elif _LAT.match(ch):
            unknown += 1
            pattern.append("[а-я]")
        else:
            return None  # цифра без пары — это код или число, не слово
    if not any(ch in LOOKALIKE or _CYR.match(ch) for ch in word) or unknown > MAX_UNKNOWN:
        return None
    if unknown and len(word) < 4:
        return None
    rx = re.compile("".join(pattern) + "$")
    hits = [k for k in ref.forms if len(k) == len(word) and rx.match(k)]
    if len(hits) > 1:  # «stom»: «этот» или «этом» — решает соседнее слово, как у Qwen («При этом»)
        hits = [k for k in hits if (prev and (_norm(prev), k) in ref.pairs) or (nxt and (k, _norm(nxt)) in ref.pairs)]
    if len(hits) != 1:
        return None
    return ref.cased(hits[0], start)


def _short_i(word: str, ref: Reference, start: bool = False) -> str | None:
    """«й», прочитанная как «и», — только после гласной: «ключевои», «деиствовать»; «вакансии», «поиск» не трогаем."""
    n = _norm(word)
    if len(n) < 5:
        return None
    for i, ch in enumerate(n):
        if ch == "и" and i > 0 and n[i - 1] in _VOWELS:
            fixed = n[:i] + "й" + n[i + 1 :]
            if fixed in ref:
                # кириллица в Tesseract сама по себе верна, её регистр сохраняем: «КЛЮЧЕВОИ» → «КЛЮЧЕВОЙ»
                if word.isupper():
                    return fixed.upper()
                form = ref.cased(fixed, start or word[0].isupper())
                return form[0].upper() + form[1:] if word[0].isupper() else form
    return None


# в кодах (ISIN, номера выпусков) Tesseract путает буквы и цифры: RUOOOA10F7LO вместо RU000A10F7L0
_CODE_SWAPS = {"O": "0O", "0": "0O", "I": "1I", "1": "1Il", "l": "1l", "S": "5S", "5": "5S", "B": "8B", "8": "8B"}
CODE_MIN_CHARS = 6


_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def isin_ok(code: str) -> bool:
    """Контрольная цифра ISIN (алгоритм Луна по цифрам, где буква — её номер: A = 10 … Z = 35)."""
    if not _ISIN.match(code):
        return False
    digits = "".join(str(int(c, 36)) for c in code)
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def _code(word: str, ref: Reference) -> str | None:
    """Код с цифрами: тот же код у Qwen с точностью до пар O/0, I/1, S/5, B/8 — и только один такой.

    ISIN Qwen тоже мог прочитать с ошибкой — его код берём, только если сходится контрольная цифра."""
    rx = re.compile(
        "".join("[" + re.escape(_CODE_SWAPS[c]) + "]" if c in _CODE_SWAPS else re.escape(c) for c in word) + "$"
    )
    hits = {form for form in ref.forms.values() if len(form) == len(word) and rx.match(form)}
    if len(hits) != 1:
        return None
    code = hits.pop()
    if len(code) == 12 and code[:2].isalpha() and code[:2].isupper() and not isin_ok(code):
        return None
    return code


def _word_of(word: str | None, ref: Reference) -> bool:
    return bool(word) and len(word) >= 3 and _norm(word) in ref


def fix_word(
    word: str, ref: Reference, prev: str | None = None, nxt: str | None = None, start: bool = False
) -> str | None:
    """Исправление слова по эталону страницы или None, если исправлять нечего или вариант не однозначен.

    start — слово в начале предложения: тогда у нарицательного слова заглавная буква."""
    if _norm(word) in ref:
        return None
    if _DIGIT.search(word) and _LAT.search(word) and len(word) >= CODE_MIN_CHARS:
        fixed = _code(word, ref)
        return fixed if fixed and fixed != word else None
    if _LAT.search(word):
        if (word.isupper() and len(word) <= 3) or len(word) == 1:
            return None
        # «Ha», «He» — только внутри фразы: оба соседа — слова из текста Qwen, не обрывки легенды графика
        if len(word) == 2 and not (_word_of(prev, ref) and _word_of(nxt, ref)):
            return None
        fixed = _latin_word(word, ref, prev, nxt, start)
    elif _CYR.search(word) and not _DIGIT.search(word):
        fixed = _short_i(word, ref, start)
    else:
        return None
    return fixed if fixed and fixed != word else None


# «2026 r.» — год с латинской «r» вместо «г.»; «rir», «r/r» — «г/г» (год к году). Только если так пишет и Qwen.
_PATTERNS = (
    (re.compile(r"(?<=\b\d{4}) r\.(?=[\s,;:)]|$)"), " г.", re.compile(r"\d{4} г\.")),
    (re.compile(r"(?<![\w/])(?:rir|r/r)(?![\w/])"), "г/г", re.compile(r"г/г")),
)


def _sentence_start(before: str, word: str) -> bool:
    """Начало предложения: у Tesseract заглавная, и слово стоит в начале блока, строки или после «.!?».

    Строчную латиницу Tesseract читает надёжно: «млрд. py6.» — это «руб.», а не новое предложение после точки."""
    if not word[:1].isupper():
        return False
    tail = before.rstrip(" \t«\"'(")
    return not tail.strip() or tail.endswith("\n") or tail[-1] in ".!?…"


def fix_text(text: str, ref: Reference) -> tuple[str, list[tuple[str, str]]]:
    """Заменить слова по эталону; остальное (пробелы, знаки, переносы) не меняется."""
    fixes: list[tuple[str, str]] = []
    for rx, repl, needed in _PATTERNS:
        if needed.search(ref.text) and rx.search(text):
            fixes += [(m.group(0).strip(), repl.strip()) for m in rx.finditer(text)]
            text = rx.sub(repl, text)
    matches = list(TOKEN.finditer(text))
    out, pos = [], 0
    for i, m in enumerate(matches):
        prev = matches[i - 1].group(0) if i else None
        nxt = matches[i + 1].group(0) if i + 1 < len(matches) else None
        fixed = fix_word(m.group(0), ref, prev, nxt, _sentence_start(text[: m.start()], m.group(0)))
        if fixed is None:
            continue
        out.append(text[pos : m.start()])
        out.append(fixed)
        fixes.append((m.group(0), fixed))
        pos = m.end()
    out.append(text[pos:])
    return "".join(out), fixes


def absent_share(text: str, ref: Reference) -> tuple[float, int]:
    """Доля слов, которых нет в эталоне страницы, и число слов: мера мусора в тексте основного движка.

    Считаются слова от трёх знаков без чисел: короткие обрывки есть и в нормальном тексте, и в подписях графиков."""
    words = [w for w in TOKEN.findall(text) if not w.isdigit() and len(w) >= 3]
    if not words:
        return 0.0, 0
    return sum(_norm(w) not in ref for w in words) / len(words), len(words)


def fix_blocks(
    blocks: list[OcrBlock], vlm_blocks: list[OcrBlock] | None
) -> tuple[list[OcrBlock], list[tuple[str, str]]]:
    """Блоки основного движка, исправленные по тексту Qwen той же страницы. Без Qwen — как есть."""
    if not vlm_blocks:
        return blocks, []
    ref = reference("\n".join(b.text for b in vlm_blocks))
    out, fixes = [], []
    for b in blocks:
        text, found = fix_text(b.text, ref)
        out.append(replace(b, text=text) if found else b)
        fixes += found
    return out, fixes
