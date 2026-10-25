import datetime as dt

from test_takeaway import item

from api.bankview import bank_view, outdated_note, statement
from api.contract import ScoreTerm, Source
from api.ranking import MSK, NewsEvent
from api.week import BACKGROUND, build_stories, dynamics, main_action, story_key, topic_counts, week_days

NOW = dt.datetime(2026, 10, 25, 12, tzinfo=MSK)
DAYS = week_days(NOW)


def event(eid, day, factors=(), sectors=()):
    return NewsEvent(
        id=f"src:news:{eid}",
        title=eid,
        published_at=dt.datetime.combine(DAYS[day], dt.time(10), tzinfo=MSK),
        factors=[(c, s, c) for c, s in factors],
        sectors=list(sectors),
    )


def dated(it, day, eid):
    it.event_id = f"src:news:{eid}"
    it.source = Source(
        id=it.event_id,
        kind="news",
        title=it.event.title,
        published_at=dt.datetime.combine(DAYS[day], dt.time(10), tzinfo=MSK),
    )
    return it


def test_week_days_and_counts():
    assert DAYS[0] == dt.date(2026, 10, 19) and DAYS[-1] == dt.date(2026, 10, 25)
    events = [
        event("a", 4, [("rate", 1.0)]),
        event("b", 4, [("rate", 0.6)]),
        event("c", 5, [("rate", 0.3)]),  # слабая метка — не в счётчике
        event("d", 6, [("commodity_oil_gas", 0.8)]),  # код разметки → код карты через aliases
        event("e", 6, sectors=[("56", 0.7)]),
    ]
    aliases = {"commodity_oil_gas": "commodity_oil"}
    assert topic_counts(events, "rate", DAYS, aliases) == [0, 0, 0, 0, 2, 0, 0]
    assert topic_counts(events, "commodity_oil", DAYS, aliases) == [0, 0, 0, 0, 0, 0, 1]
    assert topic_counts(events, "industry:56", DAYS, aliases) == [0, 0, 0, 0, 0, 0, 1]


def test_dynamics():
    assert dynamics([0, 0, 0, 0, 0, 1, 2]) == "appeared"
    assert dynamics([3, 4, 2, 1, 0, 0, 0]) == "faded"
    assert dynamics([0, 1, 1, 0, 5, 3, 1]) == "grew"


def test_story_key_is_what_the_news_is_about():
    # «ЦБ не спешит»: слагаемое топлива больше, но новость — о ставке (метка 1,0 против 0,7)
    it = item(0.6, code="commodity_oil", reason="Сырьё", exposure=0.8)
    it.relevance.breakdown = [
        ScoreTerm(
            kind="factor", code="commodity_oil", label="Сырьё", value=0.3, event_strength=0.7, exposure=0.8
        ),
        ScoreTerm(kind="factor", code="rate", label="Ставка", value=0.2, event_strength=1.0, exposure=0.4),
    ]
    assert story_key(it) == "rate"
    chain = item(0.5, code="chain:buyers:56", kind="chain")
    assert story_key(chain) == "industry:56"


def test_stories_group_by_topic_with_peak_and_limits():
    from api.takeaway import takeaways

    items = [
        dated(item(0.6, title="ЦБ сохранил ставку 14 %"), 4, "r1"),
        dated(item(0.45, title="Ставка: пауза затянется"), 2, "r2"),
        dated(item(0.5, code="fx", title="Рубль крепнет"), 3, "f1"),
        dated(item(0.4, code="region", title="Пожар на складе"), 5, "g1"),
        dated(item(0.2, code="labor", title="Зарплаты растут"), 6, "l1"),
    ]
    takeaways(items, "cfo")
    events = [
        event("r1", 4, [("rate", 1.0)]),
        event("r2", 2, [("rate", 1.0)]),
        event("x", 4, [("rate", 0.9)]),
    ]
    stories = build_stories(items, events, DAYS, {})
    codes = [s.code for s in stories]
    assert codes[:2] == ["rate", "fx"] and "region" not in codes and "region" in BACKGROUND
    rate = stories[0]
    assert rate.event_ids == ["src:news:r1", "src:news:r2"]  # главное — первым
    assert rate.daily_counts == [0, 0, 1, 0, 2, 0, 0] and rate.news_count == 3
    assert rate.peak.date == DAYS[4] and rate.peak.event_id == "src:news:r1"
    assert rate.title == "ЦБ сохранил ставку 14 %" and rate.takeaway.text.startswith("Ставка 14,0 %")
    # меньше трёх важных — добираем «к сведению», но не больше пяти всего
    assert len(stories) == 3 and stories[2].level == "info"
    action = main_action(stories)
    assert (action.code, action.label) == ("rate", "Обсудить структуру долга с менеджером")


