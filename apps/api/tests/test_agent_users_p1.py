"""Замечания «живых пользователей» 25.10 (P1): рубли по сценариям, маржа, уровень как в ленте, язык, чат."""

from agent_fakes import GOOD_PLAN, PERSONA, FactorTag, good_draft, make_event, reply
from test_agent_checks import make_ctx
from test_agent_loop import make_agent

from api.agent import scenarios
from api.agent.drafts import DraftStatement, to_statement
from api.agent.prompts import ASK_SYSTEM, DRAFT_SYSTEM

# --- рубли: сценарии на условных числах и на числах пользователя -------------------------------------


def test_rate_scenario_per_billion_and_on_user_debt():
    unit = scenarios.rate().text
    assert "1 млрд ₽" in unit and "140 млн ₽" in unit and "120 млн ₽" in unit and "20 млн ₽" in unit
    own = scenarios.rate(2.5e9).text
    assert "ваши 2,5 млрд ₽" in own and "350 млн ₽" in own and "50 млн ₽" in own


def test_fx_scenario_from_news_rate_to_bank_forecast():
    text = scenarios.fx(80.6, "export").text
    assert "80,6" in text and "87" in text and "7,9 %" in text and "выручка от экспорта вырастет" in text
    assert "7,9 млн ₽" in text  # на каждые 100 млн ₽
    assert "23,8 млн ₽" in scenarios.fx(80.6, "import", 3e8).text
    assert scenarios.fx_now("Курс доллара опустился ниже 81 рубля впервые с августа") == 81.0


def test_oil_scenario_and_reseller_margin():
    text = scenarios.oil().text
    assert "$72" in text and "$85 — на 18,1 млн ₽" in text and "$100 — на 38,9 млн ₽" in text
    assert "маржа" in text
    assert "маржа" not in scenarios.oil(reseller=False).text


def test_scenarios_for_rate_event_need_verified_bank_forecast():
    ctx = make_ctx()
    ctx.page_texts[scenarios.RATE_PAGE] = ""
    assert scenarios.for_context(ctx) == []  # прогноз банка не сверен — 12 % не из источника
    ctx.page_texts[scenarios.RATE_PAGE] = "ставка 14,0% до конца года, 12,0% на конец 2027"
    found = scenarios.for_context(ctx, scenarios.Inputs(debt=5e8))
    assert [f[0] for f in found] == ["est:rate_scenario"] and "500 млн ₽" in found[0][1].text


def test_oil_scenario_for_fuel_trader():
    from api.agent.ports import ExposureFactor

    event = make_event(factors=[FactorTag(code="commodity_oil", strength=0.9)])
    event.source.title = "Бензин на АЗС может подорожать"
    ctx = make_ctx(
        event=event,
        exposure=[ExposureFactor(code="commodity_oil", label="Сырьё: нефть, газ и топливо", level="high")],
    )
    ctx.profile = ctx.profile.model_copy(update={"display_name": "Торговля оптовая топливом"})
    (est_id, statement, place, _) = scenarios.for_context(ctx)[0]
    assert est_id == "est:oil_scenario" and place == "risks" and "маржа" in statement.text


def test_scenarios_endpoint_recalculates_on_user_numbers():
    from agent_fakes import FakeCompany, FakeLibrary, ScriptedTransport, make_llm
    from fastapi.testclient import TestClient
    from test_agent_api import INSIGHT_ID, get_insight, setup  # noqa: F401

    from api.agent.routes import get_agent
    from api.agent.service import AgentService
    from api.agent.store import MemoryAgentStore
    from api.main import app

    service = AgentService(
        make_llm(ScriptedTransport(reply(GOOD_PLAN), reply(good_draft()))),
        FakeCompany(),
        FakeLibrary(),
        MemoryAgentStore(),
    )
    app.dependency_overrides[get_agent] = lambda: service
    try:
        client = TestClient(app)
        get_insight(client)
        body = client.post(f"/api/insights/{INSIGHT_ID}/scenarios", json={"debt_rub": 2.5e9}).json()
    finally:
        app.dependency_overrides.clear()
    texts = [s["text"] for s in body["scenarios"]]
    assert any("ваши 2,5 млрд ₽" in t and "350 млн ₽" in t for t in texts)


# --- уровень как в ленте ---------------------------------------------------------------------------------


def test_card_level_follows_feed(monkeypatch):
    import api.agent.loop as loop

    monkeypatch.setattr(loop, "feed_level", lambda persona_id, event_id: "watch")
    agent, transport = make_agent(reply(GOOD_PLAN), reply(good_draft()))
    insight = agent.run(PERSONA, make_event()).insight
    assert insight.verdict.level == "watch" and insight.verdict.headline.startswith("Стоит следить")
    assert "УРОВЕНЬ В ЛЕНТЕ: следить" in transport.bodies[1]["messages"][-1]["content"]


def test_card_level_is_own_without_feed(monkeypatch):
    import api.agent.loop as loop

    monkeypatch.setattr(loop, "feed_level", lambda persona_id, event_id: None)
    agent, _ = make_agent(reply(GOOD_PLAN), reply(good_draft()))
    assert agent.run(PERSONA, make_event()).insight.verdict.level == "act"


# --- язык, гипотезы, маржа, чат --------------------------------------------------------------------------


def test_hypothesis_reads_as_possible():
    s = DraftStatement(
        text="Рестораны сократят закупки.",
        origin="hypothesis",
        refs=[],
        confirm="если до 31.12 спрос упадёт на 10 %",
    )
    assert to_statement(s).text == "Возможно, рестораны сократят закупки."


def test_prompts_carry_the_rules():
    assert "маржу" in DRAFT_SYSTEM and "не ФОТ" in DRAFT_SYSTEM and "Возможно" in DRAFT_SYSTEM
    assert "По данным банка" in ASK_SYSTEM


def test_reseller_is_told_about_margin():
    ctx = make_ctx()
    ctx.profile = ctx.profile.model_copy(update={"display_name": "Торговля оптовая топливом"})
    assert "перепродавец" in ctx.render_event()


def test_review_cases_fx_and_hypothesis_and_level():
    from api.agent.loop import FALLBACK_HEADLINES, _with_level
    from api.contract import Action, Verdict

    assert scenarios.fx_now("Евро подорожал до 95 рублей") is None
    assert scenarios.fx_now("Бензин подорожал до 65,3 руб. за литр, доллар стабилен") is None
    assert scenarios.fx_now("112 100 рублей, курс доллара") is None
    assert scenarios.fx(95, "export").text.count("−8,4 %") == 1
    names = DraftStatement(
        text="ЦБ снизит ставку в декабре.", origin="hypothesis", refs=[], confirm="если до 19.12"
    )
    assert to_statement(names).text == "Возможно, ЦБ снизит ставку в декабре."
    # запасной заголовок не противоречит новому уровню, у «важно» есть шаги
    calm = Verdict(level="info", headline=FALLBACK_HEADLINES["info"], why="Почти не влияет.")
    up = _with_level(calm, "act", [Action(text="Проверьте долг", kind="question", owner="финансовой службе")])
    assert up.headline == FALLBACK_HEADLINES["act"] and up.steps and up.steps[0].text == "Проверьте долг"
    down = _with_level(Verdict(level="act", headline=FALLBACK_HEADLINES["act"], why="x"), "info")
    assert down.headline == FALLBACK_HEADLINES["info"]
