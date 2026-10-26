"""Рыночные ряды из официальных открытых источников: курсы и ключевая ставка Банка России, нефть Brent (EIA).

Таблица `market_series` (код ряда, день, значение) в общей БД; парсер дозагружает недостающие дни каждый круг
(`ingest serve`) и держит историю за `HISTORY_DAYS`. API читает её функциями `series`, `latest`, `change`.

Источники и условия:
- курсы и ключевая ставка — веб-сервисы Банка России (cbr.ru/development): бесплатно, без ключа; воспроизведение
  с указанием источника (cbr.ru/about);
- Brent — U.S. Energy Information Administration: данные правительства США в общественном достоянии
  (eia.gov/about/copyrights_reuse.php), с указанием источника. Публикуется раз в неделю, с задержкой в несколько дней.
Цены на зерно не загружаем: открытого ежедневного ряда с понятными условиями использования не нашли.
"""

import re

# ответы ЦБ и EIA — XML и HTML официальных сайтов; встроенный разборщик (expat ≥ 2.4) не раскрывает внешние
# сущности и ограничивает «взрыв» вложенных
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import httpx
import psycopg

from ingest.news.fetch import USER_AGENT
from ingest.news.normalize import MSK

HISTORY_DAYS = 90
# ключевая ставка: изменение «за три месяца» — точка на дату «сейчас − 90» должна найтись, поэтому 180 дней
KEY_RATE_HISTORY_DAYS = 180
KEY_RATE_LOOKBACK_DAYS = 365  # ставку запрашиваем за год: на длинном плато точки «не позже» нужной даты иначе нет


@dataclass(frozen=True)
class SeriesInfo:
    label: str
    unit: str
    source: str
    source_url: str


CBR = "Банк России"
CBR_URL = "https://www.cbr.ru/currency_base/daily/"
SERIES: dict[str, SeriesInfo] = {
    "usd_rub": SeriesInfo("Курс доллара США", "₽ за $1", CBR, CBR_URL),
    "eur_rub": SeriesInfo("Курс евро", "₽ за €1", CBR, CBR_URL),
    "cny_rub": SeriesInfo("Курс юаня", "₽ за ¥1", CBR, CBR_URL),
    "aed_rub": SeriesInfo("Курс дирхама ОАЭ", "₽ за 1 дирхам", CBR, CBR_URL),
    "inr_rub": SeriesInfo("Курс индийской рупии", "₽ за 1 рупию", CBR, CBR_URL),
    "key_rate": SeriesInfo("Ключевая ставка Банка России", "% годовых", CBR, "https://www.cbr.ru/hd_base/KeyRate/"),
    "brent_usd": SeriesInfo(
        "Нефть Brent",
        "$ за баррель",
        "U.S. Energy Information Administration",
        "https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=RBRTE&f=D",
    ),
}

# внутренние коды валют ЦБ для XML_dynamic
CBR_CODES = {"usd_rub": "R01235", "eur_rub": "R01239", "cny_rub": "R01375", "aed_rub": "R01230", "inr_rub": "R01270"}
CBR_DYNAMIC = "https://www.cbr.ru/scripts/XML_dynamic.asp"
CBR_SOAP = "https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx"
EIA_BRENT = SERIES["brent_usd"].source_url

Point = tuple[date, float]


def _num(text: str) -> float:
    return float(text.replace("\xa0", "").replace(" ", "").replace(",", "."))


def parse_cbr_dynamic(xml: bytes) -> list[Point]:
    """XML_dynamic ЦБ → (дата, ₽ за 1 единицу валюты): номинал учтён («100 рупий = 91 ₽» → 0,91)."""
    root = ET.fromstring(xml)
    out = []
    for rec in root.iter("Record"):
        day = datetime.strptime(rec.get("Date", ""), "%d.%m.%Y").date()
        nominal = _num(rec.findtext("Nominal") or "1") or 1.0
        out.append((day, round(_num(rec.findtext("Value") or "0") / nominal, 6)))
    return out


