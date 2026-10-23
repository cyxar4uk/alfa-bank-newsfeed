import pytest
from factories import make_company

from api.chain import build_chain, companies, event_classes
from api.records import Flow


def flow(cp, direction, amount, counterparty=None):
    return Flow(cp, direction, amount, 1, counterparty)


NO_GROUP = dict(group_id=None)
# поставщик общепита: своя отрасль — опт (46.90), выручка 5 млрд
SUPPLIER = make_company(okved_code="46.90", revenue=5e9, **NO_GROUP)
CAFE = make_company(id="U_10", okved_code="56.10", region="Москва", **NO_GROUP)
CANTEEN = make_company(id="U_11", okved_code="56.29", region="Казань", **NO_GROUP)
TRUCKS = make_company(id="U_12", okved_code="49.41", **NO_GROUP)
FLOWS = [
    flow("U_10", "in", 3e8, CAFE),
    flow("U_11", "in", 2e8, CANTEEN),
    flow("U_99", "in", 5e8),  # плательщик вне данных банка
    flow("U_12", "out", 4e8, TRUCKS),
]


def by_kind(chain):
    return {(c.kind, c.okved): c for c in chain.channels}


def test_event_in_foreign_industry_reaches_company_through_buyers():
    # событие про общепит: своей отрасли у компании нет, но половина поступлений — от ресторанов
    chain = build_chain(SUPPLIER, FLOWS, group=[], okved=["56"])
    assert [c.kind for c in chain.channels] == ["buyers"]
    buyers = chain.channels[0]
    assert buyers.share == 0.5
    assert buyers.strength == 0.5
    assert buyers.coverage == 0.5
    assert buyers.counterparties == 2
    assert buyers.text == (
        "событие → гостиницы и общепит (56) → ваши покупатели: 2 компании,"
        " 50 % внешних поступлений (500,0 млн ₽) → вы"
    )
    assert [(n.id, n.share, n.region) for n in buyers.nodes] == [
        ("U_10", 0.3, "Москва"),
        ("U_11", 0.2, "Казань"),
    ]
    assert buyers.refs == ["feat:customer_sectors", "exp:demand_56"]
    assert chain.strength_max == 0.5
    assert chain.reason is None


def test_direct_and_suppliers_channels_and_weights():
    chain = build_chain(SUPPLIER, FLOWS, group=[], okved=["46.90", "49"], weights={"46": 0.8, "49": 0.5})
    channels = by_kind(chain)
    assert channels[("direct", "46")].strength == 0.8
    assert channels[("direct", "46")].refs == ["feat:MAINOKVED_CODE", "feat:sector"]
    suppliers = channels[("suppliers", "49")]
    assert suppliers.share == 1.0  # единственный поставщик — перевозчик
    assert suppliers.strength == 0.5
    assert chain.event_okved == ["46", "49"]
    assert chain.strength_max == 0.8
    assert chain.strength_sum == 1.0  # сумма не больше 1
    # каналы — по убыванию силы
    assert [c.strength for c in chain.channels] == sorted((c.strength for c in chain.channels), reverse=True)


def test_intra_group_payments_only_in_group_channel():
    company = make_company(okved_code="45.31.1", revenue=20e9)  # группа group_1_sb
    importer = make_company(id="U_50", okved_code="45.31", revenue=7e9)  # та же группа
    salon = make_company(id="U_51", okved_code="45.11", revenue=3e9)
    outsider = make_company(id="U_60", okved_code="45.31", group_id="group_x")
    flows = [flow("U_50", "out", 8e9, importer), flow("U_60", "out", 2e9, outsider), flow("U_99", "in", 5e9)]
    chain = build_chain(company, flows, group=[importer, salon], okved=["45"])
    channels = by_kind(chain)

    suppliers = channels[("suppliers", "45")]
    assert suppliers.share == 1.0  # из внешних платежей — только U_60; импортёр группы сюда не входит
    assert [n.id for n in suppliers.nodes] == ["U_60"]
    group = channels[("group", "45")]
    assert group.share == 1.0
    assert group.counterparties == 2
    assert [(n.id, n.intra_group, n.amount) for n in group.nodes] == [
        ("U_50", True, 8e9),
        ("U_51", True, None),
    ]
    assert group.notes == ["платежи с ними — 53 % вашего оборота (внутригрупповые)"]
    assert "feat:intra_group_share" in group.refs
    assert channels[("direct", "45")].strength == 1.0


