"""Эндпоинты агента: инсайт с кэшем, 204, своя новость, уточняющий вопрос, трасса, отзывы, стоп-кран."""

import json

import pytest
from agent_fakes import (
    FRAGMENT,
    GOOD_PLAN,
    NEWS_ID,
    PERSONA,
    FakeCompany,
    FakeLibrary,
    ScriptedTransport,
    bank,
    fact,
    good_draft,
    make_event,
    make_llm,
    reply,
)
from fastapi.testclient import TestClient

from api.agent.drafts import AskAnswer, DraftStatement
from api.agent.loop import insight_id
from api.agent.ports import Chain, ExposureFactor
from api.agent.routes import get_agent
from api.agent.service import AgentService
from api.agent.store import MemoryAgentStore
from api.llm import TransportResponse
from api.main import app

INSIGHT_ID = insight_id(NEWS_ID, PERSONA.id)


@pytest.fixture
def setup():
    def make(*responses, company=None, library=None, limit=100.0):
        transport = ScriptedTransport(*responses)
        service = AgentService(
            make_llm(transport, limit=limit),
            company or FakeCompany(),
            library or FakeLibrary(),
            MemoryAgentStore(),
        )
        app.dependency_overrides[get_agent] = lambda: service
        return TestClient(app), service, transport

    yield make
    app.dependency_overrides.clear()


def get_insight(client, event_id=NEWS_ID, persona=PERSONA.id, **params):
    # синхронный режим: карточка в том же ответе; фоновая сборка со статусом — test_agent_jobs.py
    return client.get(f"/api/insights/{event_id}", params={"persona": persona, "wait": "true", **params})


def test_insight_is_built_lazily_and_cached(setup):
    client, service, transport = setup(reply(GOOD_PLAN), reply(good_draft()))
    first = get_insight(client)
    assert first.status_code == 200
    body = first.json()
    assert body["id"] == INSIGHT_ID and body["trace_id"].startswith("tr:")
    assert {s["origin"] for s in body["bank_view"]} == {"bank"}
    second = get_insight(client)
    assert second.json() == body
    assert len(transport.bodies) == 2  # второй раз — без модели


def test_refresh_rebuilds(setup):
    client, _, transport = setup(
        reply(GOOD_PLAN), reply(good_draft()), reply(GOOD_PLAN, 0.2), reply(good_draft())
    )
    get_insight(client)
    assert get_insight(client, refresh="true").status_code == 200
    assert len(transport.bodies) == 4


def test_event_that_does_not_touch_company_is_204(setup):
    company = FakeCompany(
        exposure=[ExposureFactor(code="fx", label="курс", level="medium", refs=["feat:FTS_FLAG"])],
        chain=Chain(),
    )
    client, _, transport = setup(company=company)
    response = get_insight(client)
    assert response.status_code == 204 and response.content == b""
    assert transport.bodies == []  # на нерелевантное событие деньги не тратим


def test_unknown_event_or_persona_is_404(setup):
    client, _, _ = setup()
    assert get_insight(client, event_id="src:news:none").status_code == 404
    assert get_insight(client, persona="p-nobody").status_code == 404


def test_trace_of_insight(setup):
    client, _, _ = setup(reply(GOOD_PLAN), reply(good_draft()))
    trace_id = get_insight(client).json()["trace_id"]
    trace = client.get(f"/api/traces/{trace_id}").json()
    assert trace["insight_id"] == INSIGHT_ID
    kinds = {s["kind"] for s in trace["steps"]}
    assert {"plan", "tool", "llm", "check"} <= kinds
    llm = [s for s in trace["steps"] if s["kind"] == "llm"]
    assert all(s["model"] and s["tokens_in"] is not None and s["cost_rub"] is not None for s in llm)
    assert client.get("/api/traces/tr:none").status_code == 404


def test_analyze_own_news(setup):
    draft = good_draft(what_happened=[fact(refs=["src:news:user-1"])])
    client, _, _ = setup(reply(GOOD_PLAN), reply(draft))
    text = (
        "Совет директоров Банка России сохранил ключевую ставку на уровне 14% годовых. Снижение не обсуждали."
    )
    response = client.post(
        "/api/analyze", params={"wait": "true"}, json={"persona_id": PERSONA.id, "text": text}
    )
    assert response.status_code == 200, response.text
    assert response.json()["sources"][0]["id"] == "src:news:user-1"


def test_analyze_errors(setup):
    client, _, transport = setup()
    assert (
        client.post("/api/analyze", params={"wait": "true"}, json={"persona_id": PERSONA.id}).status_code
        == 422
    )
    short = client.post(
        "/api/analyze", params={"wait": "true"}, json={"persona_id": PERSONA.id, "text": "ставка"}
    )
    assert short.status_code == 422 and "короткий" in short.json()["detail"]
    assert transport.bodies == []


