"""Разбор заранее: агент собирает карточку до того, как пользователь открыл новость.

Раз в цикл планировщик берёт ленту демо-пользователей (та же, что на экране, из кэша лент), выбирает события
с уровнем «важно» — и «следить», пока потрачено меньше половины бюджета, — которых ещё нет в кэше карточек,
и ставит их в очередь сборки агента по убыванию оценки. Новые события парсера попадают в ленту и так
доходят до очереди в следующем цикле; первый цикл после старта — прогрев демо после выкатки.

Лимиты: свой суточный бюджет (`PRECOMPUTE_BUDGET_RUB`, сутки — как у ключа, с 03:00 МСК), не больше
`PRECOMPUTE_PER_HOUR` сборок в час и `PRECOMPUTE_IN_FLIGHT` одновременно (остальные места очереди агента —
пользователям). Готовое из кэша не повторяется; бюджет кончился — планировщик ждёт новых суток.
Выключатель — `PRECOMPUTE_ENABLED`. Файлы агента не меняются: только его `insight`, `cached`, `jobs`.
"""

import datetime as dt
import logging
import threading
import time
from collections import deque
from collections.abc import Callable

from pydantic import BaseModel, Field

from api.agent.loop import insight_id
from api.contract import Feed
from api.llm.budget import BudgetExceeded, budget_day
from api.ranking import MSK

log = logging.getLogger("api.precompute")

RESERVE_RUB = (
    3.0  # дороже карточка не выходила (api.agent.service.RUN_RESERVE_RUB): не начинаем, если не хватит
)


class PrecomputeStatus(BaseModel):
    """Состояние планировщика разборов заранее — для трассы и метрик."""

    enabled: bool
    running: bool = Field(description="поток планировщика жив")
    day: dt.date = Field(description="сутки бюджета (с 03:00 МСК)")
    budget_rub: float
    spent_rub: float = Field(description="потрачено на разборы заранее за эти сутки")
    per_hour: int
    built_hour: int = Field(description="поставлено в очередь за последний час")
    queued: int = Field(description="сейчас в очереди или собирается")
    built: int = Field(description="собрано заранее за сутки")
    cache_hits: int = Field(description="кандидат уже был в кэше карточек — не собирали повторно")
    failed: int
    skipped_budget: int = Field(description="не поставлено: кончился бюджет или часовой лимит")
    last_cycle_at: dt.datetime | None = None
    stopped: str | None = Field(default=None, description="почему не ставит новые: бюджет, лимит, нет агента")


