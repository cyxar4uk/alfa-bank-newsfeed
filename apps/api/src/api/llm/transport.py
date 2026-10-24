"""Транспорт к OpenAI-совместимому API организаторов. Отдельно от клиента — в тестах его заменяет подделка."""

from dataclasses import dataclass
from typing import Protocol

import httpx


class TransportError(RuntimeError):
    """Нет ответа: сеть, таймаут, обрыв соединения.

    `before_send` — запрос точно не ушёл (не удалось соединиться): повтор безопасен. Иначе запрос мог дойти до
    модели и быть оплачен.
    """

    def __init__(self, message: str, before_send: bool = True) -> None:
        super().__init__(message)
        self.before_send = before_send


@dataclass
class TransportResponse:
    status: int
    data: dict | None  # разобранный JSON ответа; None — ответ не JSON
    text: str  # тело ответа как есть, для текста ошибки


class Transport(Protocol):
    def post(self, body: dict) -> TransportResponse: ...


class HttpTransport:
    """POST /chat/completions. Ключ живёт только в заголовке и никуда не выводится."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 180.0) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._client = httpx.Client(timeout=timeout)

    def post(self, body: dict) -> TransportResponse:
        try:
            resp = self._client.post(self._url, headers=self._headers, json=body)
        except httpx.HTTPError as exc:
            # наружу — только тип ошибки, без текста исключения и заголовков запроса
            before_send = isinstance(exc, httpx.ConnectError | httpx.ConnectTimeout | httpx.PoolTimeout)
            raise TransportError(type(exc).__name__, before_send=before_send) from exc
        try:
            data = resp.json()
        except ValueError:
            data = None
        return TransportResponse(
            status=resp.status_code, data=data if isinstance(data, dict) else None, text=resp.text
        )

    def close(self) -> None:
        self._client.close()
