"""Самопроверка ловит подложенные дефекты на фиксированных черновиках — без модели."""

import datetime as dt

import pytest
from agent_fakes import (
    BANK_PAGE,
    CHAIN,
    EXPOSURE,
    FRAGMENT,
    PAGE,
    PERSONA,
    bank,
    fact,
    good_draft,
    make_event,
    make_profile,
)

from api.agent.checks import CHECKS, Checker, normalize, quote_in
from api.agent.context import AgentContext
from api.agent.drafts import DraftAction, DraftStatement
from api.agent.loop import _without
from api.agent.ports import AnalyticsHit
from api.contract import Source


def make_ctx(**overrides) -> AgentContext:
    hit = AnalyticsHit(
        source=Source(
            id=FRAGMENT, kind="alfa_analytics", title="Ключевая ставка", page=1, fragment=BANK_PAGE
        ),
        page_ref=PAGE,
        material_date=dt.date(2026, 9, 11),
    )
    values = dict(
        persona=PERSONA,
        profile=make_profile(),
        event=make_event(),
        exposure=EXPOSURE,
        chain=CHAIN,
        analytics=[hit],
        page_texts={PAGE: BANK_PAGE},
    )
    values.update(overrides)
    return AgentContext(**values)


def run(draft, **ctx):
    return Checker(make_ctx(**ctx)).run(draft)


def checks_failed(report) -> set[str]:
    return {i.check for i in report.issues}


def test_good_draft_passes_everything():
    report = run(good_draft())
    assert report.ok, report.summary()
    assert report.passed == list(CHECKS)


def test_fact_without_source():
    draft = good_draft(what_happened=[fact(refs=[])])
    report = run(draft)
    assert "refs" in checks_failed(report)
    assert ("what_happened", 0) in report.hard_at()
    # не исправлено доработкой — утверждение убирается из карточки
    assert _without(draft, report).what_happened == []


def test_data_without_feature():
    why = good_draft().why_it_matters
    why[0] = DraftStatement(text="У компании кредит в банке.", origin="data", refs=[], factor="rate")
    report = run(good_draft(why_it_matters=why))
    assert any(i.check == "refs" and i.block == "why_it_matters" for i in report.issues)


def test_ref_outside_context():
    draft = good_draft(what_happened=[fact(refs=["src:news:never-seen"])])
    report = run(draft)
    assert any("не из контекста" in i.message for i in report.issues)


def test_invented_bank_quote():
    fake = bank(quote="банк ожидает снижения ставки до 10% уже в октябре")
    report = run(good_draft(bank_view=[fake]))
    assert "bank_quotes" in checks_failed(report)
    assert ("bank_view", 0) in report.hard_at()


def test_bank_quote_found_in_page_text_despite_line_breaks_and_yo():
    # в распознанном тексте перенос строки внутри фразы и «е» вместо «ё»
    quote = (
        "Если раньше мы ориентировались на ставку на уровне 13,5% на конец 2026 г., то теперь мы ожидаем её"
    )
    statement = bank(text="Раньше банк ждал 13,5% на конец 2026 года, теперь — 14,0%.", quote=quote)
    report = run(good_draft(bank_view=[statement]))
    assert report.ok, report.summary()


def test_bank_view_without_alfa_source():
    report = run(good_draft(bank_view=[bank(refs=["src:news:rate1"])]))
    assert any("страницу аналитики" in i.message for i in report.issues)


def test_bank_number_not_on_page():
    statement = bank(text="Альфа-Банк ждёт 11,5% на конец 2027 года.")
    report = run(good_draft(bank_view=[statement]))
    assert any("11,5" in i.message for i in report.issues)


def test_stale_material_is_not_bank_position():
    hit = AnalyticsHit(
        source=Source(id=FRAGMENT, kind="alfa_analytics", title="Сталь 2021", page=1, fragment=BANK_PAGE),
        page_ref=PAGE,
        stale=True,
    )
    report = run(good_draft(), analytics=[hit])
    assert any("устаревший" in i.message for i in report.issues)


def test_fact_quote_not_in_news():
    report = run(good_draft(what_happened=[fact(quote="ЦБ снизил ключевую ставку до 13%")]))
    assert "facts_in_source" in checks_failed(report)


def test_fact_number_not_in_source():
    report = run(good_draft(what_happened=[fact(text="ЦБ сохранил ставку 14%, инфляция 9,2%.")]))
    assert any("9,2" in i.message for i in report.issues)


def test_single_factor_is_retelling():
    draft = good_draft()
    for s in [*draft.why_it_matters, *draft.risks]:
        s.factor, s.refs = "rate", ["feat:CL_PRODUCT_LOA_MARK"]
    report = run(draft)
    assert "multi_factor" in checks_failed(report)
    assert not report.hard_at()  # переписать, а не вырезать


def test_unknown_factor_code_does_not_count():
    draft = good_draft()
    for s in [*draft.why_it_matters, *draft.risks]:
        s.factor, s.refs = "rate", ["feat:CL_PRODUCT_LOA_MARK"]
    draft.risks[1].factor = "commodity_gold"  # такого фактора у компании нет
    assert "multi_factor" in checks_failed(run(draft))


def test_data_number_not_in_company_data():
    why = good_draft().why_it_matters
    why[1] = DraftStatement(
        text="43 % поступлений — от покупателей из общепита.", origin="data", refs=["feat:customer_sectors"]
    )
    report = run(good_draft(why_it_matters=why))
    assert any(i.check == "numbers_from_tools" and "43" in i.message for i in report.issues)


