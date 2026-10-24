"""Вывод, а не факт: итог «важно ли → почему → что делать», позиция банка одной фразой, цитаты, язык."""

from agent_fakes import (
    FRAGMENT,
    GOOD_PLAN,
    NEWS_ID,
    PERSONA,
    DraftBankPosition,
    DraftVerdict,
    FakeLibrary,
    good_draft,
    make_event,
    reply,
)
from test_agent_checks import run
from test_agent_loop import make_agent

from api.agent.drafts import DraftStatement
from api.agent.plain import technical
from api.agent.trace import TraceRecorder
from api.contract import Insight


class NoAnalytics(FakeLibrary):
    def search_alfa_analytics(self, query, *, factors=None, limit=5, material=None):
        return []


def build(*drafts, **kw) -> Insight:
    agent, _ = make_agent(reply(GOOD_PLAN), *(reply(d) for d in drafts), **kw)
    return agent.run(PERSONA, make_event()).insight


def test_insight_carries_verdict_bank_position_and_quotes():
    insight = build(good_draft())
    v = insight.verdict
    assert v.level == "act" and v.headline.startswith("Для вас важно") and "14%" in v.why and v.actions
    bp = insight.bank_position
    assert bp.found and bp.statement.startswith("Альфа-Банк ожидает")
    assert bp.source_id == FRAGMENT and bp.material and bp.date is not None and bp.analyst is None
    assert insight.quotes and insight.quotes[0].source_id == NEWS_ID
    assert insight.quotes[0].text.lower() in make_event().text.lower()
    assert insight.unresolved_refs() == set()


def test_no_bank_material_is_said_honestly():
    insight = build(good_draft(bank_view=[], bank_position=None), library=NoAnalytics())
    assert insight.bank_position.found is False
    assert "не публиковал позицию" in insight.bank_position.statement


def test_technical_words_are_caught():
    assert technical("По карте чувствительности у компании высокий фактор rate")
    assert technical("Через канал покупателей") and technical("скор 0,4")
    # продукт банка и обычные слова — не служебные
    assert not technical("Проверьте лимит факторинга по покупателям из розницы")
    assert not technical("Ставка осталась 14% — процентные расходы не снизятся")


def test_technical_statement_is_a_hard_issue():
    bad = DraftStatement(
        text="По карте чувствительности фактор rate высокий.",
        origin="ai",
        refs=["feat:CL_PRODUCT_LOA_MARK"],
        factor="rate",
    )
    report = run(good_draft(risks=[bad, *good_draft().risks]))
    assert ("risks", 0) in report.hard_at()
    assert any(i.check == "plain_language" for i in report.issues)


def test_verdict_needs_number_and_steps_for_action():
    vague = DraftVerdict(
        level="act", headline="Для вас важно: ставка", why="Это скажется на долге.", actions=[]
    )
    report = run(good_draft(verdict=vague))
    assert {i.message for i in report.issues if i.check == "verdict"} >= {
        "в «почему» нет числа из данных о компании или новости",
        "итог «действовать/следить» без шагов: что делать",
    }
    calm = DraftVerdict(level="info", headline="На вашу компанию почти не влияет", why="Кредитов и ВЭД нет.")
    assert not [i for i in run(good_draft(verdict=calm)).issues if i.check == "verdict"]


def test_invented_number_in_verdict_falls_back():
    invented = DraftVerdict(
        level="act",
        headline="Для вас важно: расходы вырастут",
        why="Процентные расходы вырастут на 37%.",
        actions=["Пересчитайте бюджет"],
    )
    # и черновик, и обе доработки с выдуманным числом — итог собирается из карточки, без него
    insight = build(*(good_draft(verdict=invented) for _ in range(3)))
    assert "37" not in insight.verdict.why and insight.verdict.level in ("act", "watch", "info")