class Precompute:
    def __init__(
        self,
        agent,
        personas: list[str],
        feed_for: Callable[[str], Feed | None],
        budget_rub: float = 100.0,
        per_hour: int = 20,
        in_flight: int = 2,
        watch: bool = True,
        enabled: bool = True,
        clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(MSK),
    ) -> None:
        self.agent = agent
        self.personas = personas
        self.feed_for = feed_for
        self.budget_rub = budget_rub
        self.per_hour = per_hour
        self.in_flight = in_flight
        self.watch = watch
        self.enabled = enabled
        self.clock = clock
        self._lock = threading.Lock()
        self._day = budget_day(clock())
        self._pending: dict[str, str] = {}  # insight_id → persona: поставлены, ждём готовности
        self._done: set[str] = set()  # собрано, уже было в кэше или не касается — больше не ставим
        self._hour: deque[float] = deque()
        self._spent = 0.0
        self.built = self.cache_hits = self.failed = self.skipped_budget = 0
        self.last_cycle_at: dt.datetime | None = None
        self.stopped: str | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # --- сутки и учёт -------------------------------------------------------------------------------

    def _roll_day(self) -> None:
        day = budget_day(self.clock())
        if day != self._day:
            self._day, self._spent = day, 0.0
            self.built = self.cache_hits = self.failed = self.skipped_budget = 0
            self._done.clear()  # новые сутки: и карточки новой версии агента можно собрать заново

    def _collect(self) -> None:
        """Забрать итоги поставленных сборок: стоимость готовых — в бюджет, упавшие — в счётчик."""
        for key, persona in list(self._pending.items()):
            job = self.agent.jobs.get(key)
            if job is not None and job.status in ("queued", "running"):
                continue
            del self._pending[key]
            self._done.add(key)
            stored = self.agent.cached(key, persona)
            if stored is not None:
                self.built += 1
                self._spent += stored.cost_rub or 0.0
            else:
                self.failed += 1

    def _hourly(self) -> int:
        now = time.monotonic()
        while self._hour and now - self._hour[0] > 3600:
            self._hour.popleft()
        return len(self._hour)

    # --- выбор и постановка -------------------------------------------------------------------------

    def candidates(self) -> list[tuple[float, str, str]]:
        """(оценка, событие, пользователь) по убыванию: «важно», при свободном бюджете и «следить»."""
        levels = {"act"} | ({"watch"} if self.watch and self._spent < self.budget_rub / 2 else set())
        found = []
        for persona in self.personas:
            try:
                feed = self.feed_for(persona)
            except Exception:
                log.warning("лента %s для разборов заранее не собрана", persona, exc_info=True)
                continue
            for item in feed.items if feed else []:
                if item.takeaway is not None and item.takeaway.level in levels:
                    found.append((item.relevance.score, item.event_id, persona))
        return sorted(found, key=lambda c: -c[0])

    def cycle(self) -> None:
        """Один проход: итоги прошлых сборок, затем новые постановки в пределах лимитов."""
        with self._lock:
            self._roll_day()
            self.last_cycle_at = self.clock()
            if not self.enabled:
                self.stopped = "выключено (PRECOMPUTE_ENABLED=false)"
                return
            if self.agent is None or getattr(self.agent, "llm", None) is None:
                self.stopped = "агент или модели не настроены"
                return
            self._collect()
            self.stopped = None
            for _, event_id, persona in self.candidates():
                key = insight_id(event_id, persona)
                if key in self._done or key in self._pending:
                    continue
                if self.agent.cached(key, persona) is not None:
                    self._done.add(key)
                    self.cache_hits += 1
                    continue
                # поставленные, но ещё не собранные — тоже в счёт: каждая может стоить до RESERVE_RUB
                if self._spent + RESERVE_RUB * (len(self._pending) + 1) > self.budget_rub:
                    self.stopped = f"бюджет разборов заранее {self.budget_rub:.0f} ₽ на сутки исчерпан"
                    self.skipped_budget += 1
                    break
                if self._hourly() >= self.per_hour:
                    self.stopped = f"лимит {self.per_hour} разборов в час"
                    self.skipped_budget += 1
                    break
                if len(self._pending) >= self.in_flight:
                    break  # остальные места очереди агента — пользователям; продолжим в следующем цикле
                self._submit(key, event_id, persona)

    def _submit(self, key: str, event_id: str, persona: str) -> None:
        try:
            result = self.agent.insight(event_id, persona, wait=False)
        except Exception as exc:  # не касается, нет события, кончился общий бюджет — больше не ставим
            self._done.add(key)
            if isinstance(exc, BudgetExceeded):
                self.stopped = f"общий бюджет моделей: {exc}"
            log.info("разбор заранее %s для %s не поставлен: %s", event_id, persona, exc)
            return
        if getattr(result, "status", None) in ("queued", "running"):
            self._pending[key] = persona
            self._hour.append(time.monotonic())
        else:  # карточка уже готова (собрал пользователь между проверками)
            self._done.add(key)
            self.cache_hits += 1

    # --- состояние и поток --------------------------------------------------------------------------

    def queued(self, event_id: str, persona: str) -> bool:
        """Сборка этой пары идёт или ждёт в очереди агента (поставил планировщик или пользователь)."""
        if self.agent is None:
            return False
        job = self.agent.jobs.get(insight_id(event_id, persona))
        return job is not None and job.status in ("queued", "running")

    def status(self) -> PrecomputeStatus:
        with self._lock:
            self._roll_day()
            return PrecomputeStatus(
                enabled=self.enabled,
                running=bool(self._thread and self._thread.is_alive()),
                day=self._day,
                budget_rub=self.budget_rub,
                spent_rub=round(self._spent, 2),
                per_hour=self.per_hour,
                built_hour=self._hourly(),
                queued=len(self._pending),
                built=self.built,
                cache_hits=self.cache_hits,
                failed=self.failed,
                skipped_budget=self.skipped_budget,
                last_cycle_at=self.last_cycle_at,
                stopped=self.stopped,
            )

    def start(self, every: float) -> None:
        def loop() -> None:
            while not self._stop.is_set():
                try:
                    self.cycle()
                except Exception:  # планировщик — не работа API: сбой цикла не роняет поток
                    log.exception("цикл разборов заранее не удался")
                self._stop.wait(every)

        self._thread = threading.Thread(target=loop, name="precompute", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