class Fragment:
    def __init__(self, text, date, fid="src:alfa:m#p1"):
        self.id, self.title, self.publisher = fid, "Ключевая ставка ЦБ РФ", "Альфа-Банк"
        self.text, self.fragment = text, None
        self.published_at = dt.datetime.combine(date, dt.time(), tzinfo=MSK)


def test_bank_statement_prefers_forecast_and_skips_tables():
    text = "\n".join(
        [
            "Итоги недели",
            "Динамика | 2025 | 2026",
            "ЦБ сохранил ставку 14,0%. Мы ожидаем ставку 14,0% до конца года.",
        ]
    )
    assert statement(text, ("ставк",)) == "Мы ожидаем ставку 14,0% до конца года."
    assert statement("Рынок облигаций вырос на 2%.", ("ставк",)) is None  # о теме — ничего


def test_bank_view_outdated_only_on_same_subject():
    assert outdated_note("Мы ждём Urals $63 в 2026 году", "ЦБ повысил прогноз Urals до $72") == (
        "банк ждал Urals $63, в новостях — $72"
    )
    assert outdated_note("Мы ожидаем ставку 14,0% до конца года", "ЦБ сохранил ставку 14%") is None
    assert outdated_note("Мы ждём Urals $63", "Курс доллара ниже 81 рубля") is None

    def fragments(codes, query):
        return [Fragment("Мы ожидаем Urals $63 в 2026 году.", dt.date(2026, 7, 31))]

    bank = bank_view("commodity_oil", fragments, "ЦБ повысил прогноз Urals до $72", dt.date(2026, 10, 23))
    assert (
        bank.outdated
        and bank.date == dt.date(2026, 7, 31)
        and bank.text == "Мы ожидаем Urals $63 в 2026 году."
    )
    assert bank_view("commodity_oil", None) is None
    assert bank_view("supply_45", fragments) is None  # темы нет в справочнике — позиции нет


def test_dynamics_edges():
    assert dynamics([2, 2, 2, 2, 2, 2, 2]) == "steady"  # ровный поток — не «утих»
    assert dynamics([0, 0, 0, 0, 0, 0, 0]) == "steady"
    assert dynamics([1, 1, 1, 1, 2, 2, 2]) == "grew"
    assert dynamics([3, 3, 3, 3, 1, 1, 1]) == "faded"


def test_region_event_with_real_factor_goes_to_that_story():
    it = item(0.5, code="region")
    it.relevance.breakdown = [
        ScoreTerm(kind="factor", code="region", label="Регион", value=0.3, event_strength=1.0, exposure=0.2),
        ScoreTerm(kind="factor", code="rate", label="Ставка", value=0.2, event_strength=0.5, exposure=0.7),
    ]
    assert story_key(it) == "rate"


def test_peak_day_without_story_event_takes_the_days_news():
    from api.takeaway import takeaways

    items = [dated(item(0.6, title="ЦБ сохранил ставку 14 %"), 2, "r1")]
    takeaways(items, "cfo")
    events = [event("r1", 2, [("rate", 1.0)])] + [event(f"x{i}", 5, [("rate", 0.9)]) for i in range(3)]
    story = build_stories(items, events, DAYS, {})[0]
    assert story.peak.date == DAYS[5] and story.peak.event_id.startswith(
        "src:news:x"
    )  # дата и «что» — один день


def test_outdated_ignores_other_rates_and_changes():
    assert outdated_note("Мы ожидаем ключевую ставку 14,0% до конца года", "Снижение ставки на 1%") is None
    assert outdated_note("Мы ожидаем ключевую ставку 14,0% до конца года", "Ставка НДС 20%") is None
    assert outdated_note("Мы ждём Urals $63", "Urals подешевела на 3%") is None
    assert outdated_note("Мы ожидаем ключевую ставку до 14,0%", "ЦБ снизил ключевую ставку до 12,0%") == (
        "банк ждал ставку 14 %, в новостях — 12 %"
    )


def test_statement_needs_a_measure_not_a_year():
    assert statement("Курс рубля в 2026 году будет волатильным.", ("курс",)) is None
    assert statement("Наш прогноз по курсу — 87 руб./$ на конец года.", ("курс",)) == (
        "Наш прогноз по курсу — 87 руб./$ на конец года."
    )
