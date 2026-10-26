import math

from factories import make_company

from api.indirect import LIMITATION, indirect_dependencies
from api.records import Flow


class Repo:
    def __init__(self, companies, flows):
        self.companies = companies
        self.flow_map = flows
        self.reads = []

    def get_company(self, company_id):
        return self.companies.get(company_id)

    def flows(self, company_id):
        self.reads.append(company_id)
        return self.flow_map.get(company_id, [])


def test_two_hop_is_bounded_and_excludes_cycles_and_group():
    root = make_company(id="U_1", group_id="root")
    middle = [make_company(id=f"U_{i}", group_id=None) for i in range(2, 9)]
    target = make_company(id="U_20", group_id=None, okved_code="46.90")
    companies = {c.id: c for c in [root, *middle, target]}
    flows = {root.id: [Flow(m.id, "out", 10 - i, 1, m) for i, m in enumerate(middle)]}
    flows.update(
        {m.id: [Flow(root.id, "in", 8, 1, root), Flow(target.id, "out", 4, 1, target)] for m in middle}
    )
    repo = Repo(companies, flows)
    result = indirect_dependencies(repo, root.id)
    assert result is not None
    assert result.intermediaries_checked == 5
    assert len(set(repo.reads[1:])) == 5
    assert len(repo.reads) == 6  # исходный узел + максимум пять уникальных вторых чтений
    assert all(path.counterparty_id != root.id for path in result.paths)
    path = result.paths[0]
    assert path.first_amount > 0 and path.second_amount == 4
    assert path.direction and path.industry
    assert path.conditional_link_index == round(path.first_share * path.second_share, 6)
    assert "не доказывает" in path.limitation
    assert path.limitation == LIMITATION


def test_missing_company_and_missing_second_hop():
    assert indirect_dependencies(Repo({}, {}), "absent") is None
    root = make_company(id="U_1", group_id=None)
    middle = make_company(id="U_2", group_id=None)
    repo = Repo({root.id: root, middle.id: middle}, {root.id: [Flow(middle.id, "out", 1, 1, middle)]})
    result = indirect_dependencies(repo, root.id)
    assert result and result.paths == []
    assert repo.reads == [root.id, middle.id]


def test_top_five_are_combined_across_incoming_and_outgoing_and_filter_is_optional():
    root = make_company(id="U_1", group_id=None)
    peers = [make_company(id=f"U_{i}", group_id=None) for i in range(2, 9)]
    target = make_company(id="U_30", group_id=None, okved_code="56.10")
    flows = {root.id: [Flow(p.id, "in" if i % 2 else "out", 10 - i, 1, p) for i, p in enumerate(peers)]}
    flows.update({p.id: [Flow(target.id, "out", 2, 1, target)] for p in peers})
    repo = Repo({c.id: c for c in [root, *peers, target]}, flows)
    result = indirect_dependencies(repo, root.id, okved=["56"])
    assert result and result.intermediaries_checked == 5
    assert len(repo.reads) == 6
    assert 0 < len(result.paths) <= 5
    assert all(path.industry for path in result.paths)
    assert indirect_dependencies(repo, root.id, okved=["99"]).paths == []


def test_separate_in_and_out_paths_exclude_cycle_from_numerator_and_use_side_denominators():
    root = make_company(id="U_1", group_id=None)
    middle = make_company(id="U_2", group_id=None)
    payer = make_company(id="U_3", group_id=None, okved_code="56.10")
    supplier = make_company(id="U_4", group_id=None, okved_code="46.90")
    unknown = make_company(id="U_5", group_id=None, okved_code=None)
    repo = Repo(
        {c.id: c for c in [root, middle, payer, supplier, unknown]},
        {
            root.id: [
                Flow(middle.id, "in", 100, 1, middle),
                Flow(supplier.id, "in", 100, 1, supplier),
                Flow(middle.id, "out", 50, 1, middle),
                Flow(unknown.id, "out", 50, 1, unknown),
            ],
            middle.id: [
                Flow(root.id, "out", 20, 1, root),  # обратный цикл остаётся в outgoing denominator
                Flow(payer.id, "in", 80, 1, payer),
                Flow(supplier.id, "out", 40, 1, supplier),
                Flow(unknown.id, "out", 40, 1, unknown),
            ],
        },
    )
    result = indirect_dependencies(repo, root.id)
    assert result
    in_path = next(p for p in result.paths if p.direction.startswith("поступления"))
    out_path = next(p for p in result.paths if p.direction.startswith("платежи"))
    assert in_path.first_amount == 100 and in_path.first_share == 0.5
    assert in_path.second_amount == 80 and in_path.second_share == 1
    assert out_path.first_amount == 50 and out_path.first_share == 0.5
    assert out_path.second_amount == 40 and out_path.second_share == 0.4  # denominator 20+40+40
    assert out_path.coverage == 0.6  # цикл в знаменателе тоже имеет известную отрасль


def test_path_cap_and_non_finite_amounts_are_ignored():
    root = make_company(id="U_1", group_id=None)
    middle = make_company(id="U_2", group_id=None)
    targets = [make_company(id=f"U_{i}", group_id=None, okved_code="56.10") for i in range(3, 23)]
    root_flows = [Flow(middle.id, "out", 100, 1, middle), Flow(middle.id, "out", math.nan, 1, middle)]
    second_flows = [Flow(t.id, "out", 10, 1, t) for t in targets]
    second_flows.extend([Flow("U_BAD", "out", math.inf, 1, None), Flow("U_BAD2", "out", math.nan, 1, None)])
    repo = Repo({c.id: c for c in [root, middle, *targets]}, {root.id: root_flows, middle.id: second_flows})
    result = indirect_dependencies(repo, root.id)
    assert result and len(result.paths) == 10
    assert result.intermediaries_checked == 1
    assert all(
        math.isfinite(p.first_amount + p.second_amount + p.conditional_link_index) for p in result.paths
    )
