"""Один клиент на все вызовы моделей.

- модель — по шагу (`plan`, `draft`, …) из конфига, только из списка разрешённых кейсом;
- повторы при сетевых ошибках, 429 и 5xx — с нарастающей паузой;
- ответ в JSON по Pydantic-схеме: невалидный ответ возвращается модели с текстом ошибки валидации;
- кэш на диске по хэшу запроса — повторный одинаковый запрос бесплатный;
- журнал каждого вызова и суточный стоп-кран.
"""

import datetime as dt
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

from api.llm.budget import BUDGET_MESSAGE, MSK, Budget, BudgetExceeded
from api.llm.cache import DiskCache, request_key
from api.llm.journal import Journal
from api.llm.transport import Transport, TransportError, TransportResponse

ALLOWED_MODELS = frozenset(
    {
        "google/gemma-4-26b-a4b-it",
        "z-ai/glm-5.3-flash",
        "qwen/qwen3.6-35b-a3b",
        "deepseek/deepseek-v4.1-flash",
        "qwen/qwen3-vl-30b-a3b-instruct",
        "moonshotai/kimi-k2.6",
    }
)

# шаг → модель; переопределяется настройкой LLM_MODELS (JSON), обоснование — в decisions.md команды
DEFAULT_STEP_MODELS: dict[str, str] = {
    "plan": "google/gemma-4-26b-a4b-it",
    "draft": "deepseek/deepseek-v4.1-flash",
    "check": "google/gemma-4-26b-a4b-it",
    "revise": "deepseek/deepseek-v4.1-flash",
    "ask": "deepseek/deepseek-v4.1-flash",
    "parse": "google/gemma-4-26b-a4b-it",
}

# доп. параметры запроса по шагу: у DeepSeek рассуждения выключаются, ответ в 3–5 раз дешевле и быстрее
DEFAULT_STEP_PARAMS: dict[str, dict] = {}

# модель недоступна у провайдера после всех повторов — один раз пробуем запасную того же класса
DEFAULT_FALLBACK_MODELS: dict[str, str] = {
    "google/gemma-4-26b-a4b-it": "qwen/qwen3.6-35b-a3b",
    "qwen/qwen3.6-35b-a3b": "google/gemma-4-26b-a4b-it",
    "deepseek/deepseek-v4.1-flash": "z-ai/glm-5.3-flash",
    "z-ai/glm-5.3-flash": "deepseek/deepseek-v4.1-flash",
}

RETRY_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
MAX_TOKENS_CAP = 16000


class LlmError(RuntimeError):
    """Модель не дала ответа, которым можно пользоваться. `calls` — уже сделанные (и оплаченные) вызовы."""

    calls: list["CallRecord"]

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.calls = []


class LlmUnavailable(LlmError):
    """Сеть, таймаут или ошибка шлюза — после всех повторов."""


class LlmBadResponse(LlmError):
    """Ответ так и не прошёл проверку схемой."""


@dataclass
class CallRecord:
    """Один вызов модели (или попадание в кэш) — для журнала и трассы агента."""

    step: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cost: float = 0.0
    cached: bool = False
    seconds: float = 0.0
    attempt: int = 1
    ok: bool = True
    error: str | None = None


