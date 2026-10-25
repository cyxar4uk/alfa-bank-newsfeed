import threading
import time
import types

from api import main
from api.cache import FEEDS, TtlCache


def test_value_is_computed_once_until_refresh_or_expiry():
    cache, calls = TtlCache(), []
    assert cache.get_or_compute("k", lambda: calls.append(1) or len(calls)) == 1
    assert cache.get_or_compute("k", lambda: calls.append(1) or len(calls)) == 1
    assert cache.get_or_compute("k", lambda: calls.append(1) or len(calls), refresh=True) == 2
    stale = TtlCache(ttl=-1)
    stale.get_or_compute("k", lambda: 1)
    assert stale.get_or_compute("k", lambda: 2) == 2


def test_concurrent_requests_wait_for_one_computation():
    cache, calls, gate, entered = TtlCache(), [], threading.Event(), threading.Event()

    def slow():
        entered.set()
        gate.wait(2)  # считаем, пока остальные запросы уже пришли и ждут
        calls.append(1)
        return "feed"

    threads = [threading.Thread(target=cache.get_or_compute, args=("k", slow)) for _ in range(4)]
    for t in threads:
        t.start()
    entered.wait(2)
    time.sleep(0.2)
    gate.set()
    for t in threads:
        t.join()
    assert calls == [1]


def test_warmup_fills_day_week_and_risk_map(monkeypatch):
    built = []
    monkeypatch.setattr(main, "DEMO_PERSONAS", [("U_1", "cfo", "")])
    monkeypatch.setattr(
        main,
        "build_feed",
        lambda repo, news, agent, persona, limit, llm, period: built.append(period) or period,
    )
    monkeypatch.setattr(
        main, "company_risk_map", lambda repo, news, cid, persona: built.append("risk") or "risk"
    )
    monkeypatch.setattr(main, "news_for", lambda state: types.SimpleNamespace(name="n"))
    main.warm_feeds(types.SimpleNamespace(repo=None, agent=None), rounds=1)
    assert built == ["day", "week", "risk"]
    assert FEEDS.get_or_compute(("p-u1-cfo", "week", 20, True, "n"), lambda: "cold") == "week"
