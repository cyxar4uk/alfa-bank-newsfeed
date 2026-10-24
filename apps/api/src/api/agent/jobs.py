"""Фоновая сборка карточек: первый запрос не держит соединение минуту, а сразу отвечает статусом.

Одна задача на пару «событие × пользователь»: повторный запрос, пока карточка собирается, получает статус
той же задачи. Одновременно собирается не больше `max_workers` карточек, остальные ждут в очереди. Этапы
сборки («Ищу аналитику Альфа-Банка», «Пишу разбор»…) приходят из агента и видны в статусе. Задачи хранятся
в БД: после перезапуска API незаконченная задача честно становится failed, а не висит. Запись в БД —
вспомогательная: её сбой не роняет сборку и не оставляет задачу «идущей»; правда о задачах этого процесса —
в памяти.
"""

import datetime as dt
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Literal, Protocol

from pydantic import BaseModel, Field

JobState = Literal["queued", "running", "done", "failed"]
DEFAULT_ETA_SECONDS = 75.0  # средняя сборка карточки по живым прогонам — 55–115 с
RESTART_ERROR = "API перезапущен во время сборки — запросите карточку заново"
INTERNAL_ERROR = "внутренняя ошибка сборки — запросите карточку заново"
KEEP_FINISHED = 1000  # сколько последних законченных задач держать в памяти

log = logging.getLogger("api.agent.jobs")


class JobStatus(BaseModel):
    """Состояние сборки карточки по паре «событие × пользователь»."""

    insight_id: str
    event_id: str
    persona_id: str
    status: JobState = Field(description="queued — ждёт очереди, running — собирается, done — готово, failed")
    stage: str = Field(default="", description="текущий этап человеческим текстом")
    stages_done: list[str] = Field(default_factory=list, description="пройденные этапы по порядку")
    elapsed_s: float = Field(default=0.0, description="сколько секунд идёт сборка")
    eta_s: float | None = Field(default=None, description="примерно сколько секунд осталось")
    queue_position: int | None = Field(default=None, description="место в очереди, если status=queued")
    error: str | None = None
    trace_id: str | None = None
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None


class JobStore(Protocol):
    def save_job(self, job: JobStatus) -> None: ...

    def get_job(self, insight_id: str) -> JobStatus | None: ...

    def fail_unfinished(self, error: str) -> int: ...


