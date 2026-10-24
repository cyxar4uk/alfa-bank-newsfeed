from api.contract import FeedItem, FeedRelevance, InsightEvent, ScoreTerm, Source
from api.takeaway import TEXT_MAX, takeaway

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
):
    terms = [ScoreTerm(kind=kind, code=code, label=reason, value=score, exposure=exposure), *extra]
    return FeedItem(
        event_id="src:news:x",
        event=InsightEvent(title="ЦБ сохранил ставку"),
        relevance=FeedRelevance(score=score, reason=reason, breakdown=terms, freshness=1, source_quality=1),
        has_bank_view=True,
        source=Source(id="src:news:x", kind="news", title="ЦБ сохранил ставку"),
        channel="direct",
        channel_text=channel_text,
        short=short,
    )


def test_levels_answer_important_why_and_what_to_do():
    act = takeaway(
        item(0.6, short="Стоимость долга: собственный кредит в банке, кредиты у 11 компаний группы"), "cfo"
    )
    assert act.level == "act"
    assert act.text == (
        "Касается вас: собственный кредит в банке, кредиты у 11 компаний группы."
        " Проверьте, когда пересматриваются ставки по кредитам и лизингу."
    )
    watch = takeaway(item(0.4), "cfo")
    assert watch.level == "watch" and watch.text.startswith(
        "Может задеть: собственный кредит в банке. Следите"
    )
    info = takeaway(item(0.1), "cfo")
    assert (info.level, info.text) == (
        "info",
        "Слабо касается вас: собственный кредит в банке. Действий не нужно.",
    )


def test_role_changes_action():
    acc = takeaway(item(0.6), "chief_accountant")
    assert acc.text.endswith("Проверьте расчёт процентов и резервов в отчётности.")


def test_weak_exposure_or_abroad_is_at_most_watch():
    assert takeaway(item(0.7, exposure=0.2), "cfo").level == "watch"
    abroad = item(0.7, reason="Налоги: изменения налогов (событие за рубежом: США)", code="tax_regulation")
    assert takeaway(abroad, "chief_accountant").level == "watch"


def test_model_view_limits_level():
    llm = ScoreTerm(
        kind="llm",
        code="llm:event",
        label="оценка модели: не задевает — речь о буровом оборудовании",
        value=-0.2,
    )
    no = takeaway(item(0.6, extra=[llm]), "cfo")
    assert (no.level, no.text) == ("info", "Скорее не касается вас: речь о буровом оборудовании.")
    weak = ScoreTerm(kind="llm", code="llm:rate", label="оценка модели: слабо — косвенно", value=-0.1)
    assert takeaway(item(0.6, extra=[weak]), "cfo").level == "watch"


def test_chain_reason_and_cleanup():
    buyers = item(
        0.55,
        code="chain:buyers:56",
        kind="chain",
        exposure=0.53,
        channel_text="событие → общепит (56) → ваши покупатели: 469 компаний, 53 % поступлений → вы",
    )
    assert takeaway(buyers, "ceo").text == (
        "Касается вас: ваши покупатели из отрасли «общепит»: 469 компаний, 53 % поступлений."
        " Проверьте спрос и сроки оплаты у крупных покупателей."
    )
    buyers.short = "Через покупателей: общепит — 53 % поступлений"
    assert takeaway(buyers, "ceo").text.startswith(
        "Касается вас: через покупателей: общепит — 53 % поступлений."
    )


def test_text_is_short_and_without_technical_words():
    long = item(0.6, short=None, channel_text="очень длинное объяснение " * 20)
    for role in ("cfo", "owner", "ceo", "chief_accountant", "treasury", "other"):
        t = takeaway(long, role).text
        assert len(t) <= TEXT_MAX
        assert not any(w in t.casefold() for w in TECH), t


def test_own_industry_chain_reads_naturally():
    own = item(
        0.55, code="chain:direct:56", kind="chain", channel_text="событие → общепит (56) → своя отрасль → вы"
    )
    assert takeaway(own, "ceo").text.startswith("Касается вас: ваша отрасль «общепит». Оцените")
