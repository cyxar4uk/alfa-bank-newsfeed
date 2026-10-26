"""Фоновая сборка карточки: статус по опросу, одна задача на пару, честный failed, лимит параллелизма."""

import threading
import time

import pytest
from agent_fakes import (
    GOOD_PLAN,
    NEWS_ID,
    PERSONA,
    FakeCompany,
    FakeLibrary,
    ScriptedTransport,
    good_draft,
    make_llm,
    reply,
)
from fastapi.testclient import TestClient

from api.agent.jobs import RESTART_ERROR, Jobs, JobStatus
from api.agent.loop import insight_id
from api.agent.routes import get_agent
from api.agent.service import AgentService
from api.agent.store import MemoryAgentStore
from api.agent.trace import ProgressStep
from api.llm import TransportResponse
from api.main import app

KEY = insight_id(NEWS_ID, PERSONA.id)
ASYNC = {"persona": PERSONA.id, "wait": "false"}  # фоновый режим — по запросу клиента


class SlowTransport(ScriptedTransport):
    """Модель «думает», пока тест не отпустит: так видно этапы и повторные запросы во время сборки."""

    def __init__(self, *responses):
        super().__init__(*responses)
        self.release = threading.Event()

    def post(self, body):
        if len(self.bodies) == 1:  # черновик — после плана
            self.release.wait(5)
        return super().post(body)


@pytest.fixture
def api():
    def make(transport, store=None):
        store = store or MemoryAgentStore()
        service = AgentService(make_llm(transport), FakeCompany(), FakeLibrary(), store)
        app.dependency_overrides[get_agent] = lambda: service
        return TestClient(app), service

    yield make
    app.dependency_overrides.clear()


def wait_status(client, want, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/insights/{NEWS_ID}/status", params={"persona": PERSONA.id}).json()
        if body.get("status") in want:
            return body
        time.sleep(0.02)
    raise AssertionError(f"статус не дошёл до {want}: {body}")


def test_first_request_returns_status_and_one_build_per_pair(api):
    transport = SlowTransport(reply(GOOD_PLAN), reply(good_draft()))
    client, _ = api(transport)
    first = client.get(f"/api/insights/{NEWS_ID}", params=ASYNC)
    assert first.status_code == 202
    job = first.json()
    assert job["insight_id"] == KEY and job["status"] in ("queued", "running")
    running = wait_status(client, {"running"})
    # повторный запрос во время сборки — тот же статус, вторая сборка не запускается
    again = client.get(f"/api/insights/{NEWS_ID}", params=ASYNC)
    assert again.status_code == 202 and again.json()["insight_id"] == KEY
    assert running["stage"] and running["eta_s"] is not None
    transport.release.set()
    done = wait_status(client, {"done", "failed"})
    assert done["status"] == "done", done
    assert "Формулирую вывод: важно ли это вам и что делать" in done["stages_done"]
    assert "Ищу, что пишет об этом Альфа-Банк" in done["stages_done"]
    # ход разбора — шаги человеческим языком с тем, что найдено
    steps = done["steps"]
    assert steps and all(st["state"] == "done" for st in steps)
    bank_step = next(st for st in steps if st["title"] == "Ищу, что пишет об этом Альфа-Банк")
    assert any(f.startswith("Материал банка «") for f in bank_step["found"])
    from api.agent.plain import technical

    for st in steps:
        assert not technical(st["title"]) and not any(technical(f) for f in st["found"]), st
    assert done["trace_id"].startswith("tr:") and done["elapsed_s"] >= 0
    ready = client.get(f"/api/insights/{NEWS_ID}", params=ASYNC)
    assert ready.status_code == 200 and ready.json()["id"] == KEY
    assert len(transport.bodies) == 2  # план и черновик — одна сборка


def test_failed_build_is_reported_and_can_be_retried(api):
    error = TransportResponse(400, {"error": "bad"}, '{"error": "bad"}')
    client, service = api(
        ScriptedTransport(reply(GOOD_PLAN), error, error, reply(GOOD_PLAN), reply(good_draft()))
    )
    assert client.get(f"/api/insights/{NEWS_ID}", params=ASYNC).status_code == 202
    failed = wait_status(client, {"failed", "done"})
    assert failed["status"] == "failed" and "400" in failed["error"] and failed["trace_id"]
    # повторный запрос после сбоя — новая сборка
    assert client.get(f"/api/insights/{NEWS_ID}", params=ASYNC).status_code == 202
    assert wait_status(client, {"done", "failed"})["status"] == "done"


def test_unfinished_job_fails_after_restart(api):
    store = MemoryAgentStore()
    store.save_job(
        JobStatus(
            insight_id=KEY, event_id=NEWS_ID, persona_id=PERSONA.id, status="running", stage="Пишу разбор"
        )
    )
    jobs = Jobs(store)
    assert jobs.recover() == 1
    client, _ = api(ScriptedTransport(reply(GOOD_PLAN), reply(good_draft())), store=store)
    status = client.get(f"/api/insights/{NEWS_ID}/status", params={"persona": PERSONA.id}).json()
    assert status["status"] == "failed" and status["error"] == RESTART_ERROR
    # после перезапуска запрос карточки запускает сборку заново, а не ждёт мёртвую задачу
    assert client.get(f"/api/insights/{NEWS_ID}", params=ASYNC).status_code == 202
    assert wait_status(client, {"done", "failed"})["status"] == "done"


def test_parallel_builds_are_limited_and_queued():
    store = MemoryAgentStore()
    jobs = Jobs(store, max_workers=2)
    gate = threading.Event()
    started = []

    def run(on_progress):
        started.append(1)
        on_progress([ProgressStep(title="Пишу разбор")])
        gate.wait(5)
        return "tr:x"

    for i in range(5):
        jobs.submit(f"ins:{i}", f"src:news:{i}", "p", run)
    deadline = time.monotonic() + 2
    while len(started) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.05)
    states = [jobs.get(f"ins:{i}") for i in range(5)]
    assert [s.status for s in states].count("running") == 2
    queued = [s for s in states if s.status == "queued"]
    assert len(queued) == 3 and sorted(s.queue_position for s in queued) == [1, 2, 3]
    gate.set()
    jobs.shutdown()


