"""Числа в тексте утверждения и их сверка с источниками: модель не должна приносить цифры «из головы».

Даты, годы, номера периодов (4К26, 1П26), коды ОКВЭД и номера компаний — не числа-утверждения, их пропускаем.
Число подтверждено, если в источниках есть значение, которое при округлении до той же точности даёт его же:
«21 %» подтверждается долей 0,2096, «7,25 млрд» — суммой 7 250 888 000.
"""

import re
from dataclasses import dataclass

_MONTHS = r"(?:январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*"
_SKIP = [
    re.compile(r"\b\d{1,2}\s+" + _MONTHS, re.IGNORECASE),  # 11 сентября
    re.compile(r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b"),  # 11.09.2026
    re.compile(r"\b\d{2}\.\d{2}(?:\.\d{1,2})?\b"),  # 23.10, ОКВЭД 45.31.1
    re.compile(r"\b[1-4][КкQ]\d{2}\b|\b[12][ПпH]\d{2}\b|\b\d{1,2}[Мм]\d{2}\b"),  # 4К26, 1П26, 7М26
    re.compile(r"\b(?:19|20)\d{2}\b(?:\s*(?:г\.|года?|году|гг\.))?"),  # годы
    re.compile(r"№\s*\d+"),  # номера компаний
    re.compile(r"\bU_\d+\b|\bgroup_\d+\w*"),  # идентификаторы
    re.compile(r"\b\d{2}(?:[–-]\d{2})?\b(?=\s*\)?\s*(?:ОКВЭД|okved))", re.IGNORECASE),
    re.compile(r"(?:ОКВЭД|okved|класс[а-я]*)\s*\(?\s*\d{2}(?:[–-]\d{2})?", re.IGNORECASE),
]
_NUMBER = re.compile(
    r"(?<![\w.,])[-−–]?\d{1,3}(?:[   ]\d{3})+(?:,\d+)?(?![\d])|(?<![\w.,])[-−–]?\d+(?:[.,]\d+)?"
)


@dataclass(frozen=True)
class Number:
    value: float
    decimals: int
    raw: str
    unit: str = ""  # что стоит сразу после числа: «%», «млрд», «п.п.»


def _strip(text: str) -> str:
    for pattern in _SKIP:
        text = pattern.sub(" ", text)
    return text


def numbers_in(text: str) -> list[Number]:
    found = []
    stripped = _strip(text)
    for m in _NUMBER.finditer(stripped):
        raw = m.group(0)
        clean = re.sub(r"[   ]", "", raw).replace("−", "-").replace("–", "-").replace(",", ".")
        try:
            value = abs(float(clean))
        except ValueError:
            continue
        decimals = len(clean.split(".", 1)[1]) if "." in clean else 0
        unit = stripped[m.end() : m.end() + 8].strip().lower()
        found.append(Number(value, decimals, raw, unit))
    return found


def variants(value: float) -> list[float]:
    """Как число из данных может быть записано человеком: доля → проценты, рубли → млн и млрд."""
    value = abs(value)
    out = [value]
    if value <= 1:
        out.append(value * 100)
    if value >= 1e5:
        out += [value / 1e3, value / 1e6, value / 1e9, value / 1e12]
    return out


_MEASURE_UNITS = ("%", "п.п", "п. п", "процент", "млн", "млрд", "трлн", "тыс", "₽", "руб", "раз", "б.п")


class NumberBank:
    """Множество чисел, на которые утверждение может опереться."""

    def __init__(self) -> None:
        self.values: set[float] = set()

    def add_text(self, text: str | None) -> None:
        if not text:
            return
        for n in numbers_in(text):
            self.values.add(n.value)

    def add_value(self, value) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, int | float):
            self.values.update(variants(float(value)))
        elif isinstance(value, str):
            self.add_text(value)
        elif isinstance(value, list | tuple):
            for v in value:
                self.add_value(v)

    def supports(self, n: Number) -> bool:
        # мелкие целые (1–10) обычно счётные: «3 компании», «2 квартала» — их не проверяем, но не проценты,
        # пункты и суммы: «на 8 %», «на 2 п.п.», «3 млрд»
        if n.decimals == 0 and n.value <= 10 and not n.unit.startswith(_MEASURE_UNITS):
            return True
        return any(round(v, n.decimals) == round(n.value, n.decimals) for v in self.values)

    def unsupported(self, text: str) -> list[str]:
        return [n.raw for n in numbers_in(text) if not self.supports(n)]


_MONEY = re.compile(
    r"\d[\d   ,.]*\s*(?:тыс\.?|млн|млрд|трлн)?\s*(?:₽|руб\.?|рубл\w*)"
    r"|\d[\d   ,.]*\s*(?:тыс\.?|млн|млрд|трлн)\.?\s+(?:₽|руб|рубл|долл|\$|юан)",
    re.IGNORECASE,
)


_SCALED = re.compile(
    r"\d[\d   ,.]*\s*(?:тысяч\w*|миллион\w*|миллиард\w*|триллион\w*)\s+(?:₽|руб|рубл|долл|\$|юан|евро)",
    re.IGNORECASE,
)
# сумма с множителем без валюты, но рядом со словами о деньгах: «потери до 5 млрд», «расходы вырастут на 300
# млн»
_SCALED_BARE = re.compile(
    r"\d[\d   ,.]*\s*(?:тыс\.?|млн|млрд|трлн|тысяч\w*|миллион\w*|миллиард\w*|триллион\w*)(?![а-я])",
    re.IGNORECASE,
)
_MONEY_WORDS = re.compile(
    r"выручк|расход|убыт|прибыл|затрат|долг|экономи|потер|издерж|доход|стоимост|платеж|платёж|процент\w* в "
    r"год|"
    r"в год|в месяц|в квартал",
    re.IGNORECASE,
)
_MULTIPLIER = re.compile(r"тыс|млн|млрд|трлн|тысяч|миллион|миллиард|триллион", re.IGNORECASE)
# курс валюты — не сумма: «81 руб. за доллар», «87,2 ₽/$», «курс доллара … 81 руб.»
_RATE_AFTER = re.compile(r"^\s*(?:/|за\s+(?:1\s+)?(?:доллар|долл|евро|юан|\$|€|¥))", re.IGNORECASE)
_RATE_BEFORE = re.compile(r"курс\w*(?:\s+\S+){0,4}\s*$", re.IGNORECASE)


def money_in(text: str) -> list[str]:
    """Суммы в рублях (и других деньгах с множителем) — модель сама их писать не должна. Курсы валют — можно.

    Сумма с множителем (тыс., млн, млрд) — всегда деньги; без множителя рядом со словом «курс» или с «/$»,
    «за доллар» — это курс.
    """
    out = []
    found = [*_MONEY.finditer(text), *_SCALED.finditer(text)]
    for m in _SCALED_BARE.finditer(text):
        near = text[max(0, m.start() - 40) : m.end() + 25]
        covered = any(f.start() <= m.start() < f.end() for f in found)
        if not covered and _MONEY_WORDS.search(near):
            found.append(m)
    for m in found:
        raw = m.group(0)
        if not _MULTIPLIER.search(raw) and (
            _RATE_AFTER.match(text[m.end() :]) or _RATE_BEFORE.search(text[: m.start()])
        ):
            continue
        out.append(raw.strip())
    return out
