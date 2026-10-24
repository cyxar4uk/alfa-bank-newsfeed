"""Сервис агента для эндпоинтов: ленивый инсайт с кэшем, своя новость, уточняющий вопрос, трасса, отзывы."""

import threading
from collections import defaultdict

from api.agent.ask import AskOut, answer
from api.agent.context import from_snapshot
from api.agent.jobs import Jobs, JobStatus
from api.agent.loop import Agent, AgentError, CompanyNotFound, insight_id
from api.agent.ports import LEVEL_RANK, CompanyData, Event, Library
from api.agent.store import AgentStore, StoredInsight
from api.agent.tools import Tools
from api.agent.trace import TraceRecorder
from api.agent.version import agent_version
from api.contract import Insight, Persona
from api.llm import BudgetExceeded, LlmClient

MAX_RUNS = 3
RUN_WAIT_SECONDS = 60
RUN_RESERVE_RUB = 3.0  # дороже карточка не выходила: черновик ~0,7 ₽, две доработки ~0,4 ₽ каждая


class NotFound(LookupError):
    pass


class NotRelevant(Exception):
    """Событие не касается компании: ни один фактор карты и ни один канал цепочки с ним не связаны."""


class AgentService:
    def __init__(
        self,
        llm: LlmClient | None,
        company: CompanyData,
        library: Library,
        store: AgentStore,
        jobs: Jobs | None = None,
    ) -> None:
        self.llm = llm
        self.company = company
        self.library = library
        self.store = store
        self.jobs = jobs or Jobs(store, max_workers=MAX_RUNS)
        self.version = agent_version(llm.models if llm else None, llm.step_params if llm else None)
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._guard = threading.Lock()
        # одновременно собираются не больше MAX_RUNS карточек: лента не должна разом сжечь суточный бюджет
        self._runs = threading.BoundedSemaphore(MAX_RUNS)

    def _lock(self, key: str) -> threading.Lock:
        with self._guard:
            if len(self._locks) > 1000:  # не копим блокировки бесконечно: свободные убираем
                for k in [k for k, lock in self._locks.items() if not lock.locked()]:
                    del self._locks[k]
            return self._locks[key]

    def _persona(self, persona_id: str) -> Persona:
        persona = self.company.persona(persona_id)
        if persona is None:
            raise NotFound(f"пользователь {persona_id} не найден")
        return persona

    def _agent(self) -> Agent:
        if self.llm is None:
            raise AgentError("модели не настроены: нет LLM_API_KEY или LLM_BASE_URL")
        return Agent(self.llm, self.company, self.library)

    def touches(self, persona: Persona, event: Event) -> bool:
        """Дешёвая проверка без модели: есть ли у события связь с компанией.

        Фактор карты (кроме региона — у события и компании регионы не сопоставлены), канал цепочки через
        покупателей или поставщиков, или задетые участники группы с тем же фактором.
        """
        codes = {f.code for f in event.factors} - {"region"}
        exposure = self.company.exposure_map(persona.company_id)
        if any(f.code in codes and LEVEL_RANK.get(f.level, 0) >= 1 for f in exposure):
            return True
        chain = self.company.counterparty_chain(persona.company_id, event.source)
        if any(ch.kind != "group" for ch in chain.channels):
            return True
        group = self.company.group_impact(persona.company_id, event.source)
        return bool(group and any(set(m.factors) & (codes | {"direct"}) for m in group.members))

    def cached(self, key: str) -> StoredInsight | None:
        """Готовая карточка той же версии логики агента; собранная старыми промптами или моделями — нет."""
        stored = self.store.get_insight(key)
        return stored if stored is not None and stored.version == self.version else None

    def _ready(self) -> Agent:
        """Агент, которому хватит бюджета на карточку; иначе понятная ошибка до постановки в очередь."""
        agent = self._agent()
        # не начинаем карточку, которую бюджет не даст закончить: план, черновик и две доработки
        remaining = agent.llm.remaining()
        if remaining < RUN_RESERVE_RUB:
            raise BudgetExceeded(
                f"на сегодня осталось {remaining:.2f} ₽ — меньше, чем нужно на карточку"
                f" ({RUN_RESERVE_RUB:.0f} ₽); сброс в 03:00 МСК"
            )
        return agent

    def _run(self, persona: Persona, event: Event, on_stage=None) -> Insight:
        agent = self._ready()
        if not self._runs.acquire(timeout=RUN_WAIT_SECONDS):
            raise AgentError("сервис занят: собирается слишком много карточек, повторите через минуту")
        try:
            result = agent.run(persona, event, on_stage=on_stage)
        except AgentError as exc:
            if exc.trace is not None:
                self.store.save_trace(exc.trace)
            raise
        finally:
            self._runs.release()
        result.trace.insight_id = result.insight.id
        self.store.save_trace(result.trace)
        self.store.save_insight(
            event.id,
            persona.id,
            StoredInsight(
                insight=result.insight,
                context=result.context.snapshot(),
                cost_rub=result.cost,
                version=self.version,
            ),
        )
        return result.insight

    def _submit(self, persona: Persona, event: Event) -> JobStatus:
        """Сборка в фоне: одна задача на пару «событие × пользователь», статус — сразу."""
        key = insight_id(event.id, persona.id)
        active = self.jobs.get(key)
        if active is not None and active.status in ("queued", "running"):
            return active
        self._ready()  # нет моделей или бюджета — ошибка сразу, а не задача, которая упадёт

        def run(on_stage) -> str | None:
            return self._run(persona, event, on_stage=on_stage).trace_id

        return self.jobs.submit(key, event.id, persona.id, run)

    def insight(
        self, event_id: str, persona_id: str, refresh: bool = False, wait: bool = True
    ) -> Insight | JobStatus:
        """Карточка из кэша; иначе сборка — сразу (`wait=True`) или в фоне со статусом (`wait=False`)."""
        persona = self._persona(persona_id)
        key = insight_id(event_id, persona.id)
        with self._lock(key):
            active = self.jobs.get(key)
            if active is not None and active.status in ("queued", "running"):
                return active
            stored = None if refresh else self.cached(key)
            if stored is not None:
                return stored.insight
            event = self.library.get_event(event_id)
            if event is None:
                raise NotFound(f"событие {event_id} не найдено")
            if self.company.profile(persona.company_id) is None:
                raise CompanyNotFound(f"нет данных о компании {persona.company_id}")
            if not self.touches(persona, event):
                raise NotRelevant(event_id)
            return self._run(persona, event) if wait else self._submit(persona, event)

    def analyze(
        self, persona_id: str, text: str | None, url: str | None, wait: bool = True
    ) -> Insight | JobStatus:
        persona = self._persona(persona_id)
        event = self.library.parse_news(text=text, url=url)
        key = insight_id(event.id, persona.id)
        with self._lock(key):
            active = self.jobs.get(key)
            if active is not None and active.status in ("queued", "running"):
                return active
            stored = self.cached(key)
            if stored is not None:
                return stored.insight
            return self._run(persona, event) if wait else self._submit(persona, event)

    def status(self, event_id: str, persona_id: str) -> JobStatus:
        """Как идёт сборка карточки; готовая карточка без задачи (из кэша) — status=done."""
        persona = self._persona(persona_id)
        key = insight_id(event_id, persona.id)
        job = self.jobs.get(key)
        if job is not None:
            return job
        stored = self.cached(key)
        if stored is not None:
            return JobStatus(
                insight_id=key,
                event_id=event_id,
                persona_id=persona.id,
                status="done",
                trace_id=stored.insight.trace_id,
            )
        raise NotFound(f"сборка карточки {event_id} для {persona_id} не запускалась")

    def ask(self, insight_id_: str, question: str) -> AskOut:
        stored = self.cached(insight_id_)
        if stored is None:
            raise NotFound(f"инсайт {insight_id_} не найден — откройте карточку события заново")
        if self.llm is None:
            raise AgentError("модели не настроены: нет LLM_API_KEY или LLM_BASE_URL")
        ctx = from_snapshot(stored.context)
        recorder = TraceRecorder()
        recorder.trace.insight_id = insight_id_
        tools = Tools(self.company, self.library, recorder)
        try:
            out = answer(self.llm, tools, ctx, stored.insight, question)
        finally:
            self.store.save_trace(recorder.trace)
        return out


