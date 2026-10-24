"""Хранилище агента в PostgreSQL: готовые инсайты (кэш), трассы, отзывы пользователей.

Таблицы свои и создаются при старте API; импорт данных кейса их не трогает.
"""

import datetime as dt
import uuid
from typing import Protocol

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field

from api.agent.jobs import JobStatus
from api.contract import Insight, Trace

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_insights (
    id          text PRIMARY KEY,
    event_id    text NOT NULL,
    persona_id  text NOT NULL,
    insight     jsonb NOT NULL,
    context     jsonb NOT NULL,
    cost_rub    double precision NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_insights_event_idx ON agent_insights (event_id, persona_id);

CREATE TABLE IF NOT EXISTS agent_traces (
    id          text PRIMARY KEY,
    insight_id  text,
    trace       jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_feedback (
    id          text PRIMARY KEY,
    insight_id  text NOT NULL,
    persona_id  text,
    useful      boolean NOT NULL,
    reason      text,
    comment     text,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_feedback_insight_idx ON agent_feedback (insight_id);

CREATE TABLE IF NOT EXISTS agent_jobs (
    insight_id  text PRIMARY KEY,
    status      text NOT NULL,
    job         jsonb NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);
"""

FeedbackReason = str


class FeedbackIn(BaseModel):
    insight_id: str = Field(pattern=r"^ins:")
    persona_id: str | None = None
    useful: bool
    reason: str | None = Field(
        default=None,
        max_length=100,
        description="причина: not_relevant, wrong_facts, too_general, no_bank_view, unclear или своя",
    )
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackOut(BaseModel):
    id: str
    created_at: dt.datetime


class FeedbackStats(BaseModel):
    total: int
    useful: int
    not_useful: int
    useful_share: float | None = Field(description="доля «полезно»; нет отзывов — null")
    reasons: dict[str, int] = Field(default_factory=dict, description="причины «не полезно»")


class StoredInsight(BaseModel):
    insight: Insight
    context: dict
    cost_rub: float = 0.0
    version: str = Field(default="", description="версия логики агента, с которой собрана карточка")


class AgentStore(Protocol):
    def get_insight(self, insight_id: str) -> StoredInsight | None: ...

    def save_insight(self, event_id: str, persona_id: str, stored: StoredInsight) -> None: ...

    def save_trace(self, trace: Trace) -> None: ...

    def get_trace(self, trace_id: str) -> Trace | None: ...

    def add_feedback(self, feedback: FeedbackIn) -> FeedbackOut: ...

    def feedback_stats(self, insight_id: str | None = None) -> FeedbackStats: ...

    def save_job(self, job: JobStatus) -> None: ...

    def get_job(self, insight_id: str) -> JobStatus | None: ...

    def fail_unfinished(self, error: str) -> int: ...


def _stats(rows: list[tuple[bool, str | None]]) -> FeedbackStats:
    useful = sum(1 for u, _ in rows if u)
    reasons: dict[str, int] = {}
    for u, reason in rows:
        if not u:
            key = reason or "без причины"
            reasons[key] = reasons.get(key, 0) + 1
    total = len(rows)
    return FeedbackStats(
        total=total,
        useful=useful,
        not_useful=total - useful,
        useful_share=round(useful / total, 3) if total else None,
        reasons=dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
    )


class PgAgentStore:
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def ensure_schema(self) -> None:
        with self.pool.connection() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('agent_schema'))")
            conn.execute(SCHEMA)

    def get_insight(self, insight_id: str) -> StoredInsight | None:
        with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute(
                "SELECT insight, context, cost_rub FROM agent_insights WHERE id = %s", (insight_id,)
            ).fetchone()
        if row is None:
            return None
        context = dict(row["context"])
        version = context.pop("_version", "")
        return StoredInsight(
            insight=row["insight"], context=context, cost_rub=row["cost_rub"], version=version
        )

    def save_insight(self, event_id: str, persona_id: str, stored: StoredInsight) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO agent_insights (id, event_id, persona_id, insight, context, cost_rub)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET insight = EXCLUDED.insight, context = EXCLUDED.context,
                    cost_rub = EXCLUDED.cost_rub, created_at = now()
                """,
                (
                    stored.insight.id,
                    event_id,
                    persona_id,
                    Jsonb(stored.insight.model_dump(mode="json")),
                    Jsonb({**stored.context, "_version": stored.version}),
                    stored.cost_rub,
                ),
            )

    def save_trace(self, trace: Trace) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO agent_traces (id, insight_id, trace) VALUES (%s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET trace = EXCLUDED.trace, insight_id = EXCLUDED.insight_id
                """,
                (trace.id, trace.insight_id, Jsonb(trace.model_dump(mode="json"))),
            )

    def get_trace(self, trace_id: str) -> Trace | None:
        with self.pool.connection() as conn:
            row = conn.execute("SELECT trace FROM agent_traces WHERE id = %s", (trace_id,)).fetchone()
        return Trace.model_validate(row[0]) if row else None

    def add_feedback(self, feedback: FeedbackIn) -> FeedbackOut:
        fid = f"fb:{uuid.uuid4().hex[:16]}"
        with self.pool.connection() as conn:
            created = conn.execute(
                """
                INSERT INTO agent_feedback (id, insight_id, persona_id, useful, reason, comment)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING created_at
                """,
                (
                    fid,
                    feedback.insight_id,
                    feedback.persona_id,
                    feedback.useful,
                    feedback.reason,
                    feedback.comment,
                ),
            ).fetchone()[0]
        return FeedbackOut(id=fid, created_at=created)

    def feedback_stats(self, insight_id: str | None = None) -> FeedbackStats:
        query = "SELECT useful, reason FROM agent_feedback"
        params: tuple = ()
        if insight_id:
            query += " WHERE insight_id = %s"
            params = (insight_id,)
        with self.pool.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return _stats([(r[0], r[1]) for r in rows])

    def save_job(self, job: JobStatus) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO agent_jobs (insight_id, status, job) VALUES (%s, %s, %s)
                ON CONFLICT (insight_id) DO UPDATE SET status = EXCLUDED.status, job = EXCLUDED.job,
                    updated_at = now()
                """,
                (job.insight_id, job.status, Jsonb(job.model_dump(mode="json"))),
            )

    def get_job(self, insight_id: str) -> JobStatus | None:
        with self.pool.connection() as conn:
            row = conn.execute("SELECT job FROM agent_jobs WHERE insight_id = %s", (insight_id,)).fetchone()
        return JobStatus.model_validate(row[0]) if row else None

    def fail_unfinished(self, error: str) -> int:
        with self.pool.connection() as conn:
            rows = conn.execute(
                """
                UPDATE agent_jobs
                SET status = 'failed', updated_at = now(),
                    job = job || jsonb_build_object('status', 'failed', 'stage', '', 'error', %s::text)
                WHERE status IN ('queued', 'running')
                RETURNING insight_id
                """,
                (error,),
            ).fetchall()
        return len(rows)


class MemoryAgentStore:
    """То же в памяти — для тестов и запуска без БД."""

    def __init__(self) -> None:
        self.insights: dict[str, StoredInsight] = {}
        self.traces: dict[str, Trace] = {}
        self.feedback: list[FeedbackIn] = []
        self.jobs: dict[str, JobStatus] = {}

    def get_insight(self, insight_id):
        return self.insights.get(insight_id)

    def save_insight(self, event_id, persona_id, stored):
        self.insights[stored.insight.id] = stored

    def save_trace(self, trace):
        self.traces[trace.id] = trace

    def get_trace(self, trace_id):
        return self.traces.get(trace_id)

    def add_feedback(self, feedback):
        self.feedback.append(feedback)
        return FeedbackOut(id=f"fb:{len(self.feedback)}", created_at=dt.datetime.now(dt.UTC))

    def feedback_stats(self, insight_id=None):
        rows = [(f.useful, f.reason) for f in self.feedback if insight_id in (None, f.insight_id)]
        return _stats(rows)

    def save_job(self, job):
        self.jobs[job.insight_id] = job.model_copy(deep=True)

    def get_job(self, insight_id):
        job = self.jobs.get(insight_id)
        return job.model_copy(deep=True) if job else None

    def fail_unfinished(self, error):
        n = 0
        for job in self.jobs.values():
            if job.status in ("queued", "running"):
                job.status, job.stage, job.error = "failed", "", error
                n += 1
        return n