def parse_cbr_key_rate(xml: bytes) -> list[Point]:
    """Ответ KeyRate веб-сервиса ЦБ → (дата, ставка %). Схема ответа — DataSet, элементы KR/DT и KR/Rate."""
    root = ET.fromstring(xml)
    out = []
    for kr in root.iter("KR"):
        dt, rate = kr.findtext("DT"), kr.findtext("Rate")
        if dt and rate:
            out.append((datetime.fromisoformat(dt).date(), _num(rate)))
    return sorted(out)


_EIA_ROW = re.compile(
    r"<td class='B6'>(?:&nbsp;)*\s*(\d{4})\s+([A-Z][a-z]{2})-\s*(\d{1,2})\s+to[^<]*</td>"
    r"((?:\s*<td class='B3'>[^<]*</td>){5})"
)
_EIA_CELL = re.compile(r"<td class='B3'>([^<]*)</td>")
_MONTHS = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}


def parse_eia_daily(html: str) -> list[Point]:
    """Таблица EIA «неделя — пять рабочих дней»: строка «2026 Oct-19 to Oct-23» и цены с понедельника по пятницу.
    Пустая ячейка — нет торгов или ещё не опубликовано."""
    rows = _EIA_ROW.findall(html)
    if not rows:
        # разметка страницы изменилась: лучше ошибка в отчёте круга, чем тихий ноль точек
        raise ValueError("на странице EIA не нашли таблицу по неделям")
    out = []
    for year, month, day, cells in rows:
        monday = date(int(year), _MONTHS[month], int(day))
        for i, value in enumerate(_EIA_CELL.findall(cells)):
            value = value.strip()
            if value and value not in ("-", "--", "NA"):
                out.append((monday + timedelta(days=i), _num(value)))
    return out


def fetch_cbr_fx(client: httpx.Client, currency: str, start: date, end: date) -> list[Point]:
    params = {
        "date_req1": start.strftime("%d/%m/%Y"),
        "date_req2": end.strftime("%d/%m/%Y"),
        "VAL_NM_RQ": CBR_CODES[currency],
    }
    resp = client.get(CBR_DYNAMIC, params=params)
    resp.raise_for_status()
    return parse_cbr_dynamic(resp.content)


def fetch_cbr_key_rate(client: httpx.Client, start: date, end: date) -> list[Point]:
    body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>
