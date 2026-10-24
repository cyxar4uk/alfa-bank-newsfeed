from test_takeaway import exposure_map, item

from api.contract import Feed, ScoreTerm
from api.llm import LlmError
from api.takeaway import takeaways
from api.takeaway_llm import COLLAPSED, demote_unrelated, write_top


class FakeLlm:
    def __init__(self, texts=None, error=None):
        self.texts, self.error, self.calls = texts or {}, error, 0

    def model_for(self, step):
        return "google/gemma-4-26b-a4b-it"

    def complete(self, step, messages, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        value = kwargs["schema"](items=[{"event_id": k, "text": v} for k, v in self.texts.items()])
        return type("C", (), {"value": value})()


def feed(*items):
    return Feed(
        persona_id="p-u1-cfo", company_id="U_1", role="cfo", items=list(items), candidates=2, news_source="т"
    )


def test_model_text_replaces_rules_when_numbers_are_real():
    a = item(0.6, title="ЦБ сохранил ставку 14 %")
    takeaways([a], "cfo", exposure_map())
    good = "Ставка 14 % продержится дольше — кредиты у 3 из 368 компаний группы; что делать: сверьте сроки."
    write_top(feed(a), FakeLlm({"E1": good}), exposure_map(), "Финансовый директор")
    assert a.takeaway.text == good and a.takeaway.level == "act"


def test_model_text_with_invented_number_or_jargon_is_rejected():
    a = item(0.6, title="ЦБ сохранил ставку 14 %")
    takeaways([a], "cfo", exposure_map())
    rules = a.takeaway.text
    invented = "Ставка 16 % — долг дороже на 5 млрд ₽; что делать: рефинансируйте."
    write_top(feed(a), FakeLlm({"E1": invented}), exposure_map(), "ФД")
    assert a.takeaway.text == rules
    write_top(feed(a), FakeLlm({"E1": "По карте 3 из 368 компаний; оценка высокая."}), exposure_map(), "ФД")
    assert a.takeaway.text == rules


def test_model_failure_keeps_rules():
    a = item(0.6)
    takeaways([a], "cfo")
    rules = a.takeaway.text
    write_top(feed(a), FakeLlm(error=LlmError("нет")), exposure_map(), "ФД")
    assert a.takeaway.text == rules


def test_unrelated_by_model_goes_to_collapsed_part():
    no = ScoreTerm(kind="llm", code="llm:event", label="оценка модели: не задевает — другое", value=0.0)
    hidden = item(0.5, title="Утильсбор на буровое оборудование", extra=[no])
    shown = item(0.4, title="ЦБ сохранил ставку")
    result = demote_unrelated(feed(hidden, shown))
    assert [i.event.title for i in result.items] == [
        "ЦБ сохранил ставку",
        "Утильсбор на буровое оборудование",
    ]
    assert hidden.relevance.score < COLLAPSED
    assert round(sum(t.value for t in hidden.relevance.breakdown), 4) == hidden.relevance.score


def test_model_duplicates_and_info_items_are_skipped():
    a, b = (
        item(0.6, title="ЦБ сохранил ставку 14 %"),
        item(0.5, title="ЦБ сохранил ставку 14 % — комментарий"),
    )
    b.event_id = "src:news:b"
    low = item(0.1, title="Мелочь 14 %")
    low.event_id = "src:news:low"
    takeaways([a, b, low], "cfo", exposure_map())
    same = "Ставка 14 % — кредиты у 3 из 368 компаний группы; что делать: сверьте сроки."
    llm = FakeLlm({"E1": same, "Е2": same})  # кириллическая «Е» в номере — тоже понимаем
    write_top(feed(a, b, low), llm, exposure_map(), "ФД")
    assert a.takeaway.text == same and b.takeaway.text != same  # одна и та же фраза — только раз
    assert low.takeaway.level == "info" and "14 %" not in low.takeaway.text[:3]


def test_scorer_words_are_allowed_in_plain_russian():
    a = item(0.6, title="ЦБ сохранил ставку 14 %")
    takeaways([a], "cfo", exposure_map())
    plain = "Ставка 14 % скорее продержится — кредиты у 3 из 368 компаний группы; что делать: сверьте сроки."
    write_top(feed(a), FakeLlm({"E1": plain}), exposure_map(), "ФД")
    assert a.takeaway.text == plain
