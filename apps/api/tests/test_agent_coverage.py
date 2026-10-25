"""Одно число охвата группы на ленту и карточку; десятичные — через запятую."""

from agent_fakes import GOOD_PLAN, PERSONA, DraftVerdict, good_draft, make_event, reply
from test_agent_checks import make_ctx
from test_agent_loop import make_agent

from api.agent.checks import Checker
from api.agent.context import coverage_fact
from api.agent.drafts import DraftStatement
from api.agent.plain import ru_decimals
from api.contract import GroupImpact

COVERAGE = GroupImpact(
    group_id="G1",
    companies_total=370,
    affected_count=127,
    affected_revenue=127.1e9,
    affected_revenue_bn=127.1,
    affected_share=0.59,
    intra_payments=0,
    intra_share=0,
    text="событие касается 127 компаний группы",
)


def ctx_with_coverage(cov=COVERAGE):
    ctx = make_ctx()
    ctx.coverage = cov
    return ctx


def test_coverage_fact_is_the_feed_phrase():
    from api.coverage import coverage_phrase

    assert (
        coverage_fact(COVERAGE) == coverage_phrase(COVERAGE) == "127 компаний группы с выручкой 127,1 млрд ₽"
    )


def test_bridge_uses_the_shared_coverage_function():
    from agent_fakes import FactorTag, SectorTag

    from api.agent.bridges import ServiceCompanyData

    seen = {}

    def shared(repo, company_id, factors, sectors):
        seen.update(company_id=company_id, factors=factors, sectors=sectors)
        return COVERAGE

    event = make_event(
        factors=[FactorTag(code="tax", strength=0.8)], sectors=[SectorTag(okved="06", strength=0.6)]
    )
    data = ServiceCompanyData(repo=None, coverage_fn=shared)
    assert data.coverage("U_1", event) is COVERAGE
    assert seen == {"company_id": "U_1", "factors": [("tax", 0.8)], "sectors": [("06", 0.6)]}


def test_number_matching_facts_passes():
    checker = Checker(ctx_with_coverage())
    assert checker.coverage_claims("Событие задевает 127 компаний группы с выручкой 127,1 млрд ₽.") == []
    assert checker.coverage_claims("Кредиты у 11 из 28 компаний группы.") == []  # другое число — не охват


def test_other_count_or_revenue_is_caught():
    checker = Checker(ctx_with_coverage())
    assert checker.coverage_claims("63 компании группы с выручкой 80,5 млрд ₽ под ударом")
    assert checker.coverage_claims("Событие касается 63 компаний группы")
    assert checker.coverage_claims("127 компаний с выручкой 90 млрд ₽")


def test_claim_without_coverage_is_caught():
    assert Checker(ctx_with_coverage(None)).coverage_claims("63 компании группы с выручкой 80 млрд ₽")


def test_verdict_with_other_number_is_a_hard_issue():
    ctx = ctx_with_coverage()
    wrong = DraftVerdict(
        level="act",
        headline="Для вас важно: налог заденет группу",
        why="63 компании группы с выручкой 80,5 млрд ₽ платят налог на сверхдоходы.",
        actions=["Посчитайте налог по компаниям группы"],
    )
    assert ("verdict", 0) in Checker(ctx).run(good_draft(verdict=wrong)).hard_at()
    statement = DraftStatement(
        text="Событие касается 63 компаний группы.",
        origin="ai",
        refs=["feat:CL_PRODUCT_LOA_MARK"],
        factor="rate",
    )
    report = Checker(ctx).run(good_draft(risks=[statement, *good_draft().risks]))
    assert ("risks", 0) in report.hard_at()


def test_context_shows_the_one_number():
    from api.agent.bridges import group_from_coverage

    ctx = ctx_with_coverage()
    ctx.group = group_from_coverage(COVERAGE)
    text = ctx.render_group()
    assert "ОХВАТ ГРУППЫ" in text and coverage_fact(COVERAGE) in text
    assert ctx.company_numbers().unsupported("127 компаний, 127,1 млрд ₽, 59 %") == []


def test_decimals_are_russian():
    assert ru_decimals("127.1 млрд ₽ и 14.0 %, Urals $72.5, в 1.5 раза") == (
        "127,1 млрд ₽ и 14,0 %, Urals $72,5, в 1,5 раза"
    )
    # даты, коды отраслей и номера версий не трогаем
    assert ru_decimals("от 11.09.2026, отрасль 46.71 Торговля") == "от 11.09.2026, отрасль 46.71 Торговля"


def test_card_texts_get_russian_decimals():
    verdict = DraftVerdict(
        level="act",
        headline="Для вас важно: ставка 14.0 % до конца года",
        why="Ставка осталась 14% — процентные расходы по вашему кредиту не снизятся.",
        actions=[
            {"text": "Проверьте долг по плавающей ставке", "owner": "финансовой службе", "due": "на неделе"}
        ],
        refs=["feat:CL_PRODUCT_LOA_MARK"],
    )
    agent, _ = make_agent(reply(GOOD_PLAN), reply(good_draft(verdict=verdict)))
    insight = agent.run(PERSONA, make_event()).insight
    assert insight.verdict.headline == "Для вас важно: ставка 14,0 % до конца года"


def test_feed_takeaway_and_agent_get_one_number():
    """Сквозная сверка: число охвата в выводе ленты у разных ролей — то же, что получает агент."""
    from agent_fakes import FactorTag, SectorTag
    from test_api import FakeRepo, GroupNews

    from api.agent.bridges import ServiceCompanyData
    from api.service import persona_feed

    repo = FakeRepo()
    news = GroupNews()
    events = {e.id: e for e in news.events(None, 10)}
    agent_data = ServiceCompanyData(repo)
    checked = 0
    for persona in ("p-u1-owner", "p-u1-cfo", "p-u1-ceo"):
        for item in persona_feed(repo, news, persona).items:
            news_event = events[item.event_id]
            event = make_event(
                factors=[FactorTag(code=c, strength=s) for c, s, _ in news_event.factors],
                sectors=[SectorTag(okved=o, strength=s) for o, s in news_event.sectors],
            )
            coverage = agent_data.coverage("U_1", event)
            assert coverage is not None
            assert coverage_fact(coverage) in item.takeaway.text
            checked += 1
    assert checked == 3
