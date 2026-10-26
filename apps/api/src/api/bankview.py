"""Позиция Альфа-Банка по теме для экранов «Главное за неделю» и «К чему уязвима компания».

Фрагменты аналитики банка по фактору и запросу темы (`NewsProvider.bank_fragments`) → одна фраза о теме: лучше
прогноз («мы ожидаем…») с числом, иначе фраза о теме с числом. Фразы о теме во фрагментах нет — позиции банка
нет: подставлять случайное предложение из материала нельзя.

«Прогноз устарел» — если в фразе банка и в свежей новости есть число об одном и том же (Urals, Brent, ключевая
ставка, курс доллара) и они расходятся больше чем на 10 %, а новость новее материала. Только эти случаи: в
остальном расхождение не определить, и пометки нет.
"""

import datetime as dt
import re
from collections.abc import Callable
from typing import Any

from api.contract import BankView
from api.ranking import MSK

OUTDATED_GAP = 0.10
STATEMENT_MAX = 220

# тема → запрос к аналитике банка и основы слов, по которым фраза считается фразой о теме
TOPICS: dict[str, tuple[str, tuple[str, ...]]] = {
    "rate": ("ключевая ставка прогноз", ("ставк",)),
    "deposit_yield": ("доходность депозитов ставка", ("доходност", "депозит", "ставк")),
    "fx": ("курс рубля доллар прогноз", ("курс", "рубл", "доллар", "валют", "евро", "юан")),
    "commodity_oil": ("нефть Urals Brent прогноз", ("нефт", "urals", "brent")),
    "inflation": ("инфляция прогноз", ("инфляц",)),
    "gov": ("бюджет госрасходы", ("бюджет", "расход")),
    "consumer": ("потребительский спрос", ("спрос", "потреб")),
    "labor": ("рынок труда зарплаты", ("зарплат", "труд", "безработ")),
    "ved_logistics": ("внешняя торговля импорт экспорт санкции", ("импорт", "экспорт", "санкци")),
    "tax_regulation": ("налоги", ("налог",)),
}
_FORECAST = re.compile(r"ожида|прогноз|считаем|оцениваем|полагаем|закладываем")
# не делим после сокращений: «г. Москва», «руб. Курс», «млрд. руб.»
_SENTENCE = re.compile(
    r"(?<!\bг\.)(?<!руб\.)(?<!млрд\.)(?<!млн\.)(?<!трлн\.)(?<!тыс\.)(?<=[.!?:])\s+(?=[А-ЯЁA-Z])"
)
# число с единицей — а не год «2026»: «14,0%», «87 руб./$», «$340 млрд», «5,8 трлн руб.»
_MEASURE = re.compile(r"\d+(?:[.,]\d+)?\s?(?:%|п\.\s?п|млрд|млн|трлн|тыс|руб|₽|долл|\$)|\$\s?\d")

# предмет → как найти его число в тексте
# цена нефти — в долларах, не процент изменения («Urals подешевела на 3%» — не цена); ставка — только
# ключевая и только уровень («до 14,5%»), не «снижение на 1%» и не «ставка НДС 20%»
_ANCHORS = {
    "Urals": re.compile(
        r"urals[^\d$]{0,25}\$\s?(\d+(?:[.,]\d+)?)(?!\s?%|\s?п\.)|urals[^\d$]{0,25}(\d+(?:[.,]\d+)?)\s?(?:долл|\$)"
    ),
    "Brent": re.compile(
        r"brent[^\d$]{0,25}\$\s?(\d+(?:[.,]\d+)?)(?!\s?%|\s?п\.)|brent[^\d$]{0,25}(\d+(?:[.,]\d+)?)\s?(?:долл|\$)"
    ),
    "ставку": re.compile(
        r"ключев\w*\s+ставк\w*(?:\s+(?!на\b)\S+){0,4}?\s+"
        r"(?:до\s+|на уровне\s+|в\s+|—\s+)?(\d+(?:[.,]\d+)?)\s?%"
    ),
    "доллар по": re.compile(
        r"(\d+(?:[.,]\d+)?)\s?(?:₽|руб\w*)\s+за\s+доллар|доллар\w*[^\d]{0,25}(\d+(?:[.,]\d+)?)\s?(?:₽|руб)"
    ),
}