Run = Callable[[Callable[[str], None]], str | None]  # (on_stage) → trace_id


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Jobs:
    def __init__(self, store: JobStore, max_workers: int = 3) -> None:
        self.store = store
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="insight")
        self._lock = threading.Lock()
        self._active: dict[str, JobStatus] = {}
        self._finished: dict[str, JobStatus] = {}  # итог задач этого процесса — важнее записи в БД
        self._done: dict[str, threading.Event] = {}
        self._order: list[str] = []  # очередь — по порядку постановки
        self._started: dict[str, float] = {}
        self._durations: list[float] = []
        self.max_workers = max_workers

    def recover(self) -> int:
        """При старте API: задачи, которые не успели закончиться до перезапуска, — failed."""
        return self.store.fail_unfinished(RESTART_ERROR)

    def get(self, insight_id: str) -> JobStatus | None:
        with self._lock:
            job = self._active.get(insight_id)
            if job is not None:
                return self._view(job)
            job = self._finished.get(insight_id)
            if job is not None:
                return job.model_copy(deep=True)
        try:
            stored = self.store.get_job(insight_id)
        except Exception:
            log.exception("не прочитан статус задачи %s", insight_id)
            return None
        if stored is not None and stored.status in ("queued", "running"):
            # «идёт» в БД, но этот процесс её не ведёт — сборка прервалась (перезапуск, сбой записи итога)
            return stored.model_copy(update={"status": "failed", "stage": "", "error": RESTART_ERROR})
        return stored

    def wait(self, insight_id: str, timeout: float) -> JobStatus | None:
        """Дождаться конца задачи (не дольше `timeout` секунд) и вернуть её статус."""
        with self._lock:
            done = self._done.get(insight_id)
        if done is not None:
            done.wait(timeout)
        return self.get(insight_id)

    def submit(self, insight_id: str, event_id: str, persona_id: str, run: Run) -> JobStatus:
        """Поставить сборку в очередь; уже идёт — вернуть статус той же задачи, вторую не запускать."""
        with self._lock:
            active = self._active.get(insight_id)
            if active is not None:
                return self._view(active)
            job = JobStatus(insight_id=insight_id, event_id=event_id, persona_id=persona_id, status="queued")
            self._active[insight_id] = job
            self._order.append(insight_id)
            self._done[insight_id] = threading.Event()
            self._finished.pop(insight_id, None)
        self._save(job)
        try:
            self._pool.submit(self._work, insight_id, run)
        except RuntimeError:  # пул остановлен — API выключается: задачу не оставляем «в очереди»
            with self._lock:
                self._active.pop(insight_id, None)
                self._order.remove(insight_id)
                self._done.pop(insight_id).set()
            raise
        return self.get(insight_id) or job

    def _save(self, job: JobStatus) -> None:
        """Записать статус в БД; сбой записи не роняет сборку — статус этого процесса есть в памяти."""
        try:
            self.store.save_job(job)
        except Exception:
            log.exception("не записан статус задачи %s", job.insight_id)

    def _work(self, insight_id: str, run: Run) -> None:
        status: JobState = "failed"
        error: str | None = INTERNAL_ERROR
        trace_id: str | None = None
        try:
            with self._lock:
                job = self._active[insight_id]
                job.status, job.started_at = "running", _now()
                self._order.remove(insight_id)
                self._started[insight_id] = time.monotonic()
            self._save(job)

            def on_stage(text: str) -> None:
                with self._lock:
                    if job.stage:
                        job.stages_done.append(job.stage)
                    job.stage = text
                self._save(job)

            trace_id = run(on_stage)
            status, error = "done", None
        except Exception as exc:  # сбой сборки — статус failed с понятным текстом
            error = str(exc) or type(exc).__name__
            trace_id = getattr(getattr(exc, "trace", None), "id", None)
        finally:
            self._finish(insight_id, status, error=error, trace_id=trace_id)

    def _finish(
        self, insight_id: str, status: JobState, error: str | None = None, trace_id: str | None = None
    ) -> None:
        with self._lock:
            job = self._active.pop(insight_id, None)
            if job is None:
                return
            if insight_id in self._order:
                self._order.remove(insight_id)
            started = self._started.pop(insight_id, None)
            if started is not None:
                job.elapsed_s = round(time.monotonic() - started, 1)
                if status == "done":
                    self._durations = [*self._durations[-19:], job.elapsed_s]
            if job.stage:
                job.stages_done.append(job.stage)
            job.status, job.stage, job.error, job.trace_id = status, "", error, trace_id
            job.finished_at, job.eta_s = _now(), None
            self._finished[insight_id] = job
            while len(self._finished) > KEEP_FINISHED:
                del self._finished[next(iter(self._finished))]
            done = self._done.pop(insight_id, None)
        if done is not None:
            done.set()
        self._save(job)

    def _view(self, job: JobStatus) -> JobStatus:
        """Копия статуса с прошедшим временем, оценкой оставшегося и местом в очереди."""
        view = job.model_copy(deep=True)
        avg = sum(self._durations) / len(self._durations) if self._durations else DEFAULT_ETA_SECONDS
        if job.status == "running":
            view.elapsed_s = round(time.monotonic() - self._started.get(job.insight_id, time.monotonic()), 1)
            view.eta_s = round(max(avg - view.elapsed_s, 5.0), 0)
        elif job.status == "queued":
            position = self._order.index(job.insight_id) + 1 if job.insight_id in self._order else 1
            view.queue_position = position
            waves = (position - 1) // self.max_workers + 1
            view.eta_s = round(avg * waves + avg, 0)
        return view

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
