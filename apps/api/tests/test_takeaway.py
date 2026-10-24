from api.contract import (
    Evidence,
    ExposureChannel,
    ExposureMap,
    FactorExposure,
    FeedItem,
    FeedRelevance,
    GroupImpact,
    InsightEvent,
    ScoreTerm,
    Source,
)
from api.takeaway import TEXT_MAX, takeaway, takeaways

TECH = ("фактор", "канал", "карт", "оценк", "скор", "модел")


def item(
    score,
    code="rate",
    kind="factor",
    exposure=0.7,
    short=None,
    channel_text="собственный кредит в банке",
    reason="Стоимость заёмных денег: собственный кредит в банке",
    extra=(),
    title="ЦБ сохранил ставку 14 %",
):
    terms = [ScoreTerm(kind=kind, code=code, label=reason, value=score, exposure=exposure), *extra]
    return FeedItem(
        event_id=f"src:news:{title}",
        event=InsightEvent(title=title),
        relevance=FeedRelevance(score=score, reason=reason, breakdown=terms, freshness=1, source_quality=1),
        has_bank_view=True,
        source=Source(id="src:news:x", kind="news", title=title),
        channel="direct",
        channel_text=channel_text,
        short=short,
    )


def exposure_map():
    rate = FactorExposure(
        id="exp:rate",
        code="rate",
        label="Стоимость заёмных денег",
        strength=0.4,
        level="medium",
        evidence=[
            Evidence(ref="feat:LEASING", label="Лизинг в банке", value="да"),
            Evidence(ref="group", label="Кредиты в банке у других компаний группы", value="3 из 368"),
        ],
    )
    return ExposureMap(company_id="U_1", factors=[rate], catalog_version="t", levels=[])


def test_act_has_event_number_and_action():
    short = "Стоимость долга: собственный кредит в банке, кредиты у 11 компаний группы"
    act = takeaway(item(0.6, short=short), "cfo")
    assert act.level == "act"
    assert act.text == (
        "Ставка 14,0 % продержится дольше — долг дороже: собственный кредит в банке, кредиты у 11 компаний"
        " группы. Что делать: сверьте сроки пересмотра ставок."
    )


def test_number_from_company_data_when_no_short_line():
    text = takeaway(item(0.6), "cfo", exposure_map()).text
    assert "кредиты у 3 из 368 компаний группы" in text


def test_group_number_for_owner():
    it = item(0.6, title="ЦБ не спешит")
    it.group_impact = GroupImpact(
        group_id="g",
        companies_total=369,
        affected_count=178,
        major_count=17,
        affected_revenue=149.04e9,
        affected_revenue_bn=149.04,
        affected_share=0.76,
        affected=[],
        intra_payments=0,
        intra_share=0,
        text="",
        refs=[],
    )
    # в заголовке «ЦБ не спешит» направления нет — так и сказано, число и действие на месте
    assert takeaway(it, "owner", exposure_map()).text == (
        "ЦБ не спешит — направление пока неясно. 178 компаний группы с выручкой 149 млрд ₽"
        " зависят от кредитов. Что делать: сверьте сроки пересмотра ставок."
    )
    it.event.title = "ЦБ не спешит // Пауза в снижении ключевой ставки может затянуться"
    assert takeaway(it, "owner", exposure_map()).text.startswith(
        "Ставка продержится дольше — долг группы дороже: 178 компаний группы с выручкой 149 млрд ₽"
    )


def test_consequence_direction_and_side():
    from api.consequence import consequence

    def cons(title, key, channel=""):
        exposure = exposure_map()
        exposure.factors[0].code = key
        exposure.factors[0].channel = ExposureChannel(kind="direct", text=channel)
        return consequence(item(0.6, title=title), key, exposure)

    assert cons("ЦБ сохранил ставку 14,00%", "rate") == "Ставка 14,0 % продержится дольше — долг дороже"
    assert cons("ЦБ снизил ключевую ставку", "rate") == "Ставка снижается — долг подешевеет"
    oil_up = "Цена Brent обновила полугодовой максимум"
    assert (
        cons(oil_up, "commodity_oil", "своя отрасль — нефть, газ и топливо")
        == "Нефть дорожает — выручка от топлива выше"
    )
    assert (
        cons(oil_up, "commodity_oil", "перевозки: топливо в себестоимости")
        == "Нефть дорожает — топливо для вас дороже"
    )
    assert cons("Курс доллара опустился ниже 81 рубля", "fx", "ВЭД: Китай; направление — импорт") == (
        "Рубль крепче — импорт дешевле"
    )
    # направление не определить — не гадаем
    assert cons("Новак заявил о готовности экспортировать дизель", "commodity_oil") is None
    assert cons("Курс доллара. Прогноз на неделю", "fx", "экспорт") is None


def test_unclear_direction_is_said_honestly():
    it = item(0.6, title="Новак заявил о готовности экспортировать дизель", code="commodity_oil")
    text = takeaway(it, "ceo", exposure_map()).text
    assert "направление пока неясно" in text