def test_status_of_cached_insight_and_unknown(api):
    client, service = api(ScriptedTransport(reply(GOOD_PLAN), reply(good_draft())))
    assert client.get(f"/api/insights/{NEWS_ID}/status", params={"persona": PERSONA.id}).status_code == 404
    client.get(f"/api/insights/{NEWS_ID}", params={"persona": PERSONA.id, "wait": "true"})
    service.jobs = Jobs(service.store)  # «после перезапуска»: задач в памяти нет, карточка в кэше
    service.store.jobs.clear()
    body = client.get(f"/api/insights/{NEWS_ID}/status", params={"persona": PERSONA.id}).json()
    assert body["status"] == "done"


def test_analyze_returns_status_with_event_id(api):
    client, _ = api(ScriptedTransport(reply(GOOD_PLAN), reply(good_draft())))
    text = (
        "Совет директоров Банка России сохранил ключевую ставку на уровне 14% годовых. Снижение не обсуждали."
    )
    r = client.post("/api/analyze", params={"wait": "false"}, json={"persona_id": PERSONA.id, "text": text})
    assert r.status_code == 202 and r.json()["event_id"] == "src:news:user-1"


def test_budget_problem_is_immediate_not_a_job(api):
    transport = ScriptedTransport()
    client, service = api(transport)
    service.llm.budget.limit_rub = 0.0
    r = client.get(f"/api/insights/{NEWS_ID}", params=ASYNC)
    assert r.status_code == 503 and "Budget has been exceeded" in r.json()["detail"]
    assert service.jobs.get(KEY) is None


