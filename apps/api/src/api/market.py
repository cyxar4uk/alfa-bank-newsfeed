"""Рыночные цифры кодом, а не моделью: официальные ряды из базы (курсы ЦБ, ключевая ставка, нефть).

Ряды кладёт парсер (`ingest.market`) в таблицу `market_series (series, day, value)`. Отсюда:
- `market_now(series)` — последнее значение;
- `market_change(series, days)` — изменение к значению на дату не позже сегодня − days;
- `market_line` — фраза для вывода, карты рисков и фактов агента: «курс доллара 80,6 ₽ (ЦБ РФ на 25.10),
  за неделю −2,4 ₽».
Таблицы или ряда нет — None: числа без источника не показываем.
"""

import datetime as dt
import logging
import threading
import time
from dataclasses import dataclass
from typing import Protocol

from psycopg_pool import ConnectionPool

from api.numbers import fmt_number, fmt_rate

log = logging.getLogger("api.market")


@dataclass(frozen=True)
class Point:
    series: str
    date: dt.date
    value: float
    source: str = "ЦБ РФ"


# ряд (код парсера, ingest.market) → (как назвать, единица, за сколько дней изменение, единица изменения)
SERIES = {
    "fx:USD": ("курс доллара", "₽", 7, "₽"),
    "fx:EUR": ("курс евро", "₽", 7, "₽"),
    "fx:CNY": ("курс юаня", "₽", 7, "₽"),
    "key_rate": ("ключевая ставка", "%", 90, "п.п."),
    "oil:brent": ("нефть Brent", "$/барр.", 7, "$"),
}
SOURCES = {"oil:brent": "EIA"}  # остальные — официальные ряды ЦБ РФ
# фактор карты → ряд, которым он измеряется
FACTOR_SERIES = {
    "fx": "fx:USD",
    "rate": "key_rate",
    "deposit_yield": "key_rate",
    "commodity_oil": "oil:brent",
}
PERIOD_WORDS = {7: "за неделю", 30: "за месяц", 90: "за три месяца"}


class MarketData(Protocol):
    def history(self, series: str, since: dt.date) -> list[Point]: ...


class MemoryMarket:
    """Ряды в памяти — для тестов и без базы."""

    def __init__(self, points: list[Point] | None = None) -> None:
        self.points = points or []

    def history(self, series: str, since: dt.date) -> list[Point]:
        return sorted(
            (p for p in self.points if p.series == series and p.date >= since), key=lambda p: p.date
        )


class PgMarket:
    """Ряды из базы; читаются не чаще раза в 10 минут — вывод ленты зовёт их на каждое событие."""

    TTL = 600

    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool
        self._cache: dict[tuple[str, dt.date], tuple[float, list[Point]]] = {}
        self._lock = threading.Lock()

    def history(self, series: str, since: dt.date) -> list[Point]:
        key = (series, since)
        with self._lock:
            hit = self._cache.get(key)
            if hit and time.monotonic() - hit[0] < self.TTL:
                return hit[1]
        try:
            with self.pool.connection() as conn:
                rows = conn.execute(
                    "SELECT day, value FROM market_series WHERE series = %s AND day >= %s ORDER BY day",
                    (series, since),
                ).fetchall()
        except Exception:  # таблицы ещё нет (парсер не обновлён) — цифр нет, лента работает
            log.debug("рыночный ряд %s не прочитан", series, exc_info=True)
            rows = []
        points = [Point(series, r[0], float(r[1]), SOURCES.get(series, "ЦБ РФ")) for r in rows]
        with self._lock:
            self._cache[key] = (time.monotonic(), points)
        return points


MARKET: MarketData = MemoryMarket()  # api.main подменяет на PgMarket при старте


def _today() -> dt.date:
    return dt.date.today()


def market_now(series: str, today: dt.date | None = None) -> Point | None:
    """Последнее значение ряда за последние 30 дней; старше — не «сейчас»."""
    points = MARKET.history(series, (today or _today()) - dt.timedelta(days=30))
    return points[-1] if points else None


def market_change(series: str, days: int, today: dt.date | None = None) -> tuple[Point, Point] | None:
    """(сейчас, тогда): тогда — последнее значение на дату не позже (сейчас − days)."""
    today = today or _today()
    points = MARKET.history(series, today - dt.timedelta(days=days + 30))
    if not points:
        return None
    now = points[-1]
    before = [p for p in points if p.date <= now.date - dt.timedelta(days=days)]
    return (now, before[-1]) if before else None


def _value(series: str, value: float) -> str:
    _, unit, _, _ = SERIES[series]
    if unit == "%":
        return fmt_rate(value)  # «16,0 %» — ставка всегда с десятыми, как во всём API
    shown = fmt_number(value, 1)
    return f"${shown}/барр." if unit == "$/барр." else f"{shown} {unit}"


def market_line(series: str, today: dt.date | None = None) -> str | None:
    """«курс доллара 80,6 ₽ (ЦБ РФ на 25.10), за неделю −2,4 ₽»; ряда нет — None."""
    if series not in SERIES:
        return None
    now = market_now(series, today)
    if now is None:
        return None
    name, _, days, delta_unit = SERIES[series]
    line = f"{name} {_value(series, now.value)} ({now.source} на {now.date:%d.%m})"
    change = market_change(series, days, today)
    if change is not None:
        delta = change[0].value - change[1].value
        sign = "+" if delta > 0 else "−" if delta < 0 else "±"
        shown = fmt_number(abs(delta), 1)
        line += (
            f", {PERIOD_WORDS.get(days, f'за {days} дн.')} {sign}{'$' if delta_unit == '$' else ''}{shown}"
        )
        line += "" if delta_unit == "$" else f" {delta_unit}"
    return line


def factor_line(code: str, today: dt.date | None = None) -> str | None:
    """Рыночная цифра фактора карты (курс — для «Курса валют», ставка — для долга и размещения)."""
    series = FACTOR_SERIES.get(code)
    return market_line(series, today) if series else None


def gap_to_bank(series: str, bank_value: float, today: dt.date | None = None) -> str | None:
    """«банк ждёт 87 ₽ — на 7,9 % выше нынешних 80,6 ₽»: прогноз банка против последнего значения."""
    now = market_now(series, today)
    if now is None or not now.value or series not in SERIES:
        return None
    gap = bank_value / now.value - 1
    if abs(gap) < 0.005:
        return f"банк ждёт {_value(series, bank_value)} — столько же, сколько сейчас"
    where = "выше" if gap > 0 else "ниже"
    return (
        f"банк ждёт {_value(series, bank_value)} — на {fmt_number(abs(gap) * 100, 1)} % {where}"
        f" нынешних {_value(series, now.value)}"
    )


def market_facts(today: dt.date | None = None) -> list[str]:
    """Все рыночные цифры одной строкой каждая — для фактов агента: числа берутся отсюда, а не из новости."""
    return [line for s in SERIES if (line := market_line(s, today))]
