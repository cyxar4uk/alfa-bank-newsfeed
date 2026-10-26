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


# --- «мои числа» пользователя (api.inputs) -------------------------------------------------------------


class Saved:
    """Как `api.contract.UserInputs`: долг, тип ставки, валютные закупки в месяц, топливо в месяц."""

    def __init__(self, **kw):
        import datetime as dt

        self.debt_rub = kw.get("debt_rub")
        self.rate_type = kw.get("rate_type")
        self.fx_purchases_month_rub = kw.get("fx")
        self.fuel_purchase_month_t = kw.get("fuel_t")
        self.updated_at = kw.get("at", dt.datetime(2026, 10, 26, 9, 0))


def test_saved_inputs_map_to_scenarios():
    inputs = scenarios.Inputs.from_user(Saved(debt_rub=2e9, rate_type="fixed", fx=5e7, fuel_t=300))
    assert inputs.debt == 2e9 and inputs.fx == 6e8 and inputs.fuel_t == 300 and inputs.rate_type == "fixed"
    assert not scenarios.Inputs.from_user(None).any()


def test_fixed_rate_and_fuel_tonnes():
    fixed = scenarios.rate(2e9, rate_type="fixed").text
    assert "фиксированная" in fixed and "не изменятся" in fixed
    assert "280 млн ₽" not in fixed and "14" not in fixed
    tonnes = scenarios.oil(fuel_t=300).text
    assert "300 т" in tonnes and "18,1 %" in tonnes and "38,9 %" in tonnes and "маржа" in tonnes


def test_interest_scenario_uses_explicit_contract_rate_not_key_rate():
    result = scenarios.joint_scenario(
        scenarios.Inputs(
            debt=2e9,
            rate_type="floating",
            current_rate_pct=17.5,
            scenario_rate_pct=14,
        )
    )
    assert result is not None
    assert "17,5% → 14%" in result.text
    assert "5,8 млн ₽" in result.text


def test_card_scenarios_use_saved_numbers():
    ctx = make_ctx()
    ctx.page_texts[scenarios.RATE_PAGE] = "14,0% до конца года, 12,0% на конец 2027"
    ctx.user_inputs = Saved(debt_rub=5e8)
    (_, statement, _, _) = scenarios.for_context(ctx)[0]
    assert "ваши 500 млн ₽" in statement.text


def test_card_version_follows_saved_numbers(monkeypatch):
    import datetime as dt

    from agent_fakes import FakeCompany, FakeLibrary, ScriptedTransport, make_llm

    import api.agent.service as service_mod
    from api.agent.loop import insight_id
    from api.agent.service import AgentService
    from api.agent.store import MemoryAgentStore

    stamp = {"value": None}
    monkeypatch.setattr(service_mod, "inputs_stamp", lambda persona_id: stamp["value"])
    llm = make_llm(ScriptedTransport(reply(GOOD_PLAN), reply(good_draft())))
    service = AgentService(llm, FakeCompany(), FakeLibrary(), MemoryAgentStore())
    event = make_event()
    service.insight(event.id, PERSONA.id)
    key = insight_id(event.id, PERSONA.id)
    assert service.cached(key, PERSONA.id) is not None
    # пользователь сохранил «мои числа» — старая карточка не отдаётся, рубли пересчитаются
    stamp["value"] = dt.datetime(2026, 10, 26, 9, 0).isoformat()
    assert service.cached(key, PERSONA.id) is None
    assert service.cached(key) is not None  # вопрос и пересчёт по открытой карточке — работают


def test_own_news_without_sectors_gets_them_from_the_cheap_model():
    from agent_fakes import ScriptedTransport, make_llm

    from api.agent.sectors import SectorGuess, SectorGuesses, guess_sectors

    llm = make_llm(
        ScriptedTransport(
            reply(
                SectorGuesses(
                    items=[SectorGuess(okved="46.71", name="Торговля топливом"), SectorGuess(okved="x")]
                )
            )
        )
    )
    found = guess_sectors(llm, make_event())
    assert [(s.okved, s.via) for s in found] == [("46", "llm")] and found[0].strength == 0.5


# --- замечания эксперта жюри ---------------------------------------------------------------------------


def test_bank_wording_is_forbidden_in_own_conclusions():
    from api.agent.checks import Checker

    ai = DraftStatement(
        text="Банк считает это выгодным для заёмщиков.",
        origin="ai",
        refs=["feat:CL_PRODUCT_LOA_MARK"],
        factor="rate",
    )
    report = Checker(make_ctx()).run(good_draft(risks=[ai, *good_draft().risks]))
    assert ("risks", 0) in report.hard_at() and any(i.check == "bank_quotes" for i in report.issues)
    central = DraftStatement(
        text="Банк России считает ставку достаточной.",
        origin="ai",
        refs=["feat:CL_PRODUCT_LOA_MARK"],
        factor="rate",
    )
    assert ("risks", 0) not in Checker(make_ctx()).run(good_draft(risks=[central])).hard_at()


def test_quote_subject_must_be_the_bank():
    from agent_fakes import BANK_PAGE

    from api.agent.checks import Checker

    checker = Checker(make_ctx())
    assert checker.bank_subject("мы ожидаем ее сохранения на текущем значении 14,0%", [BANK_PAGE])
    monetary = "Решение о бюджетных вводных станет индикатором для денежных властей. Рынок ждёт паузы."
    assert not checker.bank_subject("станет индикатором для денежных властей", [monetary])


