from types import SimpleNamespace

from api.agent.inputs import fx_flow
from api.agent.scenarios import Inputs, joint_scenario, user_lines
from api.contract import UserInputsIn


def test_fx_flow_is_monthly_net_cash_movement_not_profit():
    flow = fx_flow(400_000_000, 150_000_000, 90, 95)
    assert flow.base_month_rub == 250_000_000
    assert flow.scenario_month_rub == 250_000_000 * 95 / 90
    assert flow.change_month_rub == 250_000_000 * (95 / 90 - 1)


def test_joint_scenario_handles_fixed_debt_without_repricing():
    result = joint_scenario(Inputs(debt=2_000_000_000, rate_type="fixed", scenario_rate_pct=12))
    assert result is not None
    assert "14" not in result.text
    assert "0 \u20bd" in result.text
    assert "\u0434\u043e \u043f\u0435\u0440\u0435\u0441\u043c\u043e\u0442\u0440\u0430" in result.text


def test_joint_scenario_components_and_total_use_same_monthly_period():
    result = joint_scenario(
        Inputs(
            receipts_month=100_000_000,
            purchases_month=60_000_000,
            fx_currency="USD",
            fx_base_rate=90,
            fx_scenario_rate=99,
            debt=120_000_000,
            rate_type="floating",
            current_rate_pct=10,
            scenario_rate_pct=12,
        )
    )
    assert result is not None
    assert "4 \u043c\u043b\u043d \u20bd" in result.text
    assert "200 \u0442\u044b\u0441. \u20bd" in result.text
    assert "3,8 \u043c\u043b\u043d \u20bd" in result.text
    assert "\u0440\u0430\u0432\u043d\u043e\u043c\u0435\u0440\u043d\u043e" in result.text
    assert "\u043d\u0435 \u043f\u0440\u0438\u0431\u044b\u043b\u044c" in result.text
    assert "\u043d\u0435 \u043f\u0440\u043e\u0433\u043d\u043e\u0437" in result.text


def test_interest_uses_explicit_contract_rate_not_key_rate():
    result = joint_scenario(
        Inputs(
            debt=2_000_000_000,
            rate_type="floating",
            current_rate_pct=17.5,
            scenario_rate_pct=14,
        )
    )
    assert result is not None
    assert "17,5% \u2192 14%" in result.text
    assert "5,8" in result.text


def test_fixed_user_lines_do_not_list_hypothetical_credit_rates():
    saved = SimpleNamespace(
        debt_rub=2_000_000_000,
        rate_type="fixed",
        fx_purchases_month_rub=None,
        fx_revenue_month_rub=None,
        fuel_purchase_month_t=None,
        fx_currency=None,
        fx_base_rate=None,
        fx_scenario_rate=None,
        current_rate_pct=None,
        scenario_rate_pct=None,
    )
    lines = user_lines(saved)
    assert any("0 \u20bd" in line for line in lines)
    assert "не меняются до пересмотра" in lines[0]
    assert "при 14" not in lines[0]


def test_missing_fx_data_does_not_make_up_a_scenario():
    saved = SimpleNamespace(
        fx_revenue_month_rub=100,
        fx_purchases_month_rub=None,
        fx_currency=None,
        fx_base_rate=None,
        fx_scenario_rate=None,
        debt_rub=None,
        rate_type=None,
        current_rate_pct=None,
        scenario_rate_pct=None,
        fuel_purchase_month_t=None,
    )
    assert joint_scenario(Inputs.from_user(saved)) is None


def test_contract_accepts_new_fields():
    data = UserInputsIn(
        fx_revenue_month_rub=10,
        fx_purchases_month_rub=5,
        fx_currency="USD",
        fx_base_rate=90,
        fx_scenario_rate=95,
        current_rate_pct=16,
        scenario_rate_pct=12,
    )
    assert data.fx_currency == "USD"


def test_inputs_endpoint_saves_updates_and_rejects_invalid_fields():
    from fastapi.testclient import TestClient
    from test_api import FakeRepo

    from api.inputs import STORE
    from api.main import app, get_repo

    app.dependency_overrides[get_repo] = FakeRepo
    try:
        client = TestClient(app)
        path = "/api/personas/p-u1-cfo/inputs"
        payload = {
            "fx_revenue_month_rub": 400_000_000,
            "fx_purchases_month_rub": 150_000_000,
            "fx_currency": "USD",
            "fx_base_rate": 90,
            "fx_scenario_rate": 95,
            "debt_rub": 2_000_000_000,
            "rate_type": "floating",
            "current_rate_pct": 16,
            "scenario_rate_pct": 12,
        }
        assert client.put(path, json=payload).status_code == 200
        assert client.get(path).json()["current_rate_pct"] == 16
        assert client.put(path, json={**payload, "scenario_rate_pct": 10}).status_code == 200
        assert client.get(path).json()["scenario_rate_pct"] == 10
        assert client.put(path, json={**payload, "fx_currency": "US"}).status_code == 422
        assert client.put(path, json={**payload, "fx_base_rate": -1}).status_code == 422
        assert STORE.get("p-u1-cfo").scenario_rate_pct == 10
    finally:
        app.dependency_overrides.clear()


def test_deposit_event_does_not_trigger_credit_cost_or_credit_question():
    from agent_fakes import FactorTag, make_event
    from test_agent_checks import make_ctx

    from api.agent.clarifications import clarification_questions
    from api.agent.scenarios import for_context

    event = make_event(factors=[FactorTag(code="deposit_yield", strength=0.9)])
    event.source.title = "Deposit yields rose"
    ctx = make_ctx(event=event)
    assert for_context(ctx) == []
    assert clarification_questions(ctx, None) == []


def test_reprice_replaces_existing_joint_scenario_lines_without_duplicates():
    from copy import deepcopy
    from types import SimpleNamespace

    from agent_fakes import make_event
    from test_agent_checks import make_ctx

    from api.agent.scenarios import reprice
    from api.contract import Statement

    event = make_event()
    event.source.title = "Курс доллара изменился"
    ctx = make_ctx(event=event)
    ctx.user_inputs = SimpleNamespace(
        debt_rub=120_000_000,
        rate_type="floating",
        current_rate_pct=10,
        scenario_rate_pct=12,
        fx_revenue_month_rub=100_000_000,
        fx_purchases_month_rub=60_000_000,
        fx_currency="USD",
        fx_base_rate=90,
        fx_scenario_rate=99,
        fuel_purchase_month_t=None,
    )

    class ExistingInsight:
        def __init__(self):
            old = Statement(text="Валютная часть за месяц: stale", origin="estimate", refs=[])
            self.consequences = SimpleNamespace(risks=[old], opportunities=[], factors=[old.model_copy()])

        def model_copy(self, deep=True):
            return deepcopy(self)

    updated = reprice(ExistingInsight(), ctx)
    texts = [item.text for item in updated.consequences.factors]
    assert any("3,8" in text for text in texts)
    assert "stale" not in " ".join(texts)