def test_ask_on_topic_answer_has_origin_and_refs(setup):
    answer = AskAnswer(
        on_topic=True,
        statements=[
            bank(),
            DraftStatement(
                text="Значит, дешёвого рефинансирования в этом году не будет.",
                origin="ai",
                refs=["feat:CL_PRODUCT_LOA_MARK"],
                confidence="medium",
            ),
            # выдуманная цитата — в ответ не попадёт
            bank(quote="банк обещает ставку 9% к Новому году", text="Банк ждёт 9% к концу года."),
        ],
    )
    client, _, transport = setup(reply(GOOD_PLAN), reply(good_draft()), reply(answer))
    get_insight(client)
    response = client.post(f"/api/insights/{INSIGHT_ID}/ask", json={"question": "Когда подешевеет кредит?"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["on_topic"] is True
    assert [s["origin"] for s in body["answer"]] == ["bank", "ai"]
    assert all(s["refs"] for s in body["answer"])
    assert FRAGMENT in {s["id"] for s in body["sources"]}
    assert any("убрано" in w for w in body["warnings"])
    # вопрос пользователя попал к модели как данные
    assert "<<<ДАННЫЕ question" in transport.bodies[-1]["messages"][-1]["content"]
    trace = client.get(f"/api/traces/{body['trace_id']}").json()
    assert trace["insight_id"] == INSIGHT_ID


def test_ask_off_topic_is_polite_refusal(setup):
    answer = AskAnswer(on_topic=False, refusal="Я отвечаю только на вопросы о событии и вашей компании.")
    client, _, _ = setup(reply(GOOD_PLAN), reply(good_draft()), reply(answer))
    get_insight(client)
    body = client.post(f"/api/insights/{INSIGHT_ID}/ask", json={"question": "Какая погода в Сочи?"}).json()
    assert body["on_topic"] is False and body["answer"] == []
    assert "только на вопросы" in body["refusal"]


def test_ask_unknown_insight_and_bad_question(setup):
    client, _, _ = setup()
    assert client.post("/api/insights/ins:none/ask", json={"question": "Что дальше?"}).status_code == 404
    assert client.post(f"/api/insights/{INSIGHT_ID}/ask", json={"question": ""}).status_code == 422


def test_feedback_is_saved_and_counted(setup):
    client, _, _ = setup(reply(GOOD_PLAN), reply(good_draft()))
    get_insight(client)
    for useful, reason in [(True, None), (False, "too_general"), (False, "too_general"), (True, None)]:
        r = client.post(
            "/api/feedback",
            json={"insight_id": INSIGHT_ID, "persona_id": PERSONA.id, "useful": useful, "reason": reason},
        )
        assert r.status_code == 201 and r.json()["id"]
    stats = client.get("/api/feedback/stats").json()
    assert stats == {
        "total": 4,
        "useful": 2,
        "not_useful": 2,
        "useful_share": 0.5,
        "reasons": {"too_general": 2},
    }
    assert client.get("/api/feedback/stats", params={"insight_id": "ins:other"}).json()["total"] == 0


def test_feedback_for_unknown_insight(setup):
    client, _, _ = setup()
    r = client.post("/api/feedback", json={"insight_id": "ins:none", "useful": True})
    assert r.status_code == 404


def test_budget_exceeded_is_503_with_clear_message(setup):
    client, _, _ = setup(limit=0.0)
    response = get_insight(client)
    assert response.status_code == 503
    assert "Budget has been exceeded" in response.json()["detail"]


def test_gateway_budget_error_is_503(setup):
    body = '{"error": {"message": "Budget has been exceeded! Current cost: 500.2"}}'
    client, service, _ = setup(TransportResponse(400, json.loads(body), body))
    response = get_insight(client)
    assert response.status_code == 503 and "Budget has been exceeded" in response.json()["detail"]
    # трасса сбоя сохранена
    assert any(t.steps for t in service.store.traces.values())


def test_agent_unavailable_without_llm(setup):
    client, service, _ = setup()
    service.llm = None
    response = get_insight(client)
    assert response.status_code == 503 and "LLM_API_KEY" in response.json()["detail"]


def test_openapi_has_agent_endpoints(setup):
    client, _, _ = setup()
    paths = client.get("/api/openapi.json").json()["paths"]
    for path in (
        "/api/insights/{event_id}",
        "/api/analyze",
        "/api/insights/{insight_id}/ask",
        "/api/traces/{trace_id}",
        "/api/feedback",
    ):
        assert path in paths


def test_events_fixture_is_consistent():
    assert make_event().id == NEWS_ID


def test_cached_only_never_builds(setup):
    client, service, transport = setup(reply(GOOD_PLAN), reply(good_draft()))
    # не собрана — 204 с пометкой, модели не вызывались
    empty = get_insight(client, cached="true")
    assert empty.status_code == 204 and empty.headers["X-Insight"] == "not-built"
    assert transport.bodies == []
    assert service.ready_events([NEWS_ID, "src:news:none"], PERSONA.id) == set()
    built = get_insight(client).json()
    # собрана — та же карточка из кэша, без новых вызовов
    assert get_insight(client, cached="true").json() == built
    assert len(transport.bodies) == 2
    assert service.ready_events([NEWS_ID, "src:news:none"], PERSONA.id) == {NEWS_ID}
    assert service.ready_events([NEWS_ID], "p-nobody") == set()
    assert get_insight(client, persona="p-nobody", cached="true").status_code == 404
