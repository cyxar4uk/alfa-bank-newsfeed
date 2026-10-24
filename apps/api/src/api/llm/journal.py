"""Журнал вызовов моделей: строка JSON на вызов — шаг, модель, токены, стоимость, из кэша или нет.

Ключ и тексты запросов в журнал не пишутся.
"""

import datetime as dt
import json
import threading
from collections.abc import Iterator
from pathlib import Path


class Journal:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._lock = threading.Lock()

    def write(self, entry: dict) -> None:
        if self.path is None:
            return
        line = json.dumps(entry, ensure_ascii=False)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def entries(self) -> Iterator[dict]:
        if self.path is None or not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue

    def spending(self) -> Iterator[tuple[dt.datetime, float]]:
        """(момент, стоимость) платных вызовов — для восстановления суточного счётчика."""
        for entry in self.entries():
            cost = entry.get("cost") or 0.0
            if entry.get("cached") or not cost:
                continue
            try:
                yield dt.datetime.fromisoformat(entry["at"]), float(cost)
            except (KeyError, ValueError, TypeError):
                continue
