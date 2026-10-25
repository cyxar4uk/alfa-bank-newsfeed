"""Один уровень события на всех экранах: лента «За день», «За неделю», сюжеты, поиск и карточка разбора.

Уровень act / watch / info зависит от оценки, а оценка — от того, в какую пачку событие попало к модели
(верх дневной ленты и верх недели — разные десятки). Поэтому уровень, однажды показанный пользователю,
запоминается на несколько часов: следующая лента с тем же событием пишет вывод под него, а карточка берёт его
через `event_level` («Важно» в ленте не становится «Следить» в разборе).
"""

import threading
import time

from api.contract import ExposureMap, Feed
from api.takeaway import takeaway

TTL = 6 * 3600  # данные и оценки модели обновляются не чаще — дольше держать уровень незачем
MAX_EVENTS = 50_000


class EventLevels:
    def __init__(self, ttl: float = TTL, max_events: int = MAX_EVENTS) -> None:
        self.ttl = ttl
        self.max_events = max_events
        self._levels: dict[tuple[str, str], tuple[str, float]] = {}
        self._lock = threading.Lock()

    def get(self, persona: str, event_id: str) -> str | None:
        with self._lock:
            found = self._levels.get((persona, event_id))
            if found is None:
                return None
            level, at = found
            if time.monotonic() - at > self.ttl:
                del self._levels[(persona, event_id)]
                return None
            return level

    def _put(self, persona: str, event_id: str, level: str) -> None:
        with self._lock:
            if len(self._levels) >= self.max_events:
                # самые старые — первыми: словарь хранит порядок вставки
                for key in list(self._levels)[: self.max_events // 10]:
                    del self._levels[key]
            self._levels[(persona, event_id)] = (level, time.monotonic())

    def pin(self, feed: Feed, exposure: ExposureMap | None, remember: bool = True) -> Feed:
        """Привести уровни ленты к уже показанным; новые — запомнить (`remember=False` — только привести:
        поиск оценивает без модели и не должен задавать уровень ленте)."""
        used = {i.takeaway.text for i in feed.items if i.takeaway}
        for item in feed.items:
            if item.takeaway is None:
                continue
            known = self.get(feed.persona_id, item.event_id)
            if known is None:
                if remember:
                    self._put(feed.persona_id, item.event_id, item.takeaway.level)
            elif known != item.takeaway.level and item.relevance.breakdown:
                used.discard(item.takeaway.text)
                item.takeaway = takeaway(item, feed.role, exposure, used, level=known)
                used.add(item.takeaway.text)
        return feed

    def clear(self) -> None:
        with self._lock:
            self._levels.clear()


LEVELS = EventLevels()


def event_level(persona: str, event_id: str) -> str | None:
    """Уровень события, который пользователь видел в ленте, — для вердикта карточки; не видел — None."""
    return LEVELS.get(persona, event_id)
