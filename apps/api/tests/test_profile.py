import pytest
from factories import make_company

from api.contract import IndustryPosition
from api.profile import build_profile, format_rub, scale_for
from api.records import CompanyRecord, Flow


def flow(
    cp: str, direction: str, amount: float, payments: int = 1, counterparty: CompanyRecord | None = None
):
    return Flow(cp, direction, amount, payments, counterparty)


def values(profile) -> dict:
    return {f.id: f.value for f in profile.features}


def missing_ids(profile) -> set[str]:
    return {m.id for m in profile.missing}


TRUCKS = make_company(
    id="U_2",
    okved_code="49.41",
    okved_name="Деятельность автомобильного грузового транспорта",
    revenue=5e8,
)
POWER = make_company(
    id="U_4",
    okved_code="35.11",
    okved_name="Производство электроэнергии",
    revenue=16e9,
    group_id="group_4_sb",
)


def test_full_profile():
    profile = build_profile(make_company(), flows=[], group_size=3, group_members=["U_2", "U_9"])
    v = values(profile)

    assert profile.id == "U_1"
    assert profile.display_name == "Компания №1 · торговля оптовая твердым, жидким и газообразным топливом"
    assert v["feat:MAINOKVED_CODE"] == "46.71 Торговля оптовая твердым, жидким и газообразным топливом"
    assert v["feat:sector"] == "оптовая торговля"
    assert v["feat:REVENUE_COMPANY"] == 20e9
    assert profile.feature("feat:REVENUE_COMPANY").display == "20 млрд ₽"
    assert v["feat:scale"] == "крупный бизнес"
    assert v["feat:CL_TYPE"] == "действующий клиент"
    assert v["feat:CL_PRODUCT_LOA_MARK"] is True
    assert v["feat:bank_products"] == ["РКО", "кредиты", "лизинг", "зарплатный проект"]
    assert v["feat:FTS_COUNTRY_NAME"] == ["Китай", "ОАЭ", "Южная Корея"]
    assert v["feat:REGION"] == "Москва"
    assert profile.group.id == "group_1_sb"
    assert profile.group.size == 3
    assert profile.group.members == ["U_2", "U_9"]

    sector = profile.feature("feat:sector")
    assert sector.source == "derived"
    assert sector.derived_from == ["feat:MAINOKVED_CODE"]
    assert profile.feature("feat:REGION").source == "dataset"
    # у признаков id, подпись и происхождение есть всегда
    assert all(f.id.startswith("feat:") and f.label and f.source for f in profile.features)


def test_empty_fields_go_to_missing():
    company = CompanyRecord(id="U_5", okved_code="мусор", fts_flag=True)
    profile = build_profile(company, flows=[])

    assert profile.display_name == "Компания №5"
    assert {
        "feat:REVENUE_COMPANY",
        "feat:scale",
        "feat:sector",
        "feat:REGION",
        "feat:GROUP_ID",
        "feat:FTS_COUNTRY_NAME",
        "feat:bank_products",
        "feat:top_counterparties",
        "feat:AMOUNT_WORKERS_SPARK_GRADATION",
    } <= missing_ids(profile)
    assert profile.group is None
    assert profile.counterparties == []
    assert (
        next(m for m in profile.missing if m.id == "feat:top_counterparties").reason
        == "нет платежей в выгрузке"
    )
    # то, что есть, не в missing
    assert values(profile)["feat:FTS_FLAG"] is True
    assert "feat:FTS_FLAG" not in missing_ids(profile)


def test_no_foreign_trade_is_not_missing():
    profile = build_profile(make_company(fts_flag=False, fts_countries=None), flows=[])
    assert values(profile)["feat:FTS_FLAG"] is False
    assert "feat:FTS_COUNTRY_NAME" not in missing_ids(profile)


def test_no_products_is_known_not_missing():
    flags = dict.fromkeys(
        ["rko", "guarantee", "credit", "leasing", "deposit", "salary_project", "factoring"], False
    )
    profile = build_profile(make_company(**flags), flows=[])
    feature = profile.feature("feat:bank_products")
    assert feature.value == []
    assert feature.display == "продуктами банка не пользуется"


