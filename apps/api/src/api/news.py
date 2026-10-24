"""Откуда лента берёт новости: база поиска (`app.state.search`) или снимок `data/demo/news_snapshot.jsonl`.

Снимок — запасной путь, когда базы новостей нет (запуск без сети, проверка жюри): сценарий не ломается.
"""

import datetime as dt
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from api.ranking import NewsEvent, event_from

logger = logging.getLogger("api.news")


class NewsProvider(Protocol):
    name: str

    def events(self, since: dt.datetime | None, limit: int) -> list[NewsEvent]: ...

    def has_bank_view(self, factors: list[str]) -> bool: ...

    def event(self, event_id: str) -> NewsEvent | None: ...


@lru_cache(maxsize=4)
def _snapshot(path: str, mtime: float) -> tuple[NewsEvent, ...]:
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(event_from(json.loads(line)))
            except (ValueError, TypeError):
                continue  # битая строка снимка не роняет ленту
    events.sort(key=lambda e: e.published_at or dt.datetime.min.replace(tzinfo=dt.UTC), reverse=True)
    return tuple(events)


class SnapshotNews:
    """Новости из JSONL-снимка парсера; позиции банка в снимке нет."""

    name = "снимок data/demo/news_snapshot.jsonl"

    def __init__(self, path: Path) -> None:
        self.path = path

    def events(self, since: dt.datetime | None, limit: int) -> list[NewsEvent]:
        items = _snapshot(str(self.path), self.path.stat().st_mtime)
        if since is not None:
            items = tuple(e for e in items if e.published_at and e.published_at >= since)
        return list(items[:limit])

    def has_bank_view(self, factors: list[str]) -> bool:
        return False

    def event(self, event_id: str) -> NewsEvent | None:
        items = _snapshot(str(self.path), self.path.stat().st_mtime)
        return next((e for e in items if e.id == event_id), None)


class SearchNews:
    """Новости и аналитика банка из базы поиска (`api.search.repo.SearchRepo`)."""

    name = "база новостей"
    PAGE = 50  # больше поиск за раз не отдаёт

    def __init__(self, search: Any) -> None:
        self.search = search
        self._bank: dict[tuple[str, ...], bool] = {}

    def events(self, since: dt.datetime | None, limit: int) -> list[NewsEvent]:
        result: list[NewsEvent] = []
        offset = 0
        while len(result) < limit:
            page = self.search.list_news(
                since=since, limit=min(self.PAGE, limit - len(result)), offset=offset
            )
            result.extend(event_from(item) for item in page.items)
            offset += len(page.items)
            if not page.items or offset >= page.total:
                break
        return result

    def has_bank_view(self, factors: list[str]) -> bool:
        """Есть ли аналитика банка хотя бы по одному из факторов, которыми событие задевает компанию."""
        codes = tuple(sorted(set(factors)))
        if not codes:
            return False
        if codes not in self._bank:
            try:
                self._bank[codes] = bool(self.search.search_alfa_analytics("", factors=list(codes), limit=1))
            except Exception:
                self._bank[codes] = False  # нет аналитики или фактор неизвестен поиску — бонуса нет
        return self._bank[codes]

    def event(self, event_id: str) -> NewsEvent | None:
        if not event_id.startswith("src:news:"):
            return None
        item = self.search.get_source(event_id)
        return event_from(item) if item is not None else None


class FallbackNews:
    """База новостей, а если в ней пусто — снимок: лента не пустеет, пока новости не загружены."""

    def __init__(self, primary: NewsProvider, fallback: NewsProvider | None) -> None:
        self.primary = primary
        self.fallback = fallback
        self.name = primary.name
        self._used = primary

    def events(self, since: dt.datetime | None, limit: int) -> list[NewsEvent]:
        events = self.primary.events(since, limit)
        if not events and self.fallback is not None:
            events = self.fallback.events(since, limit)
            self._used, self.name = self.fallback, f"{self.fallback.name} (в базе новостей пусто)"
        return events

    def has_bank_view(self, factors: list[str]) -> bool:
        return self._used.has_bank_view(factors)

    def event(self, event_id: str) -> NewsEvent | None:
        try:
            found = self.primary.event(event_id)
        except Exception:
            # база новостей недоступна — ищем в снимке; причину — в журнал, чтобы не прятать ошибки кода
            logger.warning("событие %s не прочитано из базы новостей", event_id, exc_info=True)
            found = None
        if found is None and self.fallback is not None:
            found = self.fallback.event(event_id)
        return found
