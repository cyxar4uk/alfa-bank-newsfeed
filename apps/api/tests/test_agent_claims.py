"""Проверка каждого утверждения карточки: опора (новость, материал банка, данные компании) и числа."""

from agent_fakes import GOOD_PLAN, NEWS_ID, PERSONA, good_draft, make_event, reply
from test_agent_checks import make_ctx
from test_agent_loop import make_agent

from api.agent.claims import Verifier, verify
from api.contract import Consequences, Insight, InsightEvent, Relevance, Statement


def build():
    agent, _ = make_agent(reply(GOOD_PLAN), reply(good_draft()))
    return agent.run(PERSONA, make_event())


def test_card_carries_claims_and_summary():
    insight = build().insight
    summary = insight.claims_summary
    assert summary.total == len(insight.claims) > 0
    assert summary.verified_count + summary.partly_count + summary.hypothesis_count == summary.total
    verified = [c for c in insight.claims if c.status == "verified"]
    assert verified and all(c.support for c in verified)
    kinds = {s.kind for c in insight.claims for s in c.support}
    assert {"company", "bank"} <= kinds  # данные компании и материал банка


def test_trace_has_claims_step():
    result = build()
    steps = [s.summary or "" for s in result.trace.steps if s.tool == "verify_claims"]
    assert any(s.startswith("Проверка утверждений: подтверждено") for s in steps)
    assert any("Утверждения вывода: подтверждено" in c for c in result.trace.summary.checked)


def test_numbers_are_normalized():
    v = Verifier(make_ctx())
    # в новости «14%», в материале банка «14,0%»: оба написания — одно число
    assert v.claim("Ставка осталась 14,0 %.", [NEWS_ID]).status == "verified"
    claim = v.claim("Ставка выросла до 27 %.", [NEWS_ID])
    assert claim.status == "partly" and claim.unsupported_numbers == ["27"]


def test_support_by_overlap_for_claims_without_refs():
    v = Verifier(make_ctx())
    claim = v.claim("Совет директоров Банка России сохранил ключевую ставку на уровне 14%.", [])
    assert claim.support and claim.support[0].kind == "news"


def test_hypothesis_status():
    v = Verifier(make_ctx())
    assert v.claim("Возможно, рестораны сократят закупки.", []).status == "hypothesis"


def test_unfounded_conclusion_is_removed():
    ctx = make_ctx()
    insight = Insight(
        id="ins:1",
        event=InsightEvent(title="x"),
        relevance=Relevance(score=0.5, reason="x"),
        why_it_matters=[
            Statement(text="Выручка упадёт на 37 % из-за пошлин на импорт.", origin="ai", refs=[])
        ],
        consequences=Consequences(
            risks=[Statement(text="Ставка осталась 14 %.", origin="ai", refs=[NEWS_ID])]
        ),
    )
    summary = verify(ctx, insight, rewritten=2, dropped=1)
    assert insight.why_it_matters == []  # число ни в каких фактах и опоры нет
    assert summary.removed == 2 and summary.rewritten == 2
    assert [c.status for c in insight.claims] == ["verified"]


def test_each_number_points_to_its_source():
    v = Verifier(make_ctx())
    claim = v.claim("У компании кредит, а ставка осталась 14% годовых.", ["feat:CL_PRODUCT_LOA_MARK"])
    assert any(s.kind == "news" and "14%" in s.quote for s in claim.support)


def test_ref_without_common_words_is_not_support():
    v = Verifier(make_ctx())
    # ссылка на новость про ставку не подтверждает совет о складе
    claim = v.claim("Проверьте складские запасы обуви у покупателей.", [NEWS_ID])
    assert not any(s.kind == "news" for s in claim.support) and claim.status == "partly"


def test_bool_feature_reads_as_yes_and_advice_is_not_hypothesis():
    v = Verifier(make_ctx())
    claim = v.claim("У компании кредит в банке.", ["feat:CL_PRODUCT_LOA_MARK"])
    assert claim.support and "True" not in claim.support[0].quote
    assert v.claim("Можно обсудить с банком график.", []).status != "hypothesis"