def test_counterparties_shares_roles_and_exclusions():
    flows = [
        flow("U_2", "out", 3e9, 120, TRUCKS),
        flow("U_2", "in", 1e9, 40, TRUCKS),
        flow("U_1", "in", 9e11, 1000),  # самоплатёж
        flow("U_77", "out", 5e8, 10),  # контрагента нет в выгрузке
        flow("U_88", "in", 5e10, 3),  # больше годовой выручки — выброс
        flow("U_4", "in", 2.5e8, 12, POWER),
    ]
    profile = build_profile(make_company(), flows)
    cps = profile.counterparties

    assert [c.id for c in cps] == ["U_2", "U_77", "U_4"]
    trucks, unknown, power = cps
    assert trucks.role == "both"
    assert trucks.intra_group is True  # та же группа, что у компании
    assert power.intra_group is False
    assert trucks.sector == "транспорт и логистика"
    assert trucks.okved == "49.41 Деятельность автомобильного грузового транспорта"
    assert trucks.amount == 4e9
    assert trucks.payments == 160
    assert trucks.share == pytest.approx(4 / 4.75, abs=1e-4)
    assert unknown.role == "supplier"
    assert unknown.in_dataset is False
    assert unknown.sector is None
    assert unknown.display_name == "Компания №77"
    assert power.role == "customer"
    assert sum(c.share for c in cps) == pytest.approx(1, abs=1e-3)

    v = values(profile)
    assert v["feat:payments_turnover"] == 4.75e9
    assert (
        v["feat:top_counterparties"][0]
        == "U_2 · поставщик и покупатель · транспорт и логистика · 84 % оборота · в группе"
    )
    assert v["feat:intra_group_share"] == pytest.approx(4 / 4.75, abs=1e-4)
    # внутригрупповой оборот отделён: в стороны покупателей и поставщиков не входит
    pay = profile.payments
    assert pay.turnover == 4.75e9
    assert pay.intra_group_amount == 4e9
    assert pay.revenue_coverage == pytest.approx(4.75 / 20, abs=1e-4)
    assert (pay.excluded_self_payments, pay.excluded_outliers) == (1, 1)
    assert pay.customers.amount == 2.5e8
    assert pay.customers.coverage == 1.0
    assert [(x.okved, x.sector, x.share) for x in pay.customers.sectors] == [("35", "энергетика", 1.0)]
    assert pay.suppliers.amount == 5e8
    assert pay.suppliers.coverage == 0.0  # единственный поставщик неизвестен
    assert pay.suppliers.sectors == []
    assert v["feat:customer_sectors"] == ["энергетика — 100 %"]
    reasons = {m.id: m.reason for m in profile.missing}
    assert (
        reasons["feat:supplier_sectors"]
        == "отрасль неизвестна ни у одного из 1 контрагентов: их нет в выгрузке"
    )
    assert profile.feature("feat:top_counterparties").derived_from == ["payments", "feat:REVENUE_COMPANY"]
    assert any("самой себе" in n for n in profile.data_notes)
    assert any("контрагентов с суммой больше годовой выручки: 1" in n for n in profile.data_notes)


def test_sides_by_okved_class_and_coverage():
    company = make_company(group_id=None)
    cafe = make_company(id="U_10", okved_code="56.10", group_id=None)
    canteen = make_company(id="U_11", okved_code="56.29", group_id=None)
    hotel = make_company(id="U_12", okved_code="55.10", group_id=None)
    oil = make_company(id="U_13", okved_code="19.20", group_id=None)
    flows = [
        flow("U_10", "in", 3e8, counterparty=cafe),
        flow("U_11", "in", 2e8, counterparty=canteen),
        flow("U_12", "in", 1e8, counterparty=hotel),
        flow("U_14", "in", 4e8),  # покупатель вне выгрузки
        flow("U_13", "out", 6e8, counterparty=oil),
        flow("U_10", "out", 1e8, counterparty=cafe),
    ]
    profile = build_profile(company, flows)
    customers, suppliers = profile.payments.customers, profile.payments.suppliers

    assert customers.amount == 1e9
    assert customers.counterparties == 4
    assert customers.coverage == 0.6
    assert [(x.okved, x.share, x.counterparties) for x in customers.sectors] == [
        ("56", 0.5, 2),
        ("55", 0.1, 1),
    ]
    assert suppliers.amount == 7e8
    assert [x.okved for x in suppliers.sectors] == ["19", "56"]
    assert profile.payments.intra_group_amount == 0
    # 55 и 56 — одна отрасль «гостиницы и общепит» в признаке
    assert values(profile)["feat:customer_sectors"] == ["гостиницы и общепит — 60 %"]
    assert values(profile)["feat:supplier_sectors"] == ["нефть и газ — 86 %", "гостиницы и общепит — 14 %"]
    # тот, кто и платит, и получает, — в обеих сторонах
    assert next(c for c in profile.counterparties if c.id == "U_10").role == "both"