def test_data_number_from_profile_is_ok():
    why = good_draft().why_it_matters
    why[1] = DraftStatement(
        text="Покупатель из общепита — 67 % оборота, выручка компании 20,0 млрд ₽.",
        origin="data",
        refs=["feat:customer_sectors", "feat:REVENUE_COMPANY"],
        factor="demand_56",
    )
    assert run(good_draft(why_it_matters=why)).ok


def test_model_does_not_write_rubles():
    risks = good_draft().risks
    risks[0] = DraftStatement(
        text="Процентные расходы вырастут на 50 млн ₽ в год.", origin="ai", refs=["feat:CL_PRODUCT_LOA_MARK"]
    )
    report = run(good_draft(risks=risks))
    assert any("расчётный инструмент" in i.message for i in report.issues)


def test_rubles_in_action():
    actions = [DraftAction(text="Заложить резерв 100 млн ₽ на проценты.", kind="scenario")]
    report = run(good_draft(actions=actions))
    assert ("actions", 0) in report.hard_at()


def test_counterparty_outside_chain():
    risks = good_draft().risks
    risks[1] = DraftStatement(
        text="Компания №777 может задержать оплату.",
        origin="ai",
        refs=["feat:customer_sectors"],
        factor="demand_56",
    )
    report = run(good_draft(risks=risks))
    assert "counterparties_in_chain" in checks_failed(report)


def test_counterparty_from_chain_is_ok():
    risks = good_draft().risks
    risks[1] = DraftStatement(
        text="Крупнейший покупатель U_2 из общепита может задержать оплату.",
        origin="ai",
        refs=["feat:customer_sectors"],
        factor="demand_56",
    )
    assert run(good_draft(risks=risks)).ok


def test_role_not_reflected():
    why = good_draft().why_it_matters
    why[2] = DraftStatement(
        text="Рестораны сократят закупки.", origin="ai", refs=["feat:customer_sectors"], factor="demand_56"
    )
    actions = [DraftAction(text="Обсудить новость с командой.", kind="question")]
    report = run(good_draft(why_it_matters=why, actions=actions))
    assert "role" in checks_failed(report)
    assert any("действия" in i.message for i in report.issues)


def test_data_with_inference():
    why = good_draft().why_it_matters
    why[0] = DraftStatement(
        text="У компании кредит, поэтому расходы вырастут.", origin="data", refs=["feat:CL_PRODUCT_LOA_MARK"]
    )
    assert any("вывод" in i.message for i in run(good_draft(why_it_matters=why)).issues)


def test_bank_position_only_in_bank_block():
    risks = [*good_draft().risks, bank()]
    report = run(good_draft(risks=risks))
    assert ("risks", 2) in report.hard_at()


def test_bank_view_missing_when_analytics_exists():
    report = run(good_draft(bank_view=[]))
    assert "bank_quotes" in checks_failed(report)
    assert not report.hard_at()


def test_no_bank_view_without_analytics_is_fine():
    report = run(good_draft(bank_view=[]), analytics=[])
    assert report.ok, report.summary()


def test_retelling_without_company_link():
    draft = good_draft(why_it_matters=[], risks=[], opportunities=[])
    failed = checks_failed(run(draft))
    assert {"not_retelling", "multi_factor"} <= failed


@pytest.mark.parametrize(
    ("quote", "text", "found"),
    [
        ("«пауза» сохранится", 'Банк: "пауза" сохранится до конца года', True),
        ("ставку  на\nуровне 14%", "сохранил ставку на уровне 14% годовых", True),
        ("коротко", "коротко и ясно", False),  # слишком короткая выдержка ничего не доказывает
        ("ставка снижена", "ставка сохранена", False),
    ],
)
def test_quote_matching(quote, text, found):
    assert quote_in(quote, text) is found


def test_normalize_hyphenation():
    assert normalize("пресс-\nрелиз") == "прессрелиз"


def test_superseded_bank_forecast_is_caught():
    # банк 05.08 ждал 13,5 %, 11.09 пересмотрел на 14,0 % — старое нельзя подавать как текущий прогноз
    old_page = "src:alfa:consumption-2026-08#p2"
    text = "Мы ожидаем ещё двух снижений ключевой ставки и уровня 13,5% на конец 2026 г."
    old = AnalyticsHit(
        source=Source(
            id=old_page + "-3", kind="alfa_analytics", title="Потребление на пике", page=2, fragment=text
        ),
        page_ref=old_page,
        material_date=dt.date(2026, 8, 5),
    )
    ctx = dict(analytics=[*make_ctx().analytics, old], page_texts={PAGE: BANK_PAGE, old_page: text})
    stale = bank(
        text="Альфа-Банк ждёт снижения ставки до 13,5% на конец 2026 года.",
        refs=[old_page + "-3"],
        quote="двух снижений ключевой ставки и уровня 13,5% на конец 2026",
    )
    report = run(good_draft(bank_view=[bank(), stale]), **ctx)
    assert any(i.check == "fresh_forecast" and i.hard for i in report.issues)
    # то же как история — можно
    history = stale.model_copy(update={"text": "Раньше, 05.08.2026, банк ждал 13,5% на конец 2026 года."})
    assert run(good_draft(bank_view=[bank(), history]), **ctx).ok


@pytest.mark.parametrize(
    ("text", "flagged"),
    [
        ("Процентные расходы вырастут на 50 млн ₽ в год.", True),
        ("Потери могут составить 7 миллиардов рублей.", True),
        ("Курс доллара опустился ниже 81 руб.", False),
        ("Банк ждёт 87,2 ₽/$ на конец 2026 года.", False),
        ("Курс может дойти до 87 руб., а долг вырастет на 2 млрд ₽.", True),
    ],
)
def test_money_vs_exchange_rate(text, flagged):
    from api.agent.numbers import money_in

    assert bool(money_in(text)) is flagged
