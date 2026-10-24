"""Кэш ответов модели на диске: файл на запрос, имя — хэш запроса."""

import hashlib
import json
import os
import threading
import uuid
from pathlib import Path


def request_key(payload: dict) -> str:
    """Хэш канонического JSON запроса: модель, сообщения, параметры, схема ответа."""
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DiskCache:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _path(self, key: str) -> Path:
        return self.directory / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict | None:
        path = self._path(key)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # нет файла или он повреждён — считаем, что в кэше нет
            return None

    def put(self, key: str, value: dict) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # своё имя у каждого потока и процесса: параллельные одинаковые запросы не мешают друг другу
        tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        # атомарная замена: параллельный читатель не увидит половину файла
        os.replace(tmp, path)
