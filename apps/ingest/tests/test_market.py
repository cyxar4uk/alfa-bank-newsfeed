"""Рыночные ряды: разбор ответов ЦБ и EIA, дозагрузка в БД, чтение для API."""

import os
from datetime import date, timedelta

import httpx
import pytest

from ingest import market

DYNAMIC = """<?xml version="1.0" encoding="windows-1251"?><ValCurs ID="R01270" DateRange1="20.10.2026"
DateRange2="21.10.2026" name="Foreign Currency Market Dynamic">
<Record Date="20.10.2026" Id="R01270"><Nominal>100</Nominal>
<Value>91,1234</Value></Record><Record Date="21.10.2026" Id="R01270"><Nominal>100</Nominal><Value>90,5</Value></Record>
</ValCurs>""".encode("cp1251")

KEY_RATE = b"""<?xml version="1.0" encoding="utf-8"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
<soap:Body><KeyRateResponse xmlns="http://web.cbr.ru/"><KeyRateResult><diffgr:diffgram
xmlns:diffgr="urn:schemas-microsoft-com:xml-diffgram-v1"><KeyRate xmlns=""><KR><DT>2026-10-24T00:00:00+03:00</DT>
<Rate>14.00</Rate></KR><KR><DT>2026-10-23T00:00:00+03:00</DT><Rate>14.50</Rate></KR></KeyRate></diffgr:diffgram>
</KeyRateResult></KeyRateResponse></soap:Body></soap:Envelope>"""

EIA = """<tr> <td class='B6'>&nbsp;&nbsp;2026 Oct-19 to Oct-23</td> <td class='B3'>118.82</td>
<td class='B3'>115.22</td>
<td class='B3'></td> <td class='B3'></td> <td class='B3'></td> </tr>
<tr> <td class='B6'>&nbsp;&nbsp;2025 Dec-29 to Jan- 2</td> <td class='B3'>60.1</td> <td class='B3'>61</td>
<td class='B3'>NA</td> <td class='B3'>62.5</td> <td class='B3'>63</td> </tr>"""


def test_cbr_rate_per_one_unit():
    assert market.parse_cbr_dynamic(DYNAMIC) == [(date(2026, 10, 20), 0.911234), (date(2026, 10, 21), 0.905)]


def test_cbr_key_rate_sorted():
    assert market.parse_cbr_key_rate(KEY_RATE) == [(date(2026, 10, 23), 14.5), (date(2026, 10, 24), 14.0)]


def test_eia_week_rows_and_year_boundary():
    points = market.parse_eia_daily(EIA)
    assert points[:2] == [(date(2026, 10, 19), 118.82), (date(2026, 10, 20), 115.22)]
    assert (date(2026, 1, 1), 62.5) in points and (date(2025, 12, 31), 0) not in points
    assert len(points) == 6  # пустые и NA — нет данных


def test_key_rate_request_is_soap():
    seen = {}

    def handler(request):
        seen["action"] = request.headers["SOAPAction"]
        seen["body"] = request.content.decode()
        return httpx.Response(200, content=KEY_RATE)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert market.fetch_cbr_key_rate(client, date(2026, 10, 1), date(2026, 10, 24))[-1] == (date(2026, 10, 24), 14.0)
    assert seen["action"] == "http://web.cbr.ru/KeyRate" and "<fromDate>2026-10-01</fromDate>" in seen["body"]


URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
def conn():
    if not URL:
        pytest.skip("TEST_DATABASE_URL не задан")
    import psycopg

    from ingest.db.schema import ensure_schema

    with psycopg.connect(URL, autocommit=True) as c:
        ensure_schema(c)
        c.execute("TRUNCATE market_series")
        yield c


def test_update_and_read(conn):
    today = date(2026, 10, 26)
    calls = []

    def usd(client, start, end):
        calls.append(start)
        return [
            (date(2026, 10, 16), 80.0),
            (date(2026, 10, 23), 81.1),
            (date(2026, 10, 24), 80.5),
            (date(2026, 7, 1), 1.0),
        ]

    def broken(client, start, end):
        raise httpx.ConnectError("нет сети")

    report = market.update_market(conn, client=object(), today=today, sources={"usd_rub": usd, "brent_usd": broken})
    assert report.loaded == {"usd_rub": 3} and "нет сети" in report.errors["brent_usd"]  # старше 90 дней — не берём
    assert calls == [date(2026, 7, 28)]
    market.update_market(conn, client=object(), today=today, sources={"usd_rub": usd})
    assert calls[-1] == date(2026, 10, 17)  # дозагрузка с перекрытием в неделю от последнего дня

    assert market.series(conn, "usd_rub") == [
        (date(2026, 10, 16), 80.0),
        (date(2026, 10, 23), 81.1),
        (date(2026, 10, 24), 80.5),
    ]
    last = market.latest(conn, "usd_rub")
    assert (last.day, last.value, last.unit, last.source) == (date(2026, 10, 24), 80.5, "₽ за $1", "Банк России")
    moved = market.change(conn, "usd_rub", days=7)
    assert (moved.before.day, moved.abs, moved.pct) == (date(2026, 10, 16), 0.5, 0.62)
    assert market.change(conn, "brent_usd") is None and market.latest(conn, "нет") is None


def test_eia_page_without_table_is_an_error_not_zero_points():
    with pytest.raises(ValueError):
        market.parse_eia_daily("<html>изменилась разметка</html>")


def test_key_rate_lookback_covers_a_long_plateau(conn):
    # ставка не менялась полгода: точка «не позже сейчас − 90» должна найтись в запросе ЦБ
    today = date(2026, 10, 26)
    asked = {}

    def key_rate(client, start, end):
        asked["start"] = start
        return [(date(2026, 6, 1), 14.0)]  # решение полгода назад: внутри окна хранения, но старше 90 дней

    market.update_market(conn, client=object(), today=today, sources={"key_rate": key_rate})
    assert asked["start"] <= date(2026, 10, 26) - timedelta(days=90)
    assert market.change(conn, "key_rate", days=90) is None  # точка только одна — изменения нет, но и ошибки нет
    now = market.latest(conn, "key_rate")
    assert now.value == 14.0 and now.unit == "% годовых"
