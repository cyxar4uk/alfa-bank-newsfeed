"""Значимость в карточке согласована с объяснением; дисклеймер в ответах API."""

import pytest
from agent_fakes import (
    GOOD_PLAN,
    NEWS_ID,
    PERSONA,
    FakeCompany,
    FakeLibrary,
    ScriptedTransport,
    good_draft,
    make_event,
    make_llm,
    make_profile,
    reply,
)
from fastapi.testclient import TestClient
from test_agent_loop import make_agent

from api.agent.context import AgentContext
from api.agent.loop import MAX_REVISIONS
from api.agent.ports import Chain, Channel, ExposureFactor, FactorTag
from api.agent.relevance import AGENT_LINK_WEIGHT, combine, formula, terms_for
from api.agent.routes import get_agent
from api.agent.service import AgentService
from api.agent.store import MemoryAgentStore
from api.contract import DISCLAIMER
from api.main import app

SUPPLY_45 = ExposureFactor(
    code="supply_45",
    label="поставщики · автомобили",
    level="medium",
    strength=0.4,
    refs=["feat:supplier_sectors"],
)
RATE = ExposureFactor(
    code="rate", label="ставка", level="high", strength=0.7, refs=["feat:CL_PRODUCT_LOA_MARK"]
)
# новость про утильсбор на грузовики размечена как машиностроение (29): в цепочке — 3,7 % платежей
CHAIN_29 = Chain(
    channels=[
        Channel(
            kind="suppliers",
            factor="supply_29",
            okved="29",
            share=0.037,
            strength=0.037,
            text="производство автомобилей: 3,7 % платежей",
            refs=["feat:supplier_sectors"],
        )
    ]
)


def ctx_for(event, exposure, chain):
    return AgentContext(persona=PERSONA, profile=make_profile(), event=event, exposure=exposure, chain=chain)


def test_link_found_by_agent_raises_score_consistently():
    ctx = ctx_for(make_event(factors=[], okved=["29"]), [SUPPLY_45, RATE], CHAIN_29)
    formal = formula(ctx)
    assert formal.score == pytest.approx(0.04, abs=0.005)
    terms = terms_for(ctx, {"supply_45", "suppliers"})
    score, basis = combine(formal, terms)
    assert score == pytest.approx(0.4 * AGENT_LINK_WEIGHT)
    assert "связь найдена агентом" in basis


def test_tagged_link_uses_tag_strength():
    event = make_event(factors=[FactorTag(code="rate", strength=0.9)])
    ctx = ctx_for(event, [RATE], Chain())
    (term,) = terms_for(ctx, {"rate"})
    assert term.source == "tag" and term.value == pytest.approx(0.63)


def test_formal_score_kept_when_higher():
    ctx = ctx_for(make_event(factors=[FactorTag(code="rate", strength=1.0)]), [RATE], Chain())
    score, basis = combine(formula(ctx), terms_for(ctx, {"supply_45"}))
    assert score == pytest.approx(0.7) and basis == "формальная оценка"


def test_factor_absent_in_company_map_gives_nothing():
    ctx = ctx_for(make_event(factors=[]), [RATE], Chain())
    assert terms_for(ctx, {"commodity_gold"}) == []


def test_insight_score_and_trace_explain_each_other():
    company = FakeCompany(
        exposure=[RATE, ExposureFactor(code="fx", label="курс", level="medium", strength=0.6)], chain=Chain()
    )
    agent, _ = make_agent(
        reply(GOOD_PLAN), *[reply(good_draft()) for _ in range(1 + MAX_REVISIONS)], company=company
    )
    result = agent.run(PERSONA, make_event(factors=[]))
    assert result.insight.relevance.score == pytest.approx(0.35)  # ставка 0,7 × связь агента 0,5
    step = next(s for s in result.trace.steps if s.tool == "relevance")
    assert "0.35" in step.summary and "связь найдена агентом" in step.summary


def test_disclaimer_in_http_responses():
    from agent_fakes import bank

    from api.agent.drafts import AskAnswer

    answer = AskAnswer(on_topic=True, statements=[bank()])
    service = AgentService(
        make_llm(ScriptedTransport(reply(GOOD_PLAN), reply(good_draft()), reply(answer))),
        FakeCompany(),
        FakeLibrary(),
        MemoryAgentStore(),
    )
    app.dependency_overrides[get_agent] = lambda: service
    try:
        client = TestClient(app)
        insight = client.get(f"/api/insights/{NEWS_ID}", params={"persona": PERSONA.id}).json()
        ask = client.post(
            f"/api/insights/{insight['id']}/ask", json={"question": "Что дальше со ставкой?"}
        ).json()
    finally:
        app.dependency_overrides.clear()
    assert insight["disclaimer"] == DISCLAIMER and ask["disclaimer"] == DISCLAIMER
    assert "не являются инвестиционной рекомендацией" in DISCLAIMER
