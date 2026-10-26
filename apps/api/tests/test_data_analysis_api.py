from fastapi.testclient import TestClient
from test_api import FakeRepo

import api.main as main
from api.contract import CompanyProfile, Indicator
from api.data_quality import DataQualityDimension, DataQualityPassport
from api.indirect import IndirectDependencies
from api.main import app, get_repo


def test_company_data_analysis_endpoint_is_read_only_and_accepts_optional_okved(monkeypatch):
    repo = FakeRepo()
    seen = {}
    monkeypatch.setattr(
        main,
        "company_profile",
        lambda _repo, cid: CompanyProfile(id=cid, display_name="Компания", features=[], missing=[]),
    )

    def indicators(company, flows):
        seen["indicator_inputs"] = (company.id, len(flows))
        return [Indicator(code="sample", label="Показатель", value=0.1, text="10 %", formula="x / y")]

    monkeypatch.setattr(main, "company_indicators", indicators)

    def quality(company, flows):
        empty = DataQualityDimension(known_amount=0, total_amount=0, coverage=0, unknown_share=0)
        return DataQualityPassport(
            payments_present=bool(flows),
            external_counterparties=0,
            excluded_self_payments=0,
            excluded_outlier_counterparties=0,
            industry=empty,
            counterparty=empty,
            region=empty,
        )

    monkeypatch.setattr(main, "data_quality", quality)

    def indirect(_repo, cid, okved):
        seen["okved"] = okved
        return IndirectDependencies(company_id=cid, paths=[], intermediaries_checked=0)

    monkeypatch.setattr(main, "indirect_dependencies", indirect)
    app.dependency_overrides[get_repo] = lambda: repo
    try:
        client = TestClient(app)
        response = client.get(
            "/api/companies/U_1/data-analysis", params=[("okved", "56"), ("okved", "46.71")]
        )
        assert response.status_code == 200
        body = response.json()
        assert body["company"]["id"] == "U_1"
        assert body["indicators"][0]["code"] == "sample"
        assert seen["indicator_inputs"] == ("U_1", 1)
        assert body["quality"]["payments_present"] is True
        assert body["indirect"]["company_id"] == "U_1"
        assert seen["okved"] == ["56", "46.71"]
        assert client.get("/api/companies/absent/data-analysis").status_code == 404
    finally:
        app.dependency_overrides.clear()
