"""Хранилище агента в настоящем PostgreSQL. Запускается, если задан TEST_DATABASE_URL (таблицы агента
очищаются).
"""

import os

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

from api.agent.service import AgentService
from api.agent.store import FeedbackIn

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL не задан")


@pytest.fixture
def store():
    import psycopg
    from psycopg_pool import ConnectionPool

    from api.agent.store import PgAgentStore

    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS agent_insights, agent_traces, agent_feedback")
    with ConnectionPool(URL, min_size=1, max_size=2) as pool:
        s = PgAgentStore(pool)
        s.ensure_schema()
        s.ensure_schema()  # повторный старт API не ломает таблицы
        yield s


def test_insight_trace_feedback_roundtrip(store):
    transport = ScriptedTransport(reply(GOOD_PLAN), reply(good_draft()))
    service = AgentService(make_llm(transport), FakeCompany(), FakeLibrary(), store)
    insight = service.insight(NEWS_ID, PERSONA.id)

    stored = store.get_insight(insight.id)
    assert stored.insight == insight
    assert stored.context["persona"]["id"] == PERSONA.id and stored.cost_rub > 0
    # повторный запрос — из БД, без модели
    assert service.insight(NEWS_ID, PERSONA.id) == insight
    assert len(transport.bodies) == 2

    trace = store.get_trace(insight.trace_id)
    assert trace.insight_id == insight.id and trace.steps[0].kind == "tool"

    store.add_feedback(
        FeedbackIn(insight_id=insight.id, persona_id=PERSONA.id, useful=False, reason="too_general")
    )
    store.add_feedback(FeedbackIn(insight_id=insight.id, useful=True))
    stats = store.feedback_stats(insight.id)
    assert (stats.total, stats.useful, stats.reasons) == (2, 1, {"too_general": 1})
    assert store.feedback_stats("ins:other").total == 0


def test_jobs_and_version_roundtrip(store):
    from api.agent.jobs import RESTART_ERROR, JobStatus

    job = JobStatus(
        insight_id="ins:1", event_id="src:news:1", persona_id="p", status="running", stage="Пишу разбор"
    )
    store.save_job(job)
    assert store.get_job("ins:1").stage == "Пишу разбор"
    store.save_job(JobStatus(insight_id="ins:2", event_id="src:news:2", persona_id="p", status="done"))
    assert store.fail_unfinished(RESTART_ERROR) == 1
    failed = store.get_job("ins:1")
    assert (failed.status, failed.error, failed.stage) == ("failed", RESTART_ERROR, "")
    assert store.get_job("ins:2").status == "done" and store.get_job("ins:none") is None

    transport = ScriptedTransport(reply(GOOD_PLAN), reply(good_draft()))
    service = AgentService(make_llm(transport), FakeCompany(), FakeLibrary(), store)
    insight = service.insight(NEWS_ID, PERSONA.id)
    stored = store.get_insight(insight.id)
    assert stored.version == service.version and "_version" not in stored.context
