"""Замечания «живых пользователей» 25.10 (P0): тема цитаты банка, даты, профиль, шаги, резюме трассы."""

import datetime as dt

from agent_fakes import (
    FRAGMENT,
    GOOD_PLAN,
    PERSONA,
    DraftVerdict,
    FactorTag,
    bank,
    good_draft,
    make_event,
    reply,
)
from test_agent_checks import make_ctx
from test_agent_loop import make_agent

from api.agent.checks import Checker, own_goods
from api.agent.drafts import DraftAction, DraftStatement
from api.agent.ports import ExposureFactor
from api.agent.topics import contradicts_ved, event_topics, on_topic, past_as_future, ved_direction

TODAY = dt.date(2026, 10, 26)


def oil_event():
    event = make_event(factors=[FactorTag(code="commodity_oil", strength=0.9)])
    event.source.title = "Бензин на АЗС может подорожать из-за затрат на импорт топлива"
    return event


# --- 1. позиция банка — по теме события -----------------------------------------------------------------


def test_event_topics_from_factors_and_title():
    assert "oil" in event_topics(oil_event())
    assert "rate" in event_topics(make_event())


def test_rate_quote_is_off_topic_for_oil_event():
    rate_quote = "теперь мы ожидаем ее сохранения на текущем значении 14,0% до конца года"
    assert not on_topic(f"Альфа-Банк ожидает ставку 14,0% до конца года. {rate_quote}", {"oil"})
    assert on_topic("Альфа-Банк ждёт курс 87 руб./$ на конец года", {"fx"})
    assert on_topic("Альфа-Банк ожидает ставку 14,0%", {"deposit"})  # ставка отвечает и на доходность


def test_off_topic_bank_view_is_a_hard_issue():
    ctx = make_ctx(event=oil_event())
    report = Checker(ctx).run(good_draft(bank_view=[bank()], bank_position=None))
    assert ("bank_view", 0) in report.hard_at()
    assert any(i.check == "on_topic" for i in report.issues)


def test_no_topical_bank_material_means_no_position_not_unconfirmed():
    agent, _ = make_agent(reply(GOOD_PLAN), *[reply(good_draft(bank_view=[], bank_position=None))] * 3)
    insight = agent.run(PERSONA, oil_event()).insight
    assert insight.bank_position.found is False
    assert "не публиковал" in insight.bank_position.statement


# --- 2. даты ------------------------------------------------------------------------------------------


def test_past_dates_as_future_are_caught():
    assert past_as_future("Следите за заседанием ЦБ 23 октября", TODAY) == ["23 октября"]
    assert past_as_future("Минфин представит бюджет в конце сентября", TODAY)
    assert past_as_future("Ждите решения 11.09.2026", TODAY)
    assert past_as_future("Следите за заседанием 19 декабря", TODAY) == []  # впереди
    assert past_as_future("ЦБ 23 октября сохранил ставку", TODAY) == []  # факт о прошлом


def test_stale_watch_statement_is_a_hard_issue():
    ctx = make_ctx()
    ctx.today = TODAY
    stale = DraftStatement(
        text="Следите за заседанием ЦБ 23 октября: банк ждёт паузы.",
        origin="ai",
        refs=["feat:CL_PRODUCT_LOA_MARK"],
        factor="rate",
    )
    report = Checker(ctx).run(good_draft(watch=[stale]))
    assert ("watch", 0) in report.hard_at() and any(i.check == "fresh_dates" for i in report.issues)


def test_context_tells_the_model_today():
    ctx = make_ctx()
    ctx.today = TODAY
    assert "СЕГОДНЯ: 26.10.2026" in ctx.render_event()


# --- 4. профиль: направление ВЭД -------------------------------------------------------------------------


def exporter():
    return [
        ExposureFactor(
            code="fx",
            label="Курс валют",
            level="high",
            channel_text="ВЭД: ОАЭ, Алжир, Индия; направление — экспорт (оценка по отрасли)",
        )
    ]


def test_ved_direction_and_contradiction():
    assert ved_direction(exporter()) == "export"
    assert contradicts_ved("Ваш импорт запчастей, техники и упаковки подорожает", "export")
    assert contradicts_ved("Экспортная выручка вырастет при слабом рубле", "export") is None


def test_import_claim_for_exporter_is_a_hard_issue():
    ctx = make_ctx(exposure=exporter())
    wrong = DraftStatement(
        text="Ваш импорт запчастей, техники и упаковки подорожает при слабом рубле.",
        origin="ai",
        refs=["feat:CL_PRODUCT_LOA_MARK"],
        factor="fx",
    )
    report = Checker(ctx).run(good_draft(risks=[wrong, *good_draft().risks]))
    assert ("risks", 0) in report.hard_at() and any(i.check == "fits_profile" for i in report.issues)


# --- 5. шаги под роль, с адресатом и сроком --------------------------------------------------------------


def test_step_addressed_to_own_role_is_caught():
    treasurer = PERSONA.model_copy(update={"role": "treasury", "role_label": "Казначей"})
    ctx = make_ctx(persona=treasurer)
    action = DraftAction(text="Уточните у казначейства график платежей", kind="question")
    report = Checker(ctx).run(good_draft(actions=[action]))
    assert ("actions", 0) in report.hard_at() and any(i.check == "action_owner" for i in report.issues)


def test_asking_suppliers_about_own_goods_is_caught():
    goods = own_goods("Компания №57706 · торговля оптовая твердым, жидким и газообразным топливом")
    assert "топли" in goods
    ctx = make_ctx()
    ctx.profile = ctx.profile.model_copy(
        update={"display_name": "Компания №57706 · торговля оптовая твердым, жидким и газообразным топливом"}
    )
    action = DraftAction(text="Уточните у поставщиков топлива цены на I квартал", kind="question")
    assert ("actions", 0) in Checker(ctx).run(good_draft(actions=[action])).hard_at()


