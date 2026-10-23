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

    def group_records(self, group_id, exclude):
        return [c for c in self.companies.values() if c.group_id == group_id and c.id != exclude]

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


def test_exposure(client):
    response = client.get("/api/companies/U_1/exposure")
    assert response.status_code == 200
    body = response.json()
    assert body["company_id"] == "U_1"
    assert body["catalog_version"]
    factors = {f["code"]: f for f in body["factors"]}
    assert factors["rate"]["level"] == "high"
    assert factors["rate"]["id"] == "exp:rate"
    assert factors["rate"]["evidence"][0]["ref"] == "feat:CL_PRODUCT_LOA_MARK"
    assert client.get("/api/companies/U_404/exposure").status_code == 404


def test_chain(client):
    response = client.get("/api/companies/U_1/chain", params={"okved": ["49", "35"]})
    assert response.status_code == 200
    body = response.json()
    assert body["event_okved"] == ["49", "35"]
    # перевозчик U_2 — из той же группы: платежи ему внутригрупповые, канал — группа, а не поставщики
    # весь оборот U_1 — с U_2 из своей группы, поэтому канал группы по 49 сильнее, чем по 35 (энергетик U_4)
    assert [(c["kind"], c["okved"]) for c in body["channels"]] == [("group", "49"), ("group", "35")]
    assert body["channels"][0]["nodes"][0]["id"] == "U_2"
    assert client.get("/api/companies/U_1/chain", params={"okved": "49,35"}).json()["event_okved"] == [
        "49",
        "35",
    ]
    assert client.get("/api/companies/U_1/chain").status_code == 422  # без okved
    assert client.get("/api/companies/U_404/chain", params={"okved": "49"}).status_code == 404


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
