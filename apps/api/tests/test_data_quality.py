from factories import make_company

from api.data_quality import data_quality
from api.records import Flow


def test_passport_uses_amount_weighted_denominators_and_exclusions():
    company = make_company(group_id="g", revenue=None)
    known = make_company(id="U_2", group_id=None, okved_code="46.90", region="Москва")
    same_group = make_company(id="U_3", group_id="g")
    flows = [
        Flow("U_2", "out", 60, 1, known),
        Flow("U_404", "out", 40, 1, None),
        Flow("U_3", "out", 100, 1, same_group),
        Flow(company.id, "in", 5, 1, company),
        Flow("U_5", "out", -1, 1, None),
    ]
    passport = data_quality(company, flows)
    assert passport.external_counterparties == 2
    assert passport.industry.total_amount == 100
    assert passport.industry.known_amount == 60
    assert passport.industry.unknown_share == 0.4
    assert passport.counterparty.coverage == 0.6
    assert passport.region.coverage == 0.6
    assert passport.excluded_self_payments == 1


def test_passport_empty_and_all_unknown():
    company = make_company(group_id=None)
    empty = data_quality(company, [])
    assert empty.payments_present is False
    assert empty.industry.total_amount == 0
    assert empty.industry.coverage == 0
    unknown = data_quality(company, [Flow("U_99", "in", 10, 1, None)])
    assert unknown.counterparty.unknown_share == 1