def build_service(settings, pool, repo, search=None) -> AgentService:
    """Сервис агента по настройкам API: Postgres для кэша, трасс и отзывов.

    Данные — функциями модулей профиля и поиска, если они уже в коде (`api.agent.bridges`), иначе временными
    адаптерами (`api.agent.adapters`). `search` — `SearchRepo` модуля поиска, если он подключён в API.
    """
    from api.agent.adapters import JsonlLibrary
    from api.agent.bridges import SearchLibrary, ServiceCompanyData, optional
    from api.agent.store import PgAgentStore
    from api.llm import client_from_settings

    store = PgAgentStore(pool)
    store.ensure_schema()
    company = ServiceCompanyData(
        repo,
        exposure_fn=optional("api.service", "company_exposure"),
        chain_fn=optional("api.service", "company_chain"),
        profile_fn=optional("api.service", "company_profile"),
    )
    if search is not None:
        library = SearchLibrary(
            search,
            analyze_fn=optional("api.search.analyze", "analyze_news"),
            analyze_error=optional("api.search.analyze", "AnalyzeError"),
        )
    else:
        library = JsonlLibrary(settings.data_dir / "derived", snapshot=settings.news_snapshot)
    service = AgentService(client_from_settings(settings), company, library, store)
    service.jobs.recover()  # задачи, прерванные перезапуском, — failed, а не «идёт» вечно
    return service