<KeyRate xmlns="http://web.cbr.ru/"><fromDate>{start.isoformat()}</fromDate><ToDate>{end.isoformat()}</ToDate></KeyRate>
</soap:Body></soap:Envelope>"""
    resp = client.post(
        CBR_SOAP,
        content=body.encode("utf-8"),
        headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": "http://web.cbr.ru/KeyRate"},
    )
    resp.raise_for_status()
    return parse_cbr_key_rate(resp.content)


def fetch_eia_brent(client: httpx.Client, start: date, end: date) -> list[Point]:
    resp = client.get(EIA_BRENT)
    resp.raise_for_status()
    return [(d, v) for d, v in parse_eia_daily(resp.text) if start <= d <= end]


Fetcher = Callable[[httpx.Client, date, date], list[Point]]


def fetchers() -> dict[str, Fetcher]:
    out: dict[str, Fetcher] = {code: (lambda c, s, e, code=code: fetch_cbr_fx(c, code, s, e)) for code in CBR_CODES}
    out["key_rate"] = fetch_cbr_key_rate
    out["brent_usd"] = fetch_eia_brent
    return out


@dataclass
class MarketReport:
    loaded: dict[str, int]
    errors: dict[str, str]


def history_days(code: str) -> int:
    """Сколько дней истории храним: ставка — 180 (изменение «за три месяца»), остальное — 90."""
    return KEY_RATE_HISTORY_DAYS if code == "key_rate" else HISTORY_DAYS


def update_market(
    conn: psycopg.Connection,
    client: httpx.Client | None = None,
    today: date | None = None,
    sources: dict[str, Fetcher] | None = None,
) -> MarketReport:
    """Дозагрузить ряды: с последнего сохранённого дня (с перекрытием в неделю — ЦБ и EIA уточняют задним числом)
    до сегодня, не глубже HISTORY_DAYS. Недоступный источник не мешает остальным — попадает в errors.
    Точки старше HISTORY_DAYS удаляются. Вызывать вне открытой транзакции."""
    today = today or datetime.now(MSK).date()
    sources = sources or fetchers()
    report = MarketReport(loaded={}, errors={})
    own = client is None
    client = client or httpx.Client(timeout=20.0, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    try:
        for code, fetch in sources.items():
            floor = today - timedelta(days=history_days(code))
            row = conn.execute("SELECT max(day) FROM market_series WHERE series = %s", (code,)).fetchone()
            start = max(floor, (row[0] - timedelta(days=7)) if row and row[0] else floor)
            # ставка меняется редко: точка на «сейчас − 90» может быть давно, поэтому запрашиваем год, а не окно
            if code == "key_rate":
                start = min(start, today - timedelta(days=KEY_RATE_LOOKBACK_DAYS))
            try:
                points = [(d, v) for d, v in fetch(client, start, today) if floor <= d <= today]
            except Exception as exc:  # noqa: BLE001 — один источник не должен ломать остальные и цикл serve
                report.errors[code] = (str(exc) or type(exc).__name__).splitlines()[0][:200]
                continue
            with conn.transaction():
                with conn.cursor() as cur:
                    info = SERIES.get(code) or SeriesInfo(code, "", "", "")
                    cur.executemany(
                        """
                        INSERT INTO market_series (series, day, value, unit, source, fetched_at)
                        VALUES (%s, %s, %s, %s, %s, now())
                        ON CONFLICT (series, day)
                        DO UPDATE SET value = EXCLUDED.value, unit = EXCLUDED.unit, source = EXCLUDED.source,
                                      fetched_at = now()
                        """,
                        [(code, d, v, info.unit, info.source) for d, v in points],
                    )
            report.loaded[code] = len(points)
        for code in sources:
            conn.execute(
                "DELETE FROM market_series WHERE series = %s AND day < %s",
                (code, today - timedelta(days=history_days(code))),
            )
    finally:
        if own:
            client.close()
    return report


# --- чтение для API ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class MarketPoint:
    code: str
    label: str
    unit: str
    day: date
    value: float
    source: str
    source_url: str


@dataclass(frozen=True)
class MarketChange:
    code: str
    label: str
    unit: str
    now: MarketPoint
    before: MarketPoint
    abs: float
    pct: float | None  # для ставки — изменение в процентных пунктах в abs, pct — относительное


def series(conn: psycopg.Connection, code: str, days: int = HISTORY_DAYS) -> list[Point]:
    """Ряд по возрастанию даты за последние `days` дней от последней точки."""
    rows = conn.execute(
        """
        SELECT day, value FROM market_series
        WHERE series = %s AND day >= (SELECT max(day) FROM market_series WHERE series = %s) - %s
        ORDER BY day
        """,
        (code, code, days),
    ).fetchall()
    return [(r[0], float(r[1])) for r in rows]


def _point(code: str, row) -> MarketPoint | None:
    if not row:
        return None
    info = SERIES.get(code) or SeriesInfo(code, "", "", "")
    return MarketPoint(code, info.label, info.unit, row[0], float(row[1]), info.source, info.source_url)


def latest(conn: psycopg.Connection, code: str, on: date | None = None) -> MarketPoint | None:
    """Последнее значение ряда (не позже `on`, если задано)."""
    row = conn.execute(
        "SELECT day, value FROM market_series WHERE series = %s AND (%s::date IS NULL OR day <= %s::date)"
        " ORDER BY day DESC LIMIT 1",
        (code, on, on),
    ).fetchone()
    return _point(code, row)


def change(conn: psycopg.Connection, code: str, days: int = 7) -> MarketChange | None:
    """Изменение ряда за `days` дней: последняя точка против последней точки не позже (последняя − days)."""
    now = latest(conn, code)
    if now is None:
        return None
    before = latest(conn, code, now.day - timedelta(days=days))
    if before is None:
        return None
    diff = round(now.value - before.value, 6)
    pct = round(diff / before.value * 100, 2) if before.value else None
    return MarketChange(code, now.label, now.unit, now, before, diff, pct)
