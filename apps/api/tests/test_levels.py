from test_takeaway import item

from api.contract import Feed
from api.levels import EventLevels
from api.takeaway import takeaways


def feed(*items):
    takeaways(list(items), "cfo")
    return Feed(
        persona_id="p-u1-cfo", company_id="U_1", role="cfo", items=list(items), candidates=1, news_source="t"
    )


def test_level_shown_once_stays_on_every_screen():
    levels = EventLevels()
    day = levels.pin(feed(item(0.6)), None)
    assert day.items[0].takeaway.level == "act"
    # та же новость в неделе: модель оценила её в другой пачке ниже — уровень и текст остаются «действовать»
    week = levels.pin(feed(item(0.35)), None)
    assert week.items[0].takeaway.level == "act" and "Что делать" in week.items[0].takeaway.text
    assert levels.get("p-u1-cfo", day.items[0].event_id) == "act"
    assert levels.get("p-u2-cfo", day.items[0].event_id) is None  # у другого пользователя — свой уровень


def test_search_follows_but_does_not_set_levels():
    levels = EventLevels()
    levels.pin(feed(item(0.1)), None, remember=False)
    assert levels.get("p-u1-cfo", item(0.1).event_id) is None
    assert levels.pin(feed(item(0.6)), None).items[0].takeaway.level == "act"


def test_level_expires():
    levels = EventLevels(ttl=-1)
    levels.pin(feed(item(0.6)), None)
    assert levels.get("p-u1-cfo", item(0.6).event_id) is None
