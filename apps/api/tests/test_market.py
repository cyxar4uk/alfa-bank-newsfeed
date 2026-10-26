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
            Point("fx:USD", dt.date(2026, 10, 18), 83.0),
            Point("fx:USD", dt.date(2026, 10, 25), 80.6),
            Point("key_rate", dt.date(2026, 7, 25), 17.0),
            Point("key_rate", dt.date(2026, 10, 24), 16.5),
        ]
    )
    yield
    market.MARKET = old


def test_line_with_weekly_change_and_source_date():
    assert market_line("fx:USD", TODAY) == "курс доллара 80,6 ₽ (ЦБ РФ на 25.10), за неделю −2,4 ₽"
    assert factor_line("rate", TODAY) == "ключевая ставка 16,5 % (ЦБ РФ на 24.10), за три месяца −0,5 п.п."
    now, before = market_change("fx:USD", 7, TODAY)
    assert (now.value, before.value) == (80.6, 83.0)


def test_no_series_no_numbers():
    assert market_line("oil:brent", TODAY) is None and factor_line("consumer", TODAY) is None
    market.MARKET = MemoryMarket([Point("fx:USD", dt.date(2026, 8, 1), 90.0)])  # старше месяца — не «сейчас»
    assert market_line("fx:USD", TODAY) is None and market_facts(TODAY) == []


def test_bank_forecast_against_market():
    assert gap_to_bank("fx:USD", 87, TODAY) == "банк ждёт 87 ₽ — на 7,9 % выше нынешних 80,6 ₽"
    assert gap_to_bank("oil:brent", 70, TODAY) is None


def test_takeaway_facts_do_not_carry_market_number(monkeypatch):
    from test_takeaway import item

    from api.takeaway import facts

    monkeypatch.setattr(market, "_today", lambda: TODAY)
    # рыночная строка — отдельно (карта рисков, факты агента), в «Данные компании» вывода она не попадает
    assert not any(
        "курс доллара" in f for f in facts(item(0.6, code="fx", title="Рубль крепнет"), "fx", None)
    )


def test_zero_change_rate_in_points_and_changes_are_not_forecasts():
    market.MARKET = MemoryMarket(
        [Point("fx:USD", dt.date(2026, 10, 18), 80.63), Point("fx:USD", dt.date(2026, 10, 25), 80.6)]
    )
    assert market_line("fx:USD", TODAY).endswith("за неделю без изменений")
    assert gap_to_bank("fx:USD", 5, TODAY) is None  # «подорожает на 5 руб.» — не уровень курса
    market.MARKET = MemoryMarket([Point("key_rate", dt.date(2026, 10, 24), 16.5)])
    assert gap_to_bank("key_rate", 14, TODAY) == "банк ждёт 14,0 % — на 2,5 п.п. ниже нынешних"