@dataclass
class Completion[T: BaseModel]:
    text: str
    value: T | None
    model: str
    calls: list[CallRecord] = field(default_factory=list)

    @property
    def cost(self) -> float:
        return sum(c.cost for c in self.calls)

    @property
    def cached(self) -> bool:
        return bool(self.calls) and all(c.cached for c in self.calls)

    @property
    def tokens_in(self) -> int:
        return sum(c.prompt_tokens for c in self.calls)

    @property
    def tokens_out(self) -> int:
        return sum(c.completion_tokens for c in self.calls)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def extract_json(text: str) -> str:
    """JSON-объект из ответа: без рассуждений в <think>, без ограды ```json и текста вокруг."""
    text = _THINK.sub("", text).strip()
    text = _FENCE.sub("", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        return text
    return text[start : end + 1]


def schema_instruction(schema: type[BaseModel]) -> str:
    compact = json.dumps(schema.model_json_schema(), ensure_ascii=False, separators=(",", ":"))
    return "Ответ — только один JSON-объект по этой JSON Schema, без пояснений и без markdown:\n" + compact


def _is_budget_error(resp: TransportResponse) -> bool:
    """Шлюз отказал из-за бюджета ключа. Смотрим только ответ-ошибку: в успешном ответе эта фраза может быть
    текстом модели (например, цитатой из новости) и не должна останавливать сервис."""
    if resp.status == 200 and _first_choice(resp) is not None:
        return False
    error = (resp.data or {}).get("error")
    message = error.get("message") if isinstance(error, dict) else error
    text = message if isinstance(message, str) else resp.text
    return BUDGET_MESSAGE.lower() in text.lower()


class LlmClient:
    def __init__(
        self,
        transport: Transport,
        *,
        budget: Budget,
        journal: Journal | None = None,
        cache: DiskCache | None = None,
        models: dict[str, str] | None = None,
        step_params: dict[str, dict] | None = None,
        fallbacks: dict[str, str] | None = None,
        max_attempts: int = 4,
        validation_attempts: int = 2,
        backoff: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], dt.datetime] = lambda: dt.datetime.now(MSK),
    ) -> None:
        self.transport = transport
        self.budget = budget
        self.journal = journal or Journal(None)
        self.cache = cache
        self.models = {**DEFAULT_STEP_MODELS, **(models or {})}
        self.step_params = {**DEFAULT_STEP_PARAMS, **(step_params or {})}
        # None — запасные по умолчанию, {} — без запасных
        self.fallbacks = dict(DEFAULT_FALLBACK_MODELS if fallbacks is None else fallbacks)
        unknown = {m for m in [*self.models.values(), *self.fallbacks.values()] if m not in ALLOWED_MODELS}
        if unknown:
            raise ValueError(f"модели не из списка кейса: {', '.join(sorted(unknown))}")
        self.max_attempts = max_attempts
        self.validation_attempts = validation_attempts
        self.backoff = backoff
        self._sleep = sleep
        self._now = now

    def model_for(self, step: str) -> str:
        return self.models.get(step) or self.models["draft"]

    def complete[T: BaseModel](
        self,
        step: str,
        messages: list[dict],
        *,
        schema: type[T] | None = None,
        max_tokens: int = 4000,
        temperature: float = 0.0,
        model: str | None = None,
        use_cache: bool = True,
    ) -> Completion[T]:
        """Вызвать модель шага. Со `schema` — вернуть проверенный объект или поднять LlmBadResponse."""
        model = model or self.model_for(step)
        if model not in ALLOWED_MODELS:
            raise ValueError(f"модель {model} не из списка кейса")
        messages = list(messages)
        if schema is not None:
            messages = [{"role": "system", "content": schema_instruction(schema)}, *messages]
        body: dict = {
            **self.step_params.get(step, {}),
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if schema is not None:
            body["response_format"] = {"type": "json_object"}
        key = request_key(body)

        calls: list[CallRecord] = []
        if use_cache and self.cache is not None:
            hit = self.cache.get(key)
            if hit is not None:
                parsed = self._parse(hit.get("text", ""), schema)
                if not isinstance(parsed, str):
                    record = CallRecord(step=step, model=hit.get("model", model), cached=True)
                    self._log(record)
                    return Completion(text=hit["text"], value=parsed, model=record.model, calls=[record])

        conversation = list(messages)
        last_error = ""
        fell_back = False
        for attempt in range(1, self.validation_attempts + 2):
            attempt_body = {**body, "messages": conversation}
            try:
                try:
                    text, record, finish = self._call(step, attempt_body, attempt)
                except LlmUnavailable:
                    fallback = self.fallbacks.get(body["model"])
                    if fallback is None or fell_back:
                        raise
                    fell_back = True
                    self._log(
                        CallRecord(
                            step=step,
                            model=body["model"],
                            attempt=attempt,
                            ok=False,
                            error=f"модель недоступна — запрос уходит на запасную {fallback}",
                        )
                    )
                    # параметры шага настроены под основную модель (например, выключение рассуждений DeepSeek)
                    own = self.step_params.get(step, {})
                    body = {k: v for k, v in body.items() if k not in own} | {"model": fallback}
                    attempt_body = {**body, "messages": conversation}
                    text, record, finish = self._call(step, attempt_body, attempt)
            except (LlmError, BudgetExceeded) as exc:
                exc.calls = calls
                raise
            calls.append(record)
            parsed = self._parse(text, schema)
            if not isinstance(parsed, str):
                self._log(record)
                if use_cache and self.cache is not None:
                    try:
                        self.cache.put(key, {"text": text, "model": record.model})
                    except OSError:
                        pass  # кэш — ускорение, а не условие ответа: ответ уже оплачен, отдаём его
                return Completion(text=text, value=parsed, model=record.model, calls=calls)
            # ответ не прошёл схему — отмечаем в журнале и просим исправить, показав ошибку
            last_error = parsed
            record.ok, record.error = False, "ответ не прошёл схему: " + last_error[:300]
            self._log(record)
            if finish == "length":
                body["max_tokens"] = min(body["max_tokens"] * 2, MAX_TOKENS_CAP)
            conversation = [
                *messages,
                {"role": "assistant", "content": text or "(пустой ответ)"},
                {
                    "role": "user",
                    "content": (
                        "Ответ не прошёл проверку по схеме:\n"
                        + last_error
                        + "\nВерни исправленный JSON целиком по той же схеме, без пояснений."
                    ),
                },
            ]
        error = LlmBadResponse(
            f"ответ модели {body['model']} на шаге {step} не прошёл проверку: {last_error[:500]}"
        )
        error.calls = calls
        raise error

    def _parse[T: BaseModel](self, text: str, schema: type[T] | None) -> T | None | str:
        """Объект схемы (или None без схемы) — либо строка с ошибкой для модели."""
        if schema is None:
            return None if text.strip() else "пустой ответ"
        raw = extract_json(text)
        if not raw:
            return "пустой ответ: нужен JSON-объект"
        try:
            return schema.model_validate_json(raw)
        except ValidationError as exc:
            return _validation_text(exc)
        except ValueError as exc:
            return f"не JSON: {exc}"

    def _call(self, step: str, body: dict, attempt: int) -> tuple[str, CallRecord, str | None]:
        """Один запрос с повторами при временных ошибках. Возвращает текст, запись журнала и finish_reason."""
        model = body["model"]
        error = ""
        lost = 0  # обрывы после отправки: запрос мог дойти и быть оплачен — повторяем только один раз
        for n in range(1, self.max_attempts + 1):
            self.budget.check()
            started = time.monotonic()
            try:
                resp = self.transport.post(body)
            except TransportError as exc:
                error = f"нет ответа от модели: {exc}"
                self._log(CallRecord(step=step, model=model, attempt=attempt, ok=False, error=error))
                if not exc.before_send:
                    lost += 1
                    if lost > 1:
                        break
                self._pause(n)
                continue
            seconds = round(time.monotonic() - started, 2)
            if _is_budget_error(resp):
                self.budget.exhaust()
                self._log(CallRecord(step=step, model=model, attempt=attempt, ok=False, error=BUDGET_MESSAGE))
                raise BudgetExceeded("лимит ключа у организаторов исчерпан, сброс в 03:00 МСК")
            choice = _first_choice(resp)
            if resp.status != 200 or choice is None:
                # тело ошибки шлюза — только в журнал на сервере (ключа в нём нет); наружу — код ответа
                self._log(
                    CallRecord(
                        step=step,
                        model=model,
                        attempt=attempt,
                        ok=False,
                        error=f"модель ответила {resp.status}: {resp.text[:300]}",
                    )
                )
                error = f"модель ответила с кодом {resp.status}"
                if resp.status in RETRY_STATUSES or (resp.status == 200 and choice is None):
                    self._pause(n)
                    continue
                raise LlmUnavailable(error)
            usage = (resp.data or {}).get("usage") or {}
            details = usage.get("completion_tokens_details") or {}
            record = CallRecord(
                step=step,
                model=(resp.data or {}).get("model") or model,
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                reasoning_tokens=int(details.get("reasoning_tokens") or 0),
                cost=float(usage.get("cost") or 0.0),
                seconds=seconds,
                attempt=attempt,
            )
            if usage.get("cost") is None:
                # без usage.cost счётчик не видит расход — помечаем в журнале, чтобы это было заметно
                record.error = "в ответе нет usage.cost — расход не учтён"
            # деньги учитываем сразу; в журнал запись попадёт после проверки ответа (ok или ошибка схемы)
            self.budget.add(record.cost)
            message = choice.get("message") or {}
            return message.get("content") or "", record, choice.get("finish_reason")
        raise LlmUnavailable(error or "модель не ответила")

    def _pause(self, n: int) -> None:
        if n < self.max_attempts:
            self._sleep(self.backoff * 2 ** (n - 1))

    def _log(self, record: CallRecord) -> None:
        entry = {
            "at": self._now().isoformat(timespec="seconds"),
            "step": record.step,
            "model": record.model,
            "prompt_tokens": record.prompt_tokens,
            "completion_tokens": record.completion_tokens,
            "reasoning_tokens": record.reasoning_tokens,
            "cost": round(record.cost, 6),
            "cached": record.cached,
            "seconds": record.seconds,
            "attempt": record.attempt,
            "ok": record.ok,
        }
        if record.error:
            entry["error"] = record.error
        self.journal.write(entry)


def _first_choice(resp: TransportResponse) -> dict | None:
    choices = (resp.data or {}).get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        return choices[0]
    return None


def _validation_text(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors()[:12]:
        where = ".".join(str(p) for p in err.get("loc", ())) or "(корень)"
        lines.append(f"- {where}: {err.get('msg')}")
    return "\n".join(lines)


def client_from_settings(settings) -> "LlmClient | None":
    """Клиент по настройкам API; нет ключа или адреса — None (агент недоступен, остальное API работает)."""
    from api.llm.transport import HttpTransport

    key = settings.llm_api_key.get_secret_value().strip() if settings.llm_api_key else ""
    if not key or not settings.llm_base_url:
        return None
    journal = Journal(settings.llm_journal)
    budget = Budget(settings.llm_daily_budget_rub)
    budget.restore(journal.spending())
    return LlmClient(
        HttpTransport(settings.llm_base_url, key, settings.llm_timeout),
        budget=budget,
        journal=journal,
        cache=DiskCache(settings.llm_cache_dir),
        models=settings.llm_models,
        step_params=settings.llm_step_params,
        fallbacks={**DEFAULT_FALLBACK_MODELS, **settings.llm_fallbacks},
    )