def _number(text: str, anchor: re.Pattern) -> float | None:
    m = anchor.search(text.casefold())
    if not m:
        return None
    value = next(g for g in m.groups() if g)
    return float(value.replace(",", "."))


def _shown(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def outdated_note(bank_text: str, news_title: str) -> str | None:
    """«банк ждал Urals $63, в новостях — $72» или None, если числа не о том же или не расходятся."""
    for name, anchor in _ANCHORS.items():
        bank, news = _number(bank_text, anchor), _number(news_title, anchor)
        if bank and news and abs(news - bank) / bank > OUTDATED_GAP:
            unit = "$" if name in ("Urals", "Brent") else ""
            tail = " %" if name == "ставку" else (" ₽" if name == "доллар по" else "")
            return f"банк ждал {name} {unit}{_shown(bank)}{tail}, в новостях — {unit}{_shown(news)}{tail}"
    return None


def statements(text: str, stems: tuple[str, ...]) -> list[tuple[bool, str]]:
    """Фразы о теме с числом: (прогноз ли, фраза); о теме ничего — пусто."""
    # заголовки и подписи во фрагменте — отдельными строками: сначала строки, потом предложения
    sentences = [
        s.strip()
        for line in text.splitlines()
        for s in _SENTENCE.split(" ".join(line.split()))
        if s.strip() and "|" not in s  # строки таблиц — не позиция
    ]
    about = [s for s in sentences if any(stem in s.casefold() for stem in stems) and _MEASURE.search(s)]
    return [(bool(_FORECAST.search(s.casefold())), s) for s in about]


def statement(text: str, stems: tuple[str, ...]) -> str | None:
    """Фраза о теме: прогноз с числом, иначе фраза о теме с числом; о теме ничего — None."""
    found = statements(text, stems)
    chosen = next((s for forecast, s in found if forecast), found[0][1] if found else None)
    return _cut(chosen) if chosen else None


def _cut(text: str) -> str:
    return text if len(text) <= STATEMENT_MAX else text[: STATEMENT_MAX - 1].rsplit(" ", 1)[0] + "…"


def bank_view(
    code: str,
    fragments_fn: Callable[[list[str], str], list[Any]] | None,
    news_title: str | None = None,
    news_date: dt.date | None = None,
) -> BankView | None:
    """Позиция банка по теме `code` или None; `news_title` — свежая новость для сверки «прогноз устарел».

    Из всех найденных фрагментов — прогноз банка, при равенстве — из более свежего материала.
    """
    if fragments_fn is None or code not in TOPICS:
        return None
    query, stems = TOPICS[code]
    candidates = []
    for rank, fragment in enumerate(fragments_fn([code], query)):
        published = fragment.published_at.astimezone(MSK).date() if fragment.published_at else None
        for forecast, text in statements(getattr(fragment, "text", None) or fragment.fragment or "", stems):
            candidates.append((forecast, published or dt.date.min, -rank, text, fragment, published))
    if not candidates:
        return None
    forecast, _, _, text, fragment, published = max(candidates, key=lambda c: c[:3])
    text = _cut(text)
    note = None
    # «прогноз устарел» — только у прогноза банка и только если новость новее материала
    if forecast and news_title and (news_date is None or published is None or news_date > published):
        note = outdated_note(text, news_title)
    return BankView(
        text=text,
        source_id=fragment.id,
        material=fragment.title,
        publisher=fragment.publisher or "Аналитики Альфа-Банка",
        date=published,
        outdated=note is not None,
        outdated_note=note,
    )
