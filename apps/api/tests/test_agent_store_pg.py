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
