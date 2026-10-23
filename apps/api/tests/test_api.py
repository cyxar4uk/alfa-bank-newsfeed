import pytest
from factories import make_company
from fastapi.testclient import TestClient

from api.contract import ImportedFile
from api.main import app, get_repo
from api.records import Flow


class FakeRepo:
    def __init__(self):
        self.companies = {
            "U_1": make_company(),
            "U_2": make_company(id="U_2", okved_code="49.41", okved_name="Грузоперевозки", revenue=5e8),
            "U_4": make_company(
                id="U_4", okved_code="35.11", okved_name="Производство электроэнергии", revenue=16e9
            ),
        }

    def get_company(self, company_id):
        return self.companies.get(company_id)

    def list_companies(self, large, limit, offset):
        items = sorted(self.companies.values(), key=lambda c: -(c.revenue or 0))
        if large:
            items = [c for c in items if (c.revenue or 0) > 15e9]
        return items[offset : offset + limit]

    def group(self, group_id, exclude, limit):
        return 2, ["U_2"]

    def flows(self, company_id):
        return [Flow("U_2", "out", 1e9, 5, self.companies["U_2"])] if company_id == "U_1" else []

    def industry(self, company):
        return None

    def imported_files(self):
        return [
            ImportedFile(
                file="x.csv", rows_read=1, rows_loaded=1, rows_skipped=0, loaded_at="2026-10-23T00:00:00Z"
            )
        ]


@pytest.fixture
def client():
    app.dependency_overrides[get_repo] = FakeRepo
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["db"] == "ok"


def test_company_profile(client):
    response = client.get("/api/companies/U_1")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "U_1"
    assert body["group"] == {"id": "group_1_sb", "size": 2, "members": ["U_2"]}
    assert body["counterparties"][0]["sector"] == "транспорт и логистика"
    assert {f["id"] for f in body["features"]} >= {
        "feat:sector",
        "feat:REVENUE_COMPANY",
        "feat:top_counterparties",
    }


def test_company_not_found(client):
    assert client.get("/api/companies/U_404").status_code == 404


def test_large_companies(client):
    body = client.get("/api/companies", params={"large": "true"}).json()
    assert [c["id"] for c in body] == ["U_1", "U_4"]
    assert body[0]["sector"] == "оптовая торговля"


def test_personas(client):
    body = client.get("/api/personas").json()
    assert {p["company_id"] for p in body} == {"U_1", "U_4"}
    assert all(p["role_label"] and p["company_name"] for p in body)


def test_openapi(client):
    assert client.get("/api/openapi.json").status_code == 200
