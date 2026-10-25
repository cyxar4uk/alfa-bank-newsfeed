"""Кэш готовых ответов на несколько минут: лента за неделю с оценкой модели собирается до минуты, а открывают
её то с главной, то с вкладки. Один ключ считается один раз — второй запрос ждёт первый, а не зовёт модель
заново. Прогрев демо-пользователей — `api.main.warm_feeds`.
"""

import threading
import time
from collections.abc import Callable, Hashable
from typing import TypeVar

T = TypeVar("T")

TTL = 15 * 60
MAX_KEYS = 2_000


class TtlCache:
    def __init__(self, ttl: float = TTL, max_keys: int = MAX_KEYS) -> None:
        self.ttl = ttl
        self.max_keys = max_keys
        self._values: dict[Hashable, tuple[object, float]] = {}
        self._locks: dict[Hashable, threading.Lock] = {}
        self._guard = threading.Lock()

    def _fresh(self, key: Hashable) -> object | None:
        found = self._values.get(key)
        if found is not None and time.monotonic() - found[1] <= self.ttl:
            return found[0]
        return None

    def get_or_compute(self, key: Hashable, compute: Callable[[], T], refresh: bool = False) -> T:
        """Готовое значение по ключу или посчитать; `refresh` — посчитать заново (прогрев до истечения)."""
        with self._guard:
            if not refresh and (value := self._fresh(key)) is not None:
                return value  # type: ignore[return-value]
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            with self._guard:  # пока ждали — посчитал другой запрос
                if not refresh and (value := self._fresh(key)) is not None:
                    return value  # type: ignore[return-value]
            value = compute()
            with self._guard:
                if value is None:  # не нашли (404) — не храним, и замок под чужой ключ не копим
                    self._locks.pop(key, None)
                    return value
                if len(self._values) >= self.max_keys:
                    for old in list(self._values)[: self.max_keys // 10]:
                        self._values.pop(old, None)
                        self._locks.pop(old, None)
                self._values.pop(key, None)
                self._values[key] = (value, time.monotonic())
            return value

    def clear(self) -> None:
        with self._guard:
            self._values.clear()
            self._locks.clear()


FEEDS = TtlCache()