def test_money_from_company_data_may_be_repeated():
    from api.agent.checks import Checker

    ctx = make_ctx()
    checker = Checker(ctx)
    assert checker.money_unfounded("Выручка 777 млн ₽ выросла") == ["777 млн ₽"]
    ctx.profile.features[0].value = 777_000_000
    assert Checker(ctx).money_unfounded("Выручка 777 млн ₽ выросла") == []


def test_dollar_fall_and_ruble_weakness_conflict():
    from api.agent.checks import Checker

    event = make_event()
    event.source.title = "Курс доллара опустился до 80,19 рубля"
    checker = Checker(make_ctx(event=event))
    assert checker.direction_problem("Рубль у минимумов: ослабление рубля дорожает закупку")
    assert checker.direction_problem("Рубль стал крепче, импорт дешевеет") is None


def test_refs_without_source_are_cut_not_just_reported():
    from api.agent.loop import prune_refs
    from api.contract import Consequences, Insight, InsightEvent, Relevance, Statement

    insight = Insight(
        id="ins:1",
        event=InsightEvent(title="x"),
        relevance=Relevance(score=0.5, reason="x", refs=["feat:UNKNOWN"]),
        why_it_matters=[Statement(text="Данные без признака.", origin="data", refs=["feat:UNKNOWN"])],
        consequences=Consequences(
            risks=[Statement(text="Вывод.", origin="ai", refs=["feat:UNKNOWN", "feat:KNOWN"])]
        ),
        features_used=["feat:KNOWN"],
    )
    cut = prune_refs(insight)
    assert cut == {"feat:UNKNOWN"} and insight.why_it_matters == []  # data без источника не показываем
    assert insight.consequences.risks[0].refs == ["feat:KNOWN"] and insight.relevance.refs == []
    assert insight.unresolved_refs() == set()


def test_own_news_is_capped_at_watch():
    from agent_fakes import fact

    draft = good_draft(what_happened=[fact(refs=["src:news:user-1"])])
    agent, _ = make_agent(reply(GOOD_PLAN), reply(draft))
    event = make_event()
    event.source.id = "src:news:user-1"
    insight = agent.run(PERSONA, event).insight
    assert insight.relevance.score <= 0.49 and insight.verdict.level != "act"


def test_bank_position_marks_outdated_material():
    from datetime import date

    from agent_fakes import FRAGMENT
    from test_agent_verdict import BUDGET_FRAGMENT, TwoMaterials

    from api.agent.loop import _outdated

    ctx = make_ctx(analytics=TwoMaterials().search_alfa_analytics(""))
    old = next(h for h in ctx.analytics if h.source.id == BUDGET_FRAGMENT)
    new = next(h for h in ctx.analytics if h.source.id == FRAGMENT)
    assert old.material_date < new.material_date == date(2026, 9, 11)
    flag, note = _outdated(ctx, old)
    assert isinstance(flag, bool) and (note is None or "свежее" in note or "более свежий" in note)


def test_other_banks_are_not_alfa_claims():
    from api.agent.checks import _BANK_CLAIM

    others = ("Банк ВТБ ожидает снижения ставки.", "Центральный банк ожидает паузы.")
    ours = (
        "Банк считает это выгодным.",
        "Альфа-Банк ожидает ставку 14 %.",
        "По мнению банка, ставка вырастет.",
    )
    for text in (*others, "Банковский сектор ожидает роста."):
        assert not _BANK_CLAIM.search(text), text
    for text in ours:
        assert _BANK_CLAIM.search(text), text


def test_bank_subject_third_person_and_other_agencies():
    from api.agent.checks import Checker

    checker = Checker(make_ctx())
    third = "Аналитики банка ожидают снижения ставки в 2027 году."
    assert checker.bank_subject("ожидают снижения ставки", [third])
    other = "Прогноз ЦБ предполагает снижение ставки в 2027 году."
    assert not checker.bank_subject("предполагает снижение ставки", [other])
    own_forecast = "Прогноз по курсу рубля остаётся на уровне 87 руб./$."
    assert checker.bank_subject("остаётся на уровне 87", [own_forecast])


def test_judge_marks_the_contradicting_risk():
    from agent_fakes import FakeCompany, FakeLibrary, ScriptedTransport, make_llm

    from api.agent.drafts import DraftDirection
    from api.agent.loop import Agent, DirectionVerdict
    from api.agent.trace import TraceRecorder

    judged = DirectionVerdict(consistent=False, problem="крепкий рубль удешевляет закупку", risk_indexes=[1])
    agent = Agent(make_llm(ScriptedTransport(reply(judged))), FakeCompany(), FakeLibrary())
    direction = DraftDirection(what="доллар упал", direction="down", beneficiary="импортёры")
    report = agent.check(make_ctx(), good_draft(event_direction=direction), TraceRecorder())
    marked = {(i.block, i.index) for i in report.issues if i.check == "verdict"}
    assert ("verdict", 0) in marked and ("risks", 1) in marked
    assert ("risks", 1) in report.hard_at()
