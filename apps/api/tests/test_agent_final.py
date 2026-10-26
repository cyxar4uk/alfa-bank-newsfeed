"""Финальный проход: «мои числа» в карточке и чате, одна база ставки, цитаты предложениями."""

import datetime as dt

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
    reply,
)
from test_agent_checks import make_ctx

from api.agent import scenarios
from api.agent.loop import _whole_sentence, insight_id
from api.agent.service import AgentService
from api.agent.store import MemoryAgentStore
from api.contract import UserInputs

RATE_TEXT = "ставка 14,0% до конца года, 12,0% на конец 2027"


def Saved(debt=1.5e9, kind="floating"):  # noqa: N802
    return UserInputs(debt_rub=debt, rate_type=kind, updated_at=dt.datetime(2026, 10, 26, 12, 0))


def test_rate_scenario_has_one_base_and_percent_phrase():
    text = scenarios.rate().text
    assert "140 млн ₽" in text and "120 млн ₽" in text and "примерно на 14 % меньше текущих выплат" in text
    assert "14,6" not in text and "13,0" not in text


def test_user_lines_give_rubles_for_chat_rates():
    lines = scenarios.user_lines(Saved())
    assert len(lines) == 1 and "по вашим данным 1,5 млрд ₽" in lines[0]
    assert (
        "при 16 % — 240 млн ₽" in lines[0] and "при 12 % — 180 млн ₽" in lines[0] and "плавающая" in lines[0]
    )
    assert scenarios.user_lines(None) == []


def test_context_shows_user_numbers_and_allows_quoting_them():
    ctx = make_ctx()
    ctx.user_inputs = Saved()
    assert "по вашим данным 1,5 млрд ₽" in ctx.render_company()
    assert ctx.company_numbers().unsupported("240 млн ₽ при ставке 16 %") == []


def test_card_rubles_are_repriced_without_a_rebuild(monkeypatch):
    import api.agent.scenarios as sc
    import api.agent.service as service_mod

    state = {"saved": None, "stamp": None}
    monkeypatch.setattr(sc, "saved_inputs", lambda persona_id: state["saved"])
    monkeypatch.setattr(service_mod, "inputs_stamp", lambda persona_id: state["stamp"])
    transport = ScriptedTransport(reply(GOOD_PLAN), reply(good_draft()))
    service = AgentService(make_llm(transport), FakeCompany(), FakeLibrary(), MemoryAgentStore())
    event = make_event()
    first = service.insight(event.id, PERSONA.id)
    calls = len(transport.bodies)
    stored = service.store.get_insight(insight_id(event.id, PERSONA.id))
    stored.context["page_texts"][sc.RATE_PAGE] = RATE_TEXT  # прогноз банка сверен — сценарий ставки возможен
    service.store.save_insight(event.id, PERSONA.id, stored)
    # пользователь сохранил долг: карточка пересчитывает рубли на нём, модель не зовётся
    state["saved"], state["stamp"] = Saved(), "2026-10-26T12:00:00"
    second = service.insight(event.id, PERSONA.id)
    texts = [s.text for s in second.consequences.risks]
    assert len(transport.bodies) == calls
    assert any("ваши 1,5 млрд ₽" in t and "210 млн ₽" in t for t in texts), texts
    assert first.id == second.id and service.cached(insight_id(event.id, PERSONA.id), PERSONA.id) is not None


def test_whole_sentence_for_highlight():
    text = (
        "ЦБ сохранил ставку. Совет директоров оставил ключевую ставку на уровне 14% годовых. "
        "Следующее заседание в декабре."
    )
    assert _whole_sentence(text, "ключевую ставку на уровне 14%") == (
        "Совет директоров оставил ключевую ставку на уровне 14% годовых."
    )
    assert _whole_sentence(text, "нет такой цитаты") == "нет такой цитаты"
    assert NEWS_ID
