from fastapi.testclient import TestClient
from test_api import FakeRepo

from api.agent.adapters import ProfileCompanyData
from api.main import app, get_repo


def test_agent_finds_every_persona_listed_by_api():
    # агент и /api/personas должны видеть одних и тех же пользователей, иначе инсайт отвечает 404
    repo = FakeRepo()
    app.dependency_overrides[get_repo] = lambda: repo
    try:
        listed = TestClient(app).get("/api/personas").json()
    finally:
        app.dependency_overrides.clear()
    assert listed
    data = ProfileCompanyData(repo)
    for persona in listed:
        found = data.persona(persona["id"])
        assert found is not None and found.company_id == persona["company_id"]