def test_verdict_steps_need_owner_and_due():
    v = DraftVerdict(
        level="act",
        headline="Для вас важно: кредит не подешевеет",
        why="Ставка осталась 14% — процентные расходы не снизятся.",
        actions=["Проверьте долг по плавающей ставке"],
    )
    issues = Checker(make_ctx()).run(good_draft(verdict=v)).issues
    assert any(i.check == "action_owner" and not i.hard for i in issues)


def test_treasurer_on_rate_needs_debt_and_placement():
    treasurer = PERSONA.model_copy(update={"role": "treasury", "role_label": "Казначей"})
    ctx = make_ctx(persona=treasurer)
    only_debt = [DraftAction(text="Пересчитайте график процентов по долгу", kind="scenario")]
    report = Checker(ctx).run(good_draft(actions=only_debt))
    assert any("доходность размещения" in i.message for i in report.issues)
    both = [*only_debt, DraftAction(text="Сравните доходность депозитов на 3 и 6 месяцев", kind="scenario")]
    assert not any(
        "доходность размещения" in i.message for i in Checker(ctx).run(good_draft(actions=both)).issues
    )


def test_card_carries_step_owner_and_due():
    agent, _ = make_agent(reply(GOOD_PLAN), reply(good_draft()))
    insight = agent.run(PERSONA, make_event()).insight
    step = insight.verdict.steps[0]
    assert step.owner == "финансовой службе" and step.due == "на неделе"
    assert insight.verdict.actions == [s.text for s in insight.verdict.steps]


# --- 7. резюме трассы ------------------------------------------------------------------------------------


def test_trace_has_human_summary_and_no_company_ids_in_refs():
    agent, _ = make_agent(reply(GOOD_PLAN), reply(good_draft()))
    result = agent.run(PERSONA, make_event())
    summary = result.trace.summary
    assert summary.verdict.startswith("Самопроверка:") and summary.checked
    assert any("Материалы Альфа-Банка" in c for c in summary.checked)
    refs = [r for s in result.trace.steps for r in s.output_refs]
    assert refs and all(r.startswith(("src:", "feat:")) for r in refs)


def test_trace_summary_explains_failed_checks():
    from api.agent.checks import Issue, Report
    from api.agent.loop import _trace_summary

    report = Report(issues=[Issue("on_topic", "x", "bank_view", 0, True)])
    summary = _trace_summary(make_ctx(), report, dropped=1)
    assert "позиция банка была не по теме события" in summary.problems
    assert "пройдено" in summary.verdict and "on_topic" not in summary.verdict
    assert FRAGMENT  # фикстура аналитики на месте


def test_own_goods_without_company_number():
    assert "топли" in own_goods("Торговля оптовая твердым, жидким и газообразным топливом")


def test_dates_review_cases():
    # дата без года, которая уже «прошла» в этом году, — это следующий год
    assert past_as_future("Подготовьте платёжный календарь к 15 января", TODAY) == []
    assert past_as_future("В начале февраля вступит в силу закон", TODAY) == []
    # дата материала банка и описание прошлого — не ошибка
    assert past_as_future("Альфа-Банк ожидает ставку 15 % к концу года (материал от 31.07.2026)", TODAY) == []
    assert past_as_future("До 23 октября было 17 %, теперь 16,5 %", TODAY) == []
    # слово будущего в другом предложении не делает прошлую дату будущей
    assert past_as_future("ЦБ 24 октября снизил ставку. Следите за инфляцией.", TODAY) == []
    assert past_as_future("Следите за заседанием ЦБ 23 октября", TODAY) == ["23 октября"]


def test_topics_review_cases():
    from api.agent.topics import text_topics

    assert "fx" not in text_topics("выручка 5 млрд рублей")
    assert "fx" in text_topics("курс рубля к доллару ослаб до 87")
    assert "tax" not in text_topics("сбор урожая")
    assert "metals" not in text_topics("цены стали расти")
    assert "rate" not in text_topics("ставка НДПИ вырастет") and "tax" in text_topics("ставка НДПИ вырастет")


def test_self_department_review_cases():
    cfo_ctx = make_ctx()
    assert Checker(cfo_ctx).step_problem("Уточните у финансового директора график", None)
    treasurer = PERSONA.model_copy(update={"role": "treasury", "role_label": "Казначей"})
    ctx = make_ctx(persona=treasurer)
    assert Checker(ctx).step_problem("Сверьте с казначейскими счетами остатки", None) is None
    assert Checker(ctx).step_problem("Поручите казначейству пересчёт", None)


def test_empty_draft_is_not_better_than_full_one():
    from api.agent.loop import _badness

    empty = good_draft(what_happened=[], why_it_matters=[], risks=[], actions=[])
    full_with_one_slip = good_draft(watch=[DraftStatement(text="Ставка 99 %.", origin="ai", refs=[])])
    ctx = make_ctx()
    assert _badness(Checker(ctx).run(full_with_one_slip)) < _badness(Checker(ctx).run(empty))


def test_old_fx_forecast_is_allowed_with_its_date():
    from api.agent.forecasts import superseded

    # свежая таблица курса не читается — прогноз 87 ₽/$ от 31.07 можно цитировать с датой
    text = "Альфа-Банк ожидает курс 87 руб./$ на конец года (материал от 31.07.2026)"
    assert superseded(text, "src:alfa:macro-1p26", dt.date(2026, 7, 31)) is None
