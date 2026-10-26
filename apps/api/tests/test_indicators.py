from factories import make_company

from api.indicators import company_indicators
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
    found = {i.code: i for i in company_indicators(company, flows)}
    assert (
        found["top_customer_share"].value == 0.6
        and "заметная зависимость" in found["top_customer_share"].text
    )
    assert found["top_supplier_share"].value == 0.75
    assert found["gov_customers_share"].value == 0.6
    assert found["intra_group_share"].value == round(2e8 / 16e8, 4)
    assert found["supplier_sectors"].text.startswith("Внешние платежи поставщикам: оптовая торговля — 75 %")
    assert "fx_sensitivity" not in found  # ВЭД не задаёт валюту платежа и валютную позицию
    assert found["top3_customer_share"].value == 1.0
    assert found["top5_supplier_share"].value == 1.0
    assert found["hhi_customer"].value == 0.52
    assert found["unknown_industry_in_share"].value == 0
    assert found["unknown_counterparty_out_share"].value == 0.25
    assert all(i.formula for i in found.values())


def test_no_flows_no_indicators_and_no_rate_no_fx():
    assert company_indicators(make_company(), []) == []
    importer = make_company(id="U_7", group_id=None, fts_flag=True)
    codes = {
        i.code for i in company_indicators(make_company(group_id=None), [flow("U_7", "out", 1e8, importer)])
    }
    assert "fx_sensitivity" not in codes


def test_region_concentration_keeps_unknowns_in_denominator_and_ved_membership_can_overlap():
    company = make_company(group_id=None)
    a = make_company(id="U_2", group_id=None, region="Москва", fts_flag=True, fts_countries="КИТАЙ, ОАЭ")
    b = make_company(id="U_3", group_id=None, region="Москва", fts_flag=True, fts_countries="КИТАЙ")
    c = make_company(id="U_4", group_id=None, region=None, fts_flag=True, fts_countries="ОАЭ")
    found = {
        i.code: i
        for i in company_indicators(
            company,
            [
                flow(a.id, "in", 30, a),
                flow(b.id, "in", 20, b),
                flow("U_99", "in", 50),
                flow(a.id, "out", 10, a),
                flow(c.id, "out", 10, c),
            ],
        )
    }
    assert found["top_region_share_in"].value == 0.5  # 50 known in Moscow / 100 incl. unknown
    assert found["top_region_share_out"].value == 0.5
    assert found["ved_country_in_share_1"].value == 0.5
    assert found["ved_country_in_share_2"].value == 0.3
    assert "доли пересекаются" in found["ved_country_in_share_1"].text
    assert "не указывает валюту" in found["ved_country_in_share_1"].text
