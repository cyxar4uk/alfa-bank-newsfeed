from factories import make_company

from api.okved import sector_for
from api.personas import DEMO_PERSONAS, make_personas, pick_companies

DEMO = [
    make_company(id="U_8318", okved_code="45.31.1", revenue=35.9e9),
    make_company(id="U_57706", okved_code="46.71", revenue=105.6e9),
    make_company(id="U_34911", okved_code="46.21", revenue=53.9e9, city="г. Ростов-на-Дону"),
    make_company(id="U_258116", okved_code="46.90", revenue=17.4e9),
]


def others():
    codes = ["41.20", "42.11", "45.11", "64.99", "71.12", "47.71", "49.41", "35.11", "62.01"]
    return [
        make_company(id=f"U_{i}", okved_code=code, revenue=100e9 - i * 1e9, client_type="CLIENT")
        for i, code in enumerate(codes)
    ]


def test_demo_personas_come_first():
    personas = make_personas(DEMO + others())
    demo = personas[: len(DEMO_PERSONAS)]
    assert [p.id for p in demo] == [
        "p-u8318-cfo",
        "p-u8318-acc",
        "p-u57706-owner",
        "p-u57706-tre",
        "p-u34911-ceo",
        "p-u34911-tre",
        "p-u258116-ceo",
    ]
    assert demo[0].name == "Финдиректор · Оптовик автозапчастей, Москва"
    assert demo[0].role_label == "Финансовый директор"
    assert demo[0].sector == "автомобили"


def test_personas_cover_sectors_and_roles():
    personas = make_personas(DEMO + others())
    companies = {p.company_id for p in personas}
    assert 6 <= len(companies) <= 8
    assert {"owner", "ceo", "cfo", "chief_accountant", "treasury"} <= {p.role for p in personas}
    for company in companies:
        assert 1 <= sum(p.company_id == company for p in personas) <= 2
    assert len({p.id for p in personas}) == len(personas)
    # добранные компании — отрасли, которых нет у демо-клиентов, по одной на отрасль
    fill = [p for p in personas if p.company_id not in {c.id for c in DEMO}]
    assert [p.sector for p in fill] == [
        "строительство",
        "транспорт и логистика",
        "энергетика",
        "розничная торговля",
    ]
    assert fill[0].name == "Финдиректор · Строительство, Москва"


def test_without_demo_companies_fills_from_data():
    personas = make_personas(others())
    companies = {p.company_id for p in personas}
    assert len(companies) == 8
    assert len({p.sector for p in personas}) == 8


def test_personas_are_deterministic():
    data = DEMO + others()
    assert make_personas(data) == make_personas(list(reversed(data)))


def test_clients_first():
    companies = others()
    companies.append(make_company(id="U_99", okved_code="41.10", revenue=500e9, client_type="PROSPECT"))
    picked = pick_companies(companies)
    # потенциальный клиент с самой большой выручкой уступает действующему из той же отрасли
    assert picked[0].id == "U_0"
    assert "U_99" not in {c.id for c in picked}
    assert sector_for(picked[0].okved_code) == "строительство"
