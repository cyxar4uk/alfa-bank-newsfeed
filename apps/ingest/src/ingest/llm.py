"""Клиент OpenAI-совместимого API организаторов. Каждый вызов пишется в журнал: модель, цель, токены, стоимость.

Настройки — из окружения: `LLM_API_KEY`, `LLM_BASE_URL` (адрес зависит от машины, поэтому только настройкой).
Ключ никуда не выводится и в журнал не попадает.
"""

import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx

from ingest.news.normalize import MSK


class LlmUnavailable(RuntimeError):
    pass


@dataclass
class ChatResult:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost: float | None


class LlmClient:
    def __init__(self, api_key: str, base_url: str, journal: Path | None = None, timeout: float = 180.0):
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.journal = journal
        self.timeout = timeout
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, journal: Path | None = None) -> "LlmClient":
        key, url = os.environ.get("LLM_API_KEY"), os.environ.get("LLM_BASE_URL")
        if not key or not url:
            raise LlmUnavailable("не заданы LLM_API_KEY и LLM_BASE_URL")
        return cls(key, url, journal)

    def chat(
        self,
        model: str,
        messages: list[dict],
        purpose: str,
        max_tokens: int = 2000,
        temperature: float = 0.0,
        json_mode: bool = False,
    ) -> ChatResult:
        body: dict = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        started = time.monotonic()
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=body,
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise LlmUnavailable(f"нет ответа от модели: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            # текст ошибки сервера без заголовков запроса — ключа в нём нет
            raise LlmUnavailable(f"модель ответила {resp.status_code}: {resp.text[:300]}")
        try:
            data = resp.json()
            usage = data.get("usage") or {}
            result = ChatResult(
                text=data["choices"][0]["message"].get("content") or "",
                model=data.get("model", model),
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                cost=usage.get("cost"),
            )
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            # шлюз ответил 200, но без ответа модели — например, {"error": {"message": "budget exceeded"}}
            raise LlmUnavailable(f"непонятный ответ модели: {resp.text[:300]}") from exc
        self._log(purpose, result, time.monotonic() - started)
        return result

    def _log(self, purpose: str, result: ChatResult, seconds: float) -> None:
        if self.journal is None:
            return
        entry = {
            "at": datetime.now(MSK).isoformat(timespec="seconds"),
            "purpose": purpose,
            "model": result.model,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "cost": result.cost,
            "seconds": round(seconds, 1),
        }
        with self._lock:
            self.journal.parent.mkdir(parents=True, exist_ok=True)
            with self.journal.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
