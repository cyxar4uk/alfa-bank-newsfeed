from test_api import FakeRepo

from api.agent.bridges import ServiceCompanyData
from api.agent.claims import Verifier
from api.service import company_profile


def test_calculated_metrics_have_the_same_citable_values_in_profile_and_agent():
    repo = FakeRepo()
    repo.companies["U_1"].group_id = None
    repo.companies["U_2"].group_id = None
    profile = company_profile(repo, "U_1")
    metric = profile.feature("feat:indicator_top3_supplier_share")
    assert metric is not None and metric.value == 1.0
    assert metric.source == "derived" and metric.derived_from == ["payments"]
    assert "100 %" in metric.display and "все внешние" in metric.display
    adapter = ServiceCompanyData(repo, profile_fn=company_profile)
    same = adapter.profile("U_1").feature(metric.id)
    assert same == metric


def test_profile_metrics_are_resolvable_as_claim_evidence():
    from test_agent_checks import make_ctx

    repo = FakeRepo()
    repo.companies["U_1"].group_id = None
    repo.companies["U_2"].group_id = None
    ctx = make_ctx()
    ctx.profile = company_profile(repo, "U_1")
    metric = ctx.profile.feature("feat:indicator_top3_supplier_share")
    claim = Verifier(ctx).claim(metric.display, [metric.id], "data")
    assert claim.support[0].ref == metric.id
    assert claim.unsupported_numbers == []