def test_role_changes_action():
    assert "расчёт процентов и резервов" in takeaway(item(0.6), "chief_accountant").text


def test_watch_and_info():
    assert takeaway(item(0.4), "cfo").level == "watch"
    info = takeaway(item(0.1), "cfo")
    assert info.level == "info" and info.text.endswith("Действий не нужно.")
    assert takeaway(item(0.7, exposure=0.2), "cfo").level == "watch"  # слабая зависимость


def test_model_view_and_its_factor():
    label = "оценка модели: не задевает — речь о буровом оборудовании"
    no = ScoreTerm(kind="llm", code="llm:event", label=label, value=-0.2)
    assert (
        takeaway(item(0.6, extra=[no]), "cfo").text == "Скорее не касается вас: речь о буровом оборудовании."
    )
    # модель назвала главным фактор ставки, хотя первым шло сырьё: действие — по ставке
    oil = ScoreTerm(kind="factor", code="commodity_oil", label="Сырьё", value=0.3, exposure=0.8)
    rate = ScoreTerm(kind="factor", code="rate", label="Ставка", value=0.2, exposure=0.4)
    llm = ScoreTerm(kind="llm", code="llm:rate", label="оценка модели: заметно — ставка", value=0.05)
    it = item(0.6)
    it.relevance.breakdown = [oil, rate, llm]
    assert "ставки по кредитам" in takeaway(it, "cfo").text


def test_no_identical_texts_in_a_row():
    a, b = item(0.6, title="ЦБ не спешит"), item(0.6, title="ЦБ не спешит")
    b.event_id = "src:news:other"
    takeaways([a, b], "cfo")
    assert a.takeaway.text != b.takeaway.text


def test_unrelated_search_hit():
    it = item(0)
    it.relevance.breakdown = []
    assert takeaway(it, "cfo").text == "Напрямую вас не касается. Действий не нужно."


def test_text_is_short_and_without_technical_words():
    long = item(0.6, channel_text="очень длинное объяснение " * 20, title="Очень длинный заголовок " * 6)
    for role in ("cfo", "owner", "ceo", "chief_accountant", "treasury", "other"):
        t = takeaway(long, role, exposure_map()).text
        assert len(t) <= TEXT_MAX
        assert not any(w in t.casefold() for w in TECH), t


def test_facts_skip_okved_lists_and_shorten_group_lines():
    from api.takeaway import facts

    exposure = exposure_map()
    exposure.factors[0].evidence = [
        Evidence(ref="feat:MAINOKVED_CODE", label="Основная деятельность", value="45.31.1 Торговля оптовая"),
        Evidence(ref="group", label="Компании группы с ОКВЭД 41, 42, 35", value="41, 42, 35"),
        Evidence(
            ref="group",
            label="Компании группы с ОКВЭД 41, 42, 35",
            value="48 компаний, 116,8 млрд ₽ — 59 % выручки группы без самой компании; крупнейшие: U_4909",
        ),
    ]
    # «48 компаний отрасли в группе» — не охват события: число задетых компаний даёт только api.coverage
    assert facts(item(0.6), "rate", exposure) == []
    text = takeaway(
        item(0.6, title="ЦБ сохранил ключевую ставку на уровне 14 % годовых и дал сигнал"), "cfo", exposure
    )
    assert "48 компаний" not in text.text and len(text.text) <= TEXT_MAX


def test_consequence_does_not_flip_meaning():
    from api.consequence import consequence

    def cons(title, key, channel=""):
        exposure = exposure_map()
        exposure.factors[0].code = key
        exposure.factors[0].channel = ExposureChannel(kind="direct", text=channel)
        return consequence(item(0.6, title=title), key, exposure)

    pause = "ЦБ не спешит // Пауза в снижении ключевой ставки может затянуться"
    assert cons(pause, "rate") == "Ставка продержится дольше — долг дороже"
    assert cons("ЦБ снизил ставку, сохранив жесткий сигнал", "rate") == "Ставка снижается — долг подешевеет"
    assert cons("ЦБ не повысил ставку", "rate") == "Ставка не меняется — долг остаётся дорогим"
    assert cons("Инфляция 9,5 %: ЦБ сохранил ставку 16 %", "rate").startswith("Ставка 16,0 %")
    # без предмета рядом с глаголом и при неясной стороне — не гадаем
    assert cons("Инфляция замедлилась, ЦБ обсудит ставку", "rate") is None
    assert cons("ОПЕК+ сократит добычу нефти", "commodity_oil", "своя отрасль — нефть") is None
    assert cons("Цена Brent обновила максимум", "commodity_oil", "") is None
    assert cons("Ростех подписал контракт", "gov") is None
    assert cons("Рубль не смог укрепиться", "fx", "импорт") is None
    assert cons("Курс доллара вырос", "fx", "ВЭД: экспорт и импорт") is None
    assert (
        cons("Минпромторг предложил ввести утильсбор", "tax_regulation")
        == "Налоги и пошлины растут — нагрузка выше"
    )
