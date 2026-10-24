"""Требования организаторов: гипотезы отдельно от выводов, расхождение с банком, дисклеймер, остаток ключа."""

import datetime as dt

import pytest
from agent_fakes import (
    FRAGMENT,
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
from test_agent_checks import run
from test_agent_loop import make_agent

from api.agent.drafts import AskAnswer, DraftConflict, DraftStatement
from api.agent.service import AgentService
from api.agent.store import MemoryAgentStore
from api.contract import DISCLAIMER, Insight
from api.llm import Budget, BudgetExceeded, Journal, LlmClient


def hypothesis(**kw) -> DraftStatement:
    base = dict(
        text="Рестораны могут перейти на более дешёвых поставщиков.",
        origin="hypothesis",
        refs=["feat:customer_sectors"],
        confidence="low",
        factor="demand_56",
        confirm="доля поступлений от общепита падает два месяца подряд",
        refute="поступления от общепита держатся на уровне лета",
    )
    return DraftStatement(**{**base, **kw})


def conflict_ai(**kw) -> DraftStatement:
    base = dict(
        text="Ставка начнёт снижаться уже в октябре.",
        origin="ai",
        refs=["feat:CL_PRODUCT_LOA_MARK"],
        confidence="low",
        factor="rate",
        bank_conflict=DraftConflict(text="банк ждёт 14,0% до конца года", refs=[FRAGMENT]),
    )
    return DraftStatement(**{**base, **kw})


# --- самопроверка -----------------------------------------------------------------------------------


def test_hypothesis_needs_confirm_or_refute():
    ok = run(good_draft(risks=[*good_draft().risks, hypothesis()]))
    assert ok.ok, ok.summary()
    bare = run(good_draft(risks=[*good_draft().risks, hypothesis(confirm=None, refute=None)]))
    assert ("risks", 2) in bare.hard_at()


def test_hypothesis_cannot_write_rubles():
    report = run(good_draft(risks=[*good_draft().risks, hypothesis(text="Выручка упадёт на 300 млн ₽.")]))
    assert ("risks", 2) in report.hard_at()


def test_bank_conflict_needs_bank_material():
    good = run(good_draft(risks=[*good_draft().risks, conflict_ai()]))
    assert good.ok, good.summary()
    no_ref = conflict_ai(bank_conflict=DraftConflict(text="банк думает иначе", refs=[NEWS_ID]))
    assert ("risks", 2) in run(good_draft(risks=[*good_draft().risks, no_ref])).hard_at()
    wrong_number = conflict_ai(
        bank_conflict=DraftConflict(text="банк ждёт 11,0% до конца года", refs=[FRAGMENT])
    )
    assert ("risks", 2) in run(good_draft(risks=[*good_draft().risks, wrong_number])).hard_at()
    invented = conflict_ai(
        bank_conflict=DraftConflict(text="банк ждёт 14,0% до конца года", refs=[FRAGMENT, "src:alfa:выдумка"])
    )
    # выдуманная ссылка рядом с настоящей страницей банка не проходит
    assert ("risks", 2) in run(good_draft(risks=[*good_draft().risks, invented])).hard_at()


# --- карточка ---------------------------------------------------------------------------------------


def test_insight_carries_hypothesis_check_conflict_and_disclaimer():
    draft = good_draft(risks=[*good_draft().risks, hypothesis()], opportunities=[conflict_ai()])
    agent, _ = make_agent(reply(GOOD_PLAN), reply(draft))
    insight = agent.run(PERSONA, make_event()).insight
    Insight.model_validate(insight.model_dump())
    hyp = next(s for s in insight.consequences.risks if s.origin == "hypothesis")
    assert hyp.check.confirm and hyp.check.refute
    conflict = insight.consequences.opportunities[0].bank_conflict
    assert conflict.text and conflict.refs == [FRAGMENT]
    assert FRAGMENT in {s.id for s in insight.sources} and insight.unresolved_refs() == set()
    assert insight.disclaimer == DISCLAIMER and "инвестиционной рекомендацией" in insight.disclaimer


def test_contract_drops_fields_that_do_not_belong():
    from api.contract import BankConflict, HypothesisCheck, Statement

    s = Statement(
        text="Факт.",
        origin="fact",
        refs=[NEWS_ID],
        check=HypothesisCheck(confirm="x"),
        bank_conflict=BankConflict(text="y", refs=[FRAGMENT]),
    )
    assert s.check is None and s.bank_conflict is None


def test_ask_answer_has_disclaimer_and_hypothesis():
    answer = AskAnswer(on_topic=True, statements=[hypothesis()])
    service = AgentService(
        make_llm(ScriptedTransport(reply(GOOD_PLAN), reply(good_draft()), reply(answer))),
        FakeCompany(),
        FakeLibrary(),
        MemoryAgentStore(),
    )
    insight = service.insight(NEWS_ID, PERSONA.id)
    out = service.ask(insight.id, "Что будет с ресторанами?")
    assert out.disclaimer == DISCLAIMER
    assert out.answer[0].origin == "hypothesis" and out.answer[0].check.refute


# --- бюджет ключа у шлюза ---------------------------------------------------------------------------


class KeyInfoTransport(ScriptedTransport):
    def __init__(self, spend, *responses):
        super().__init__(*responses)
        self.spend = spend
        self.asked = 0

    def key_info(self):
        self.asked += 1
        return {"info": {"max_budget": 500.0, "spend": self.spend}}


def test_upstream_remaining_limits_runs():
    transport = KeyInfoTransport(498.5)
    llm = LlmClient(
        transport, budget=Budget(100.0), journal=Journal(None), fallbacks={}, sleep=lambda s: None
    )
    assert llm.upstream_remaining() == pytest.approx(1.5)
    assert llm.remaining() == pytest.approx(1.5)  # меньшее из своего лимита и остатка ключа
    llm.upstream_remaining()
    assert transport.asked == 1  # ответ шлюза кэшируется
    service = AgentService(llm, FakeCompany(), FakeLibrary(), MemoryAgentStore())
    with pytest.raises(BudgetExceeded, match="осталось 1.50"):
        service.insight(NEWS_ID, PERSONA.id)
    assert transport.bodies == []


def test_upstream_unknown_falls_back_to_own_budget():
    class Silent(ScriptedTransport):
        def key_info(self):
            return None

    llm = LlmClient(Silent(), budget=Budget(7.0), journal=Journal(None), fallbacks={})
    assert llm.upstream_remaining() is None and llm.remaining() == pytest.approx(7.0)


# --- мост к модулю поиска ---------------------------------------------------------------------------


class FakeSearchRepo:
    """Ведёт себя как api.search.SearchRepo: неизвестный фактор — ValueError (UnknownFilter)."""

    def __init__(self):
        self.calls = []

    def search_alfa_analytics(self, query, topic=None, limit=5, *, factors=None, include_stale=False):
        self.calls.append(factors)
        if factors and "demand_56" in factors:
            raise ValueError("неизвестный фактор demand_56")

        class Fragment:
            id = "src:alfa:keyrate-2026-09#p1-6"
            page_ref = None
            stale = False
            published_at = dt.datetime(2026, 9, 11, tzinfo=dt.UTC)
            text = "полный текст фрагмента"

            def model_dump(self, include=None):
                return {
                    "id": self.id,
                    "kind": "alfa_analytics",
                    "title": "Ключевая ставка",
                    "page": 1,
                    "fragment": "окно…",
                    "published_at": self.published_at,
                }

        return [Fragment()]


def test_search_bridge_retries_without_unknown_factors_and_takes_full_text():
    from api.agent.bridges import SearchLibrary

    repo = FakeSearchRepo()
    hits = SearchLibrary(repo).search_alfa_analytics("ключевая ставка", factors=["rate", "demand_56"])
    assert repo.calls == [["rate", "demand_56"], None]
    assert hits[0].page_ref == "src:alfa:keyrate-2026-09#p1"
    assert hits[0].source.fragment == "полный текст фрагмента"
    assert hits[0].material_date == dt.date(2026, 9, 11)


def test_search_bridge_parse_error():
    from api.agent.bridges import SearchLibrary
    from api.agent.ports import ParseError

    class AnalyzeError(Exception):
        def __init__(self, message):
            super().__init__(message)
            self.message = message

    def analyze(**kw):
        raise AnalyzeError("на странице не нашли текст новости")

    library = SearchLibrary(FakeSearchRepo(), analyze_fn=analyze, analyze_error=AnalyzeError)
    with pytest.raises(ParseError, match="не нашли текст"):
        library.parse_news(url="https://example.test/news")


def test_short_source_refs_are_normalized():
    s = DraftStatement(
        text="Факт.", origin="fact", refs=["alfa:keyrate-2026-09#p1-6", " news:rate1 ", "feat:X"]
    )
    assert s.refs == ["src:alfa:keyrate-2026-09#p1-6", "src:news:rate1", "feat:X"]
