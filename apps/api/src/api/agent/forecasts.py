"""Самые свежие прогнозы Альфа-Банка по темам — чтобы старый прогноз не выдавался за актуальный.

Банк пересматривает прогнозы: ставка на конец 2026 г. — 13,5 % в материалах 31.07–07.09, 14,0 % с 11.09. Агент
обязан цитировать последний прогноз и показывать дату, а старый — только как «раньше банк ждал…». Здесь —
какой материал по теме самый свежий; новый материал аналитики — новая строка, код не меняется.
"""

import datetime as dt
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Forecast:
    topic: str
    material: str  # src:alfa:<материал> — самый свежий прогноз по теме
    date: dt.date
    pattern: re.Pattern  # о чём утверждение: ставка, курс, инфляция
    query: str  # чем найти в этом материале прогноз по теме
    # прогноз в свежем материале читается (текст, а не таблица с ошибками распознавания) — только тогда
    # старый прогноз по теме считается устаревшим; иначе процитировать новый нечем, и старый берём с датой
    readable: bool = True


FORECASTS = [
    Forecast(
        "rate",
        "src:alfa:keyrate-2026-09",
        dt.date(2026, 9, 11),
        re.compile(r"ставк|снижени\w* ставк|смягчени", re.IGNORECASE),
        "ожидаем сохранения паузы ставка до конца года",
    ),
    Forecast(
        "fx",
        "src:alfa:keyrate-2026-09",
        dt.date(2026, 9, 11),
        re.compile(r"курс\w*|рубл[ья]\b|₽/\$|руб\./\$", re.IGNORECASE),
        "курс конец года руб./$ руб./юань",
        readable=False,  # курс на 11.09 — только в таблице на 2-й странице, распознана с ошибками
    ),
    Forecast(
        "inflation",
        "src:alfa:keyrate-2026-09",
        dt.date(2026, 9, 11),
        re.compile(r"инфляц", re.IGNORECASE),
        "инфляция дек./дек. прогноз",
    ),
]
# какие темы будить по факторам события
TOPICS_BY_FACTOR = {"rate": "rate", "deposit_yield": "rate", "fx": "fx", "inflation": "inflation"}

_FORECAST_WORDS = re.compile(r"прогноз|ожида|ждёт|ждет|ждал|закладыва|ориентир", re.IGNORECASE)
_PAST = re.compile(r"раньше|ранее|прежн|до этого|до пересмотра|вместо|пересмотр|изменил", re.IGNORECASE)


def superseded(text: str, material: str, material_date: dt.date | None) -> Forecast | None:
    """Свежий прогноз, который отменяет прогноз из этого материала, если утверждение — о прогнозе по теме
    и не помечено как прежнее. Иначе None."""
    if material_date is None or not _FORECAST_WORDS.search(text) or _PAST.search(text):
        return None
    for f in FORECASTS:
        if f.readable and material != f.material and material_date < f.date and f.pattern.search(text):
            return f
    return None