def test_low_coverage_noted():
    chain = build_chain(
        SUPPLIER, [flow("U_10", "in", 1e8, CAFE), flow("U_99", "in", 9e8)], group=[], okved=["56"]
    )
    buyers = chain.channels[0]
    assert buyers.coverage == 0.1
    assert buyers.notes == ["отрасль известна лишь у 10 % внешних поступлений: реальная доля может быть выше"]
    assert "отрасль известна лишь у 10 % внешних поступлений" in chain.gaps


def test_tiny_channels_are_noise():
    flows = [flow("U_10", "in", 1e6, CAFE), flow("U_99", "in", 9.99e8)]
    chain = build_chain(SUPPLIER, flows, group=[], okved=["56"])
    assert chain.channels == []
    assert chain.reason == "контрагенты из отраслей события есть, но дают меньше 1 % оборота стороны"


def test_no_payments_and_no_match():
    chain = build_chain(SUPPLIER, [], group=[], okved=["56"])
    assert chain.channels == []
    assert chain.gaps == ["нет платежей в выгрузке"]  # одна причина на обе стороны
    assert "данных недостаточно" in chain.reason  # не «не относятся»: контрагентов мы не проверили
    assert chain.strength_max == 0 and chain.strength_sum == 0


def test_event_without_okved():
    chain = build_chain(SUPPLIER, FLOWS, group=[], okved=["мусор", ""])
    assert chain.event_okved == []
    assert chain.reason == "у события нет классов ОКВЭД"


def test_payments_far_below_revenue_give_no_side_channels():
    company = make_company(okved_code="46.71", revenue=100e9, **NO_GROUP)
    chain = build_chain(company, [flow("U_10", "in", 1e8, CAFE)], group=[], okved=["56"])
    assert chain.channels == []
    assert any("0,1 % выручки" in g for g in chain.gaps)


def test_event_classes():
    assert event_classes(["56", "56.10", "46.71", " 41.2 ", "мусор", "4"]) == ["56", "46", "41"]


@pytest.mark.parametrize(
    ("n", "text"),
    [(1, "1 компания"), (3, "3 компании"), (11, "11 компаний"), (21, "21 компания"), (469, "469 компаний")],
)
def test_companies_plural(n, text):
    assert companies(n) == text


def test_neighbour_subindustry_is_partial_direct():
    grain = make_company(okved_code="46.21", **NO_GROUP)
    chain = build_chain(grain, [], group=[], okved=["46.71"])
    direct = chain.channels[0]
    assert direct.kind == "direct"
    assert direct.strength == 0.5  # тот же класс 46, но событие про топливо, а компания торгует зерном
    assert direct.text.startswith("событие в соседней отрасли того же класса ОКВЭД 46 (46.71)")
    # событие про весь класс или про свой код — это своя отрасль
    assert build_chain(grain, [], group=[], okved=["46"]).channels[0].strength == 1.0
    assert build_chain(grain, [], group=[], okved=["46.2"]).channels[0].strength == 1.0


def test_weights_by_event_codes_and_bad_values():
    assert build_chain(SUPPLIER, FLOWS, [], ["56.10"], weights={"56.10": 0.2}).channels[0].strength == 0.1
    # NaN и мусор не роняют расчёт — такой вес как будто не задан
    nan = build_chain(SUPPLIER, FLOWS, [], ["56"], weights={"56": float("nan"), "x": 0.5})
    assert nan.channels[0].weight == 1.0
    zero = build_chain(SUPPLIER, FLOWS, [], ["56"], weights={"56": 0})
    assert zero.channels == []
    assert zero.reason == "связь события с этими отраслями нулевая"


def test_group_member_without_revenue_but_with_payments():
    company = make_company(okved_code="46.90", revenue=5e9)
    member = make_company(id="U_70", okved_code="45.31", revenue=None)
    flows = [flow("U_70", "out", 2e9, member), flow("U_99", "out", 2e9)]
    chain = build_chain(company, flows, group=[member], okved=["45"])
    group = chain.channels[0]
    assert group.kind == "group"
    assert group.share == 0.5  # половина оборота — с этой компанией группы, хотя её выручки в данных нет
    assert group.nodes[0].share is None and group.nodes[0].amount == 2e9
    assert "сила — по доле вашего оборота с ними: она больше их доли в выручке группы" in group.notes
