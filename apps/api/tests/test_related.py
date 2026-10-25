import datetime as dt

from test_takeaway import item

from api.contract import Source, Takeaway
from api.ranking import MSK
from api.related import related, stems

NOW = dt.datetime(2026, 10, 26, 12, tzinfo=MSK)


def it(title, code="rate", day=0, eid=None, strength=1.0):
    x = item(0.5, code=code, title=title)
    x.event_id = f"src:news:{eid or title}"
    x.relevance.breakdown[0].event_strength = strength
    x.source = Source(id=x.event_id, kind="news", title=title, published_at=NOW - dt.timedelta(days=day))
    x.takeaway = Takeaway(level="watch", text="t")
    return x


def test_same_story_factor_and_title_fresh_first_without_reprints():
    target = it("ЦБ сохранил ключевую ставку 16 %", eid="t")
    pool = [
        target,
        it("Ставка ЦБ: аналитики ждут снижения в декабре", day=3, eid="a"),
        it("ЦБ сохранил ключевую ставку на уровне 16 %", day=0, eid="dup"),  # перепечатка открытой
        it("Банки подняли ставки по вкладам", day=1, eid="b"),
        it("Минфин разместил ОФЗ", day=2, eid="c"),
        it("Нефть Brent подорожала до $80", code="commodity_oil", day=0, eid="oil"),
    ]
    found = [i.event_id for i in related(target, pool)]
    assert "src:news:t" not in found and "src:news:dup" not in found and "src:news:oil" not in found
    assert found[:3] == ["src:news:b", "src:news:c", "src:news:a"]  # свежие выше


def test_reprints_among_related_are_shown_once_and_six_at_most():
    target = it("Курс доллара упал ниже 80 рублей", code="fx", eid="t")
    pool = [
        it(f"Рубль укрепился: доллар по {80 - n} рублей", code="fx", day=n, eid=f"r{n}") for n in range(10)
    ]
    pool += [it("Рубль укрепился: доллар по 79 рублей", code="fx", day=0, eid="copy")]
    found = related(target, pool)
    assert 0 < len(found) <= 6
    titles = [stems(i.event.title) for i in found]
    assert len({frozenset(t) for t in titles}) == len(titles)
