"""Суточный счётчик расходов на модели и стоп-кран.

Лимит организаторов — 500 ₽ в сутки на ключ всей команды, сброс в 03:00 МСК. Сервис держит свой лимит ниже
(настройка `LLM_DAILY_BUDGET_RUB`): остальное нужно парсеру и отладке. Расход за сутки восстанавливается из
журнала при старте, так что перезапуск API не обнуляет счётчик.
"""

import datetime as dt
import threading
from collections.abc import Callable, Iterable

MSK = dt.timezone(dt.timedelta(hours=3))
RESET_HOUR = 3  # сутки организаторов начинаются в 03:00 МСК

# текст шлюза организаторов, когда лимит ключа исчерпан; тот же текст отдаём при своём стоп-кране
BUDGET_MESSAGE = "Budget has been exceeded"


class BudgetExceeded(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(f"{BUDGET_MESSAGE}: {detail}")
        self.detail = detail
        self.calls: list = []  # вызовы, сделанные до стоп-крана, — для трассы


def budget_day(moment: dt.datetime) -> dt.date:
    """Сутки бюджета, к которым относится момент: до 03:00 МСК — ещё вчерашние."""
    return (moment.astimezone(MSK) - dt.timedelta(hours=RESET_HOUR)).date()


class Budget:
    def __init__(
        self,
        limit_rub: float,
        now: Callable[[], dt.datetime] = lambda: dt.datetime.now(MSK),
    ) -> None:
        self.limit_rub = limit_rub
        self._now = now
        self._lock = threading.Lock()
        self._day = budget_day(now())
        self._spent = 0.0

    def restore(self, entries: Iterable[tuple[dt.datetime, float]]) -> None:
        """Учесть уже сделанные сегодня вызовы (момент, стоимость) — из журнала."""
        with self._lock:
            self._roll()
            self._spent += sum(cost for at, cost in entries if budget_day(at) == self._day)

    def _roll(self) -> None:
        day = budget_day(self._now())
        if day != self._day:
            self._day, self._spent = day, 0.0

    @property
    def spent(self) -> float:
        with self._lock:
            self._roll()
            return self._spent

    @property
    def remaining(self) -> float:
        return max(self.limit_rub - self.spent, 0.0)

    def check(self) -> None:
        """Перед вызовом: лимит исчерпан — BudgetExceeded, вызова не будет."""
        with self._lock:
            self._roll()
            if self._spent >= self.limit_rub:
                raise BudgetExceeded(
                    f"за сутки потрачено {self._spent:.2f} ₽ из {self.limit_rub:.2f} ₽, сброс в 03:00 МСК"
                )

    def add(self, cost: float) -> None:
        with self._lock:
            self._roll()
            self._spent += cost

    def exhaust(self) -> None:
        """Шлюз сам сказал, что бюджет ключа исчерпан: до сброса больше не пытаемся."""
        with self._lock:
            self._roll()
            self._spent = max(self._spent, self.limit_rub)