def test_card_of_other_agent_version_is_not_served(api):
    client, service = api(
        ScriptedTransport(reply(GOOD_PLAN), reply(good_draft()), reply(GOOD_PLAN), reply(good_draft()))
    )
    assert (
        client.get(f"/api/insights/{NEWS_ID}", params={"persona": PERSONA.id, "wait": "true"}).status_code
        == 200
    )
    assert service.cached(KEY) is not None
    service.version = "другая"  # сменились промпты или модели
    assert service.cached(KEY) is None
    assert client.get(f"/api/insights/{NEWS_ID}", params=ASYNC).status_code == 202


def test_version_changes_with_models():
    from api.agent.version import agent_version

    assert agent_version({"draft": "a"}) != agent_version({"draft": "b"})
    assert agent_version() == agent_version()


class FlakyStore(MemoryAgentStore):
    """БД, которая не принимает запись статусов задач."""

    def save_job(self, job):
        raise OSError("БД недоступна")


def test_store_failure_does_not_break_or_hang_the_build(api):
    client, service = api(ScriptedTransport(reply(GOOD_PLAN), reply(good_draft())), store=FlakyStore())
    assert client.get(f"/api/insights/{NEWS_ID}", params=ASYNC).status_code == 202
    done = wait_status(client, {"done", "failed"})
    assert done["status"] == "done", done  # запись этапов и итога упала — сборка всё равно закончилась
    assert client.get(f"/api/insights/{NEWS_ID}", params=ASYNC).status_code == 200


def test_running_in_db_but_not_in_this_process_is_failed():
    store = MemoryAgentStore()
    store.save_job(JobStatus(insight_id=KEY, event_id=NEWS_ID, persona_id=PERSONA.id, status="running"))
    job = Jobs(store).get(KEY)  # recover() не звали: задача «идёт» в БД, но её никто не ведёт
    assert job.status == "failed" and job.error == RESTART_ERROR


def test_finished_status_is_kept_in_memory_not_db():
    store = MemoryAgentStore()
    jobs = Jobs(store)
    jobs.submit(KEY, NEWS_ID, PERSONA.id, lambda on_progress: "tr:x")
    assert jobs.wait(KEY, 5).status == "done"
    store.jobs[KEY] = store.jobs[KEY].model_copy(update={"status": "running"})  # итог в БД не записался
    assert jobs.get(KEY).status == "done"
    jobs.shutdown()


def test_wait_true_joins_the_running_build(api):
    transport = SlowTransport(reply(GOOD_PLAN), reply(good_draft()))
    client, _ = api(transport)
    assert client.get(f"/api/insights/{NEWS_ID}", params=ASYNC).status_code == 202
    wait_status(client, {"running"})
    threading.Timer(0.2, transport.release.set).start()
    # синхронный запрос во время фоновой сборки дожидается её, а не запускает вторую и не отвечает 202
    r = client.get(f"/api/insights/{NEWS_ID}", params={"persona": PERSONA.id})
    assert r.status_code == 200 and r.json()["id"] == KEY
    assert len(transport.bodies) == 2


def test_default_is_synchronous_for_old_clients(api):
    client, _ = api(ScriptedTransport(reply(GOOD_PLAN), reply(good_draft())))
    r = client.get(f"/api/insights/{NEWS_ID}", params={"persona": PERSONA.id})
    assert r.status_code == 200 and r.json()["disclaimer"]


def test_failed_own_news_is_rebuilt_by_get(api):
    error = TransportResponse(400, {"error": "bad"}, '{"error": "bad"}')
    client, service = api(ScriptedTransport(reply(GOOD_PLAN), error))
    text = "Совет директоров Банка России сохранил ключевую ставку на уровне 14% годовых."
    r = client.post("/api/analyze", params={"wait": "false"}, json={"persona_id": PERSONA.id, "text": text})
    event_id = r.json()["event_id"]
    deadline = time.monotonic() + 5
    while service.jobs.get(r.json()["insight_id"]).status != "failed" and time.monotonic() < deadline:
        time.sleep(0.02)
    service.touches = lambda persona, event: False  # своя новость связь по разметке может и не пройти
    again = client.get(f"/api/insights/{event_id}", params=ASYNC)
    assert again.status_code == 202, again.text  # сборка запущена заново, а не «не касается» (204)
