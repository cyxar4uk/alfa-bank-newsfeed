import datetime as dt

from factories import make_company

from api import market
from api.indicators import company_indicators
from api.market import MemoryMarket, Point
from api.records import Flow


def flow(cp, direction, amount, counterparty=None):
    return Flow(cp, direction, amount, 1, counterparty)


def test_indicators_from_payments(monkeypatch):
    company = make_company(group_id="g")
    gov = make_company(id="U_9", okved_code="84.11", group_id=None, fts_flag=False)
    cafe = make_company(id="U_8", okved_code="56.10", group_id=None, fts_flag=False)
    importer = make_company(id="U_7", okved_code="46.69", group_id=None, fts_flag=True)
    sister = make_company(id="U_6", okved_code="49.41", group_id="g", fts_flag=False)
    flows = [
        flow("U_9", "in", 6e8, gov),
        flow("U_8", "in", 4e8, cafe),
        flow("U_7", "out", 3e8, importer),
        flow("U_99", "out", 1e8),
        flow("U_6", "out", 2e8, sister),
    ]
    old = market.MARKET
    market.MARKET = MemoryMarket([Point("usd_rub", dt.date.today(), 80.0)])
    try:
        found = {i.code: i for i in company_indicators(company, flows)}
    finally:
        market.MARKET = old
    assert (
        found["top_customer_share"].value == 0.6
        and "заметная зависимость" in found["top_customer_share"].text
    )
    assert found["top_supplier_share"].value == 0.75
    assert found["gov_customers_share"].value == 0.6
    assert found["intra_group_share"].value == round(2e8 / 16e8, 4)
    assert found["supplier_sectors"].text.startswith("Внешние платежи поставщикам: оптовая торговля — 75 %")
    fx = found["fx_sensitivity"]
    assert fx.is_estimate and fx.value == 3e8 / 80 and "(оценка)" in fx.text
    assert all(i.formula for i in found.values())


def test_no_flows_no_indicators_and_no_rate_no_fx():
    assert company_indicators(make_company(), []) == []
    importer = make_company(id="U_7", group_id=None, fts_flag=True)
    codes = {
        i.code for i in company_indicators(make_company(group_id=None), [flow("U_7", "out", 1e8, importer)])
    }
    assert "fx_sensitivity" not in codes  # курса нет — не выдумываем
