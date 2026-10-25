import datetime as dt
import types

from test_takeaway import item

from api.agent.loop import insight_id
from api.contract import Feed, Takeaway
from api.llm.budget import BudgetExceeded
from api.precompute import Precompute
from api.ranking import MSK

NOW = dt.datetime(2026, 10, 26, 12, tzinfo=MSK)


class FakeAgent:
    """Очередь агента: insight(wait=False) ставит задачу; finish() — задача собралась за cost ₽."""

    def __init__(self, cost=1.0):
        self.llm = object()
        self.cost = cost
        self.store: dict[str, float] = {}
        self.running: dict[str, str] = {}
        self.calls: list[str] = []
        self.jobs = types.SimpleNamespace(get=self._job)
        self.fail_with: Exception | None = None

    def _job(self, key):
        return types.SimpleNamespace(status="running") if key in self.running else None

    def cached(self, key, persona=None):
        return types.SimpleNamespace(cost_rub=self.store[key]) if key in self.store else None

    def insight(self, event_id, persona, wait=True):
        if self.fail_with:
            raise self.fail_with
        self.calls.append(event_id)
        self.running[insight_id(event_id, persona)] = persona
        return types.SimpleNamespace(status="queued")

    def finish(self):
        for key in list(self.running):
            self.store[key] = self.cost
            del self.running[key]


def feed(*levels):
    items = []
    for n, level in enumerate(levels):
        it = item(0.9 - n * 0.1, title=f"e{n}")
        it.takeaway = Takeaway(level=level, text="t")
        items.append(it)
    return Feed(
        persona_id="p-u1-cfo", company_id="U_1", role="cfo", items=items, candidates=1, news_source="t"
    )


def make(agent, levels=("act", "watch", "info"), **kw):
    kw.setdefault("in_flight", 10)
    return Precompute(agent, ["p-u1-cfo"], lambda p: feed(*levels), clock=lambda: NOW, **kw)


def test_queues_important_by_score_and_skips_info_and_ready():
    agent = FakeAgent()
    agent.store[insight_id("src:news:e0", "p-u1-cfo")] = 0.5  # уже собрана
    pre = make(agent)
    pre.cycle()
    assert agent.calls == ["src:news:e1"]  # «следить» при свободном бюджете; «к сведению» — нет
    assert pre.status().cache_hits == 1 and pre.status().queued == 1
    agent.finish()
    pre.cycle()  # итог: собрано, стоимость — в бюджет; повторно не ставит
    s = pre.status()
    assert (s.built, s.spent_rub, s.queued) == (1, 1.0, 0) and agent.calls == ["src:news:e1"]
    assert pre.queued("src:news:e1", "p-u1-cfo") is False


def test_budget_hour_and_in_flight_limits():
    agent = FakeAgent()
    pre = make(agent, levels=("act",) * 5, budget_rub=7.0)  # 3 ₽ запаса на каждую: влезают две
    pre.cycle()
    assert len(agent.calls) == 2 and "бюджет" in pre.status().stopped
    hourly = make(FakeAgent(), levels=("act",) * 5, per_hour=3)
    hourly.cycle()
    assert len(hourly.agent.calls) == 3 and "в час" in hourly.status().stopped
    narrow = make(FakeAgent(), levels=("act",) * 5, in_flight=1)
    narrow.cycle()
    assert len(narrow.agent.calls) == 1


def test_watch_only_while_budget_is_free_and_switch_off():
    agent = FakeAgent()
    pre = make(agent, levels=("watch",), budget_rub=10.0)
    pre._spent = 6.0
    pre.cycle()
    assert agent.calls == []
    off = make(FakeAgent(), enabled=False)
    off.cycle()
    assert off.agent.calls == [] and "выключено" in off.status().stopped
    assert "агент" in (lambda p: (p.cycle(), p.status().stopped)[1])(make(None))


def test_new_budget_day_resets_spend_and_shared_budget_stops():
    agent = FakeAgent(cost=5.0)
    clock = [NOW]
    pre = Precompute(agent, ["p-u1-cfo"], lambda p: feed("act"), clock=lambda: clock[0], budget_rub=6)
    pre.cycle()
    agent.finish()
    pre.cycle()
    assert pre.status().spent_rub == 5.0
    clock[0] = NOW + dt.timedelta(days=1)
    assert pre.status().spent_rub == 0.0
    broke = FakeAgent()
    broke.fail_with = BudgetExceeded("за сутки потрачено")
    p = make(broke)
    p.cycle()
    assert "общий бюджет" in p.status().stopped


def test_failed_build_costs_reserve_and_is_retried_once():
    agent = FakeAgent()
    pre = make(agent, levels=("act",))
    pre.cycle()
    agent.running.clear()  # сборка упала: карточки нет
    pre.cycle()  # итог: −3 ₽ запаса, вторая попытка
    assert pre.status().failed == 1 and pre.status().spent_rub == 3.0 and len(agent.calls) == 2
    agent.running.clear()
    pre.cycle()
    pre.cycle()
    assert len(agent.calls) == 2  # две попытки — больше не ставим


def test_not_relevant_is_final_and_temporary_error_is_retried():
    class NotRelevant(Exception):
        pass

    agent = FakeAgent()
    agent.fail_with = NotRelevant("src:news:e0")
    pre = make(agent, levels=("act",))
    pre.cycle()
    pre.cycle()
    assert pre._attempts == {} and len(pre._done) == 1
    busy = FakeAgent()
    busy.fail_with = RuntimeError("сервис занят")
    p = make(busy, levels=("act",))
    p.cycle()
    assert not p._done and p._attempts
    busy.fail_with = None
    p.cycle()
    assert busy.calls == ["src:news:e0"]


def test_no_feeds_built_when_budget_is_spent():
    built = []
    pre = Precompute(FakeAgent(), ["p-u1-cfo"], lambda p: built.append(p), clock=lambda: NOW, budget_rub=2)
    pre.cycle()
    assert built == [] and "бюджет" in pre.status().stopped
