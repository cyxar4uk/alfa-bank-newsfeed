import datetime as dt

import pytest

from api import market
from api.market import MemoryMarket, Point, factor_line, gap_to_bank, market_change, market_facts, market_line

TODAY = dt.date(2026, 10, 26)


@pytest.fixture(autouse=True)
def rows():
    old = market.MARKET
    market.MARKET = MemoryMarket(
        [
            Point("usd_rub", dt.date(2026, 10, 18), 83.0),
            Point("usd_rub", dt.date(2026, 10, 25), 80.6),
            Point("key_rate", dt.date(2026, 7, 25), 17.0),
            Point("key_rate", dt.date(2026, 10, 24), 16.5),
        ]
    )
    yield
    market.MARKET = old


def test_line_with_weekly_change_and_source_date():
    assert market_line("usd_rub", TODAY) == "курс доллара 80,6 ₽ (ЦБ РФ на 25.10), за неделю −2,4 ₽"
    assert factor_line("rate", TODAY) == "ключевая ставка 16,5 % (ЦБ РФ на 24.10), за три месяца −0,5 п.п."
    now, before = market_change("usd_rub", 7, TODAY)
    assert (now.value, before.value) == (80.6, 83.0)


def test_no_series_no_numbers():
    assert market_line("brent_usd", TODAY) is None and factor_line("consumer", TODAY) is None
    market.MARKET = MemoryMarket([Point("usd_rub", dt.date(2026, 8, 1), 90.0)])  # старше месяца — не «сейчас»
    assert market_line("usd_rub", TODAY) is None and market_facts(TODAY) == []


def test_bank_forecast_against_market():
    assert gap_to_bank("usd_rub", 87, TODAY) == "банк ждёт 87 ₽ — на 7,9 % выше нынешних 80,6 ₽"
    assert gap_to_bank("brent_usd", 70, TODAY) is None


def test_takeaway_facts_end_with_market_number(monkeypatch):
    from test_takeaway import item

    from api.takeaway import facts

    monkeypatch.setattr(market, "_today", lambda: TODAY)
    found = facts(item(0.6, code="fx", title="Рубль крепнет"), "fx", None)
    assert found[-1].startswith("курс доллара 80,6 ₽")
