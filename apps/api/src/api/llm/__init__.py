"""Клиент разрешённых моделей: один на всё приложение.

Модель выбирается по шагу из конфига, ответ в JSON проверяется по Pydantic-схеме, одинаковые запросы берутся
из кэша на диске, каждый вызов пишется в журнал, суточный расход ограничен стоп-краном.
"""

from api.llm.budget import Budget, BudgetExceeded
from api.llm.cache import DiskCache
from api.llm.client import (
    ALLOWED_MODELS,
    DEFAULT_STEP_MODELS,
    CallRecord,
    Completion,
    LlmBadResponse,
    LlmClient,
    LlmError,
    LlmUnavailable,
    client_from_settings,
)
from api.llm.journal import Journal
from api.llm.transport import HttpTransport, Transport, TransportError, TransportResponse

__all__ = [
    "ALLOWED_MODELS",
    "DEFAULT_STEP_MODELS",
    "Budget",
    "BudgetExceeded",
    "CallRecord",
    "Completion",
    "DiskCache",
    "HttpTransport",
    "Journal",
    "LlmBadResponse",
    "LlmClient",
    "LlmError",
    "LlmUnavailable",
    "Transport",
    "TransportError",
    "TransportResponse",
    "client_from_settings",
]