def test_only_incoming_payments():
    profile = build_profile(make_company(group_id=None), [flow("U_14", "in", 1e8)])
    assert profile.payments.suppliers.amount == 0
    missing = {m.id: m.reason for m in profile.missing}
    assert missing["feat:supplier_sectors"] == "нет платежей от внешних контрагентов в выгрузке"
    # поступления есть, но плательщик неизвестен — «нет данных» с причиной, а не пустой список
    assert (
        missing["feat:customer_sectors"]
        == "отрасль неизвестна ни у одного из 1 контрагентов: их нет в выгрузке"
    )
    assert profile.payments.customers.coverage == 0


def test_industry_position():
    position = IndustryPosition(
        okved="45.31.1",
        rank=1,
        total=422,
        okved_class="45",
        class_rank=1,
        class_total=2661,
        percentile=0.9976,
    )
    profile = build_profile(make_company(), flows=[], industry=position)
    feature = profile.feature("feat:industry_rank")
    assert feature.value == "№ 1 из 422"
    assert feature.display == (
        "№ 1 из 422 по выручке среди компаний с ОКВЭД 45.31.1 в данных банка (№ 1 из 2661 в классе 45)"
    )
    assert profile.industry == position
    assert "feat:industry_rank" in missing_ids(build_profile(make_company(), flows=[]))


def test_low_payment_coverage_note():
    profile = build_profile(make_company(revenue=20e9), [flow("U_77", "out", 1e8)])
    assert "платежи в выгрузке — 0,5 % выручки: картина контрагентов неполная" in profile.data_notes
    assert profile.feature("feat:intra_group_share") is None  # внутри группы платежей нет


def test_top_is_limited_to_ten():
    flows = [flow(f"U_{100 + i}", "out", 1e6 * (i + 1)) for i in range(15)]
    profile = build_profile(make_company(), flows)
    assert len(profile.counterparties) == 10
    assert profile.counterparties[0].id == "U_114"


def test_outlier_rule_needs_revenue():
    # без выручки отбрасывать не с чем сравнивать — пара остаётся
    profile = build_profile(make_company(revenue=None), [flow("U_88", "in", 5e10)])
    assert [c.id for c in profile.counterparties] == ["U_88"]


def test_only_self_payments():
    profile = build_profile(make_company(), [flow("U_1", "out", 1e9)])
    assert profile.counterparties == []
    assert "feat:top_counterparties" in missing_ids(profile)
    assert profile.payments is None
    reasons = {m.id: m.reason for m in profile.missing}
    assert reasons["feat:top_counterparties"] == "все платежи — самой себе или выбросы"


def test_scale_by_group_revenue():
    # компания на 5 млрд в группе на 20 млрд — крупный бизнес по выручке группы;
    # своей выручке сегмент не приписываем
    profile = build_profile(make_company(revenue=5e9), flows=[], group_size=3, group_revenue=20e9)
    scale = profile.feature("feat:scale")
    assert scale.value == "крупный бизнес"
    assert scale.display == "крупный бизнес по выручке группы (20 млрд ₽); своя выручка — 5 млрд ₽"
    assert scale.derived_from == ["feat:group_revenue", "feat:REVENUE_COMPANY"]
    assert profile.feature("feat:group_revenue").display == "20 млрд ₽ — 3 компании"
    assert profile.feature("feat:group_revenue_share").value == 0.25
    assert profile.group.revenue == 20e9


def test_scale_without_own_revenue():
    profile = build_profile(make_company(revenue=None), flows=[], group_size=2, group_revenue=30e9)
    assert profile.feature("feat:scale").display.endswith("своей выручки в данных нет")
    assert profile.feature("feat:group_revenue").derived_from == [
        "feat:GROUP_ID"
    ]  # своей выручки нет — не ссылаемся
    assert "feat:group_revenue_share" in missing_ids(profile)


def test_single_company_group_scale_by_own_revenue():
    profile = build_profile(make_company(revenue=5e9), flows=[], group_size=1, group_revenue=5e9)
    assert profile.feature("feat:scale").value == "средний бизнес"
    assert profile.feature("feat:group_revenue") is None


def test_single_company_group():
    profile = build_profile(make_company(), flows=[], group_size=1, group_members=[])
    assert profile.feature("feat:GROUP_ID").display == "компания вне группы"


@pytest.mark.parametrize(
    ("revenue", "scale"),
    [(16e9, "крупный бизнес"), (15e9, "средний бизнес"), (5e8, "малый бизнес"), (1e6, "микробизнес")],
)
def test_scale(revenue, scale):
    assert scale_for(revenue) == scale


def test_format_rub():
    assert format_rub(16461799989.0) == "16,5 млрд ₽"
    assert format_rub(2.5e8) == "250 млн ₽"
    assert format_rub(512) == "512 ₽"
