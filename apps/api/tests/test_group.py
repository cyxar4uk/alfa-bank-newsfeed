from factories import make_company

from api.group import group_context, group_impact
from api.records import Flow

# топливный оптовик в группе: дорожный строитель, жилищный строитель с кредитом, мелкая розница
COMPANY = make_company(okved_code="46.71", revenue=100e9)
ROADS = make_company(id="U_20", okved_code="42.11", revenue=30e9, credit=False, leasing=False, fts_flag=False)
HOUSING = make_company(id="U_21", okved_code="41.20", revenue=20e9, credit=True, fts_flag=False)
SHOP = make_company(
    id="U_22", okved_code="47.11", revenue=1e9, credit=False, leasing=False, deposit=False, fts_flag=False
)
GROUP = [ROADS, HOUSING, SHOP]
FLOWS = [Flow("U_20", "out", 2e9, 10, ROADS), Flow("U_99", "out", 8e9, 10, None)]


def ctx():
    return group_context(COMPANY, GROUP, FLOWS)


def test_no_group_no_block():
    assert group_context(make_company(group_id=None), [], []) is None
    assert group_context(COMPANY, [COMPANY], []) is None  # в группе только сама компания


def test_event_in_member_industry():
    impact = group_impact(ctx(), factors=[], okved=[("42", 1.0)])
    assert impact.affected_count == 1
    roads = impact.affected[0]
    assert (roads.id, roads.direct, roads.strength) == ("U_20", True, 1.0)
    assert roads.channel.startswith("событие в её отрасли: 42.11")
    # внутригрупповые платежи — отдельно
    assert roads.intra_payments == 2e9
    assert impact.intra_payments == 2e9
    assert impact.intra_share == 0.2
    assert impact.affected_revenue == 30e9
    assert impact.affected_share == round(30 / 51, 4)
    assert impact.companies_total == 4
    assert impact.text.startswith("событие касается 1 компании группы из 3, из них 1 с выручкой от 1 млрд ₽")


def test_event_through_member_factor():
    # ставка касается жилищного строителя со своим кредитом и дорожника — капиталоёмкая отрасль (0,35);
    # показаны по убыванию выручки
    impact = group_impact(ctx(), factors=[("rate", 1.0)], okved=[])
    ids = [m.id for m in impact.affected]
    assert ids == ["U_20", "U_21"]
    assert impact.affected[1].factors[0].code == "rate"
    assert impact.affected[1].strength > impact.affected[0].strength  # у своего кредита связь сильнее
    assert "U_22" not in ids  # у розницы без кредита ставка не задевает


def test_baseline_factors_do_not_make_everyone_affected():
    # налоги и инфляция касаются всех на базовом уровне — это не повод показывать всю группу
    impact = group_impact(ctx(), factors=[("tax_regulation", 1.0), ("inflation", 1.0)], okved=[])
    assert impact.affected_count == 0
    assert impact.text == "событие не касается других компаний группы"


def test_aliases_and_sectors_order():
    impact = group_impact(
        ctx(),
        factors=[("commodity_oil_gas", 1.0)],
        okved=[("41", 1.0), ("42", 1.0)],
        aliases={"commodity_oil_gas": "commodity_oil"},
    )
    assert [m.id for m in impact.affected] == ["U_20", "U_21"]  # одинаковая сила — крупнейшие первыми
    assert "отрасли: строительство" in impact.text


def test_neighbour_subindustry_is_half_strength():
    grain = make_company(id="U_30", okved_code="46.21", revenue=5e9)
    fuel = make_company(id="U_31", okved_code="46.71", revenue=5e9)
    context = group_context(COMPANY, [grain, fuel], FLOWS)
    impact = group_impact(context, factors=[], okved=[("46.71", 1.0)])
    by_id = {m.id: m for m in impact.affected}
    assert by_id["U_31"].strength == 1.0
    assert by_id["U_30"].strength == 0.5  # соседняя подотрасль того же класса


def test_broad_factors_and_baseline_are_ignored():
    impact = group_impact(ctx(), factors=[("inflation", 1.0), ("region", 1.0)], okved=[])
    assert impact.affected_count == 0