def test_bank_position_must_speak_for_the_bank_and_quote_the_material():
    quote = "теперь мы ожидаем ее сохранения на текущем значении 14,0% до конца года"
    impersonal = DraftBankPosition(
        statement="Ставка будет 14,0% до конца года.", refs=[FRAGMENT], quote=quote
    )
    assert ("bank_position", 0) in run(good_draft(bank_position=impersonal)).hard_at()
    made_up = DraftBankPosition(
        statement="Альфа-Банк ожидает ставку 14,0% до конца года.",
        refs=[FRAGMENT],
        quote="банк ждёт снижения",
    )
    assert ("bank_position", 0) in run(good_draft(bank_position=made_up)).hard_at()
    wrong = DraftBankPosition(
        statement="Альфа-Банк ожидает ставку 10% к декабрю.", refs=[FRAGMENT], quote=quote
    )
    assert ("bank_position", 0) in run(good_draft(bank_position=wrong)).hard_at()


def test_user_sees_only_plain_warnings():
    draft = good_draft(warnings=["нет данных о типе ставки", "фактор fx не размечен"])
    insight = build(draft, draft, draft)
    assert "нет данных о типе ставки" in insight.quality.warnings
    assert all(not technical(w) for w in insight.quality.warnings)


def test_progress_steps_are_human_and_hide_technical_findings():
    seen = []
    trace = TraceRecorder(on_progress=seen.append)
    trace.stage("Ищу, что пишет об этом Альфа-Банк")
    trace.found("Материал банка «Ключевая ставка» от 11.09.2026", "фактор rate", "src:alfa:x")
    trace.stage("Формулирую вывод: важно ли это вам и что делать")
    trace.finish()
    steps = seen[-1]
    assert [s.state for s in steps] == ["done", "done"]
    assert steps[0].found == ["Материал банка «Ключевая ставка» от 11.09.2026"]


def test_data_notes_are_humanized_or_hidden():
    from api.agent.plain import humanize_note

    assert humanize_note("платежи в выгрузке — 0,7 % выручки: цепочки не строим") == (
        "платежи в данных банка — лишь 0,7 % выручки: влияние через контрагентов не оценить"
    )
    assert humanize_note("по контрагентам данных недостаточно (см. gaps) — связь не проверить") == (
        "по контрагентам данных недостаточно — связь не проверить"
    )
    assert humanize_note("цепочка покупателей не построена") is None
    assert humanize_note("Нет данных о типе ставки по кредиту") == "Нет данных о типе ставки по кредиту"


def test_company_ids_are_not_for_users():
    assert technical("по компании U_34961 (21 % оборота) отрасль неизвестна")
    assert not technical("Компания №34961 — 21 % оборота")


def test_ordinary_words_are_not_flagged():
    assert not technical("Банк России скорее всего сохранит ставку, решение скоро")
    assert not technical("Токенизация активов и цифровые токены — новая тема рынка")
    # в пересказе источника обычные «канал» и «фактор» уместны, в выводе — нет
    assert not technical("Суэцкий канал закрыт для танкеров", quoting=True)
    assert technical("Через канал покупателей событие дойдёт до вас")
    assert technical("по признаку CL_PRODUCT_LOA_MARK") and technical("риск fx высокий")


def test_progress_failure_does_not_break_the_build():
    def broken(steps):
        raise RuntimeError("БД недоступна")

    agent, _ = make_agent(reply(GOOD_PLAN), reply(good_draft()))
    insight = agent.run(PERSONA, make_event(), on_progress=broken).insight
    assert insight.verdict is not None


def test_long_finding_is_not_repeated():
    trace = TraceRecorder()
    trace.stage("Шаг")
    long = "Материал банка " + "очень длинный " * 20
    trace.found(long, long)
    assert len(trace.steps[0].found) == 1


def test_bank_position_cites_the_checked_page():
    quote = "теперь мы ожидаем ее сохранения на текущем значении 14,0% до конца года"
    page = DraftBankPosition(
        statement="Альфа-Банк ожидает сохранения ставки 14,0% до конца года.",
        refs=["src:alfa:keyrate-2026-09#p1"],
        quote=quote,
    )
    insight = build(good_draft(bank_position=page))
    assert insight.bank_position.source_id == "src:alfa:keyrate-2026-09#p1"
    assert insight.unresolved_refs() == set()
