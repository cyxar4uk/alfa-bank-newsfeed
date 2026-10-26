import datetime as dt
import json

import pytest
from pydantic import BaseModel

from api.llm import (
    Budget,
    BudgetExceeded,
    DiskCache,
    Journal,
    LlmBadResponse,
    LlmClient,
    LlmUnavailable,
    TransportError,
    TransportResponse,
)
from api.llm.budget import MSK, budget_day
from api.llm.client import extract_json


class Answer(BaseModel):
    answer: str
    n: int


def ok(content: str, cost: float = 0.01, finish: str = "stop", model: str = "z-ai/glm-5.3-flash"):
    data = {
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "completion_tokens_details": {"reasoning_tokens": 5},
            "cost": cost,
        },
    }
    return TransportResponse(200, data, json.dumps(data))


class FakeTransport:
    """Отдаёт заготовленные ответы по очереди и запоминает запросы."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.bodies: list[dict] = []

    def post(self, body):
        self.bodies.append(json.loads(json.dumps(body)))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_client(transport, tmp_path, limit=10.0, now=None, **kwargs):
    budget = Budget(limit, now=now) if now else Budget(limit)
    kwargs.setdefault("fallbacks", {})  # запасные модели проверяются отдельным тестом
    return LlmClient(
        transport,
        budget=budget,
        journal=Journal(tmp_path / "calls.jsonl"),
        cache=DiskCache(tmp_path / "cache"),
        sleep=lambda s: None,
        **kwargs,
    )


def journal(tmp_path):
    return [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text(encoding="utf-8").splitlines()]


MESSAGES = [{"role": "user", "content": "Столица России и 2+2?"}]


def test_model_by_step_from_config(tmp_path):
    transport = FakeTransport(ok('{"answer": "Москва", "n": 4}'))
    client = make_client(transport, tmp_path, models={"plan": "qwen/qwen3.6-35b-a3b"})
    result = client.complete("plan", MESSAGES, schema=Answer)
    assert transport.bodies[0]["model"] == "qwen/qwen3.6-35b-a3b"
    assert transport.bodies[0]["response_format"] == {"type": "json_object"}
    assert result.value == Answer(answer="Москва", n=4)


def test_only_allowed_models(tmp_path):
    with pytest.raises(ValueError, match="не из списка"):
        make_client(FakeTransport(), tmp_path, models={"draft": "openai/gpt-4o"})
    client = make_client(FakeTransport(), tmp_path)
    with pytest.raises(ValueError):
        client.complete("draft", MESSAGES, model="meta/llama-3")


def test_same_request_comes_from_cache(tmp_path):
    transport = FakeTransport(ok('{"answer": "Москва", "n": 4}', cost=0.02))
    client = make_client(transport, tmp_path)
    first = client.complete("draft", MESSAGES, schema=Answer)
    second = client.complete("draft", MESSAGES, schema=Answer)
    assert len(transport.bodies) == 1
    assert second.value == first.value
    assert second.cached and second.cost == 0
    assert client.budget.spent == pytest.approx(0.02)
    entries = journal(tmp_path)
    assert [e["cached"] for e in entries] == [False, True]


def test_journal_has_step_model_tokens_cost(tmp_path):
    client = make_client(FakeTransport(ok('{"answer": "Москва", "n": 4}', cost=0.0123)), tmp_path)
    client.complete("check", MESSAGES, schema=Answer)
    (entry,) = journal(tmp_path)
    assert entry["step"] == "check"
    assert entry["model"] == "z-ai/glm-5.3-flash"
    assert (entry["prompt_tokens"], entry["completion_tokens"], entry["reasoning_tokens"]) == (100, 20, 5)
    assert entry["cost"] == pytest.approx(0.0123)
    assert entry["ok"] is True
    text = (tmp_path / "calls.jsonl").read_text(encoding="utf-8")
    assert "Столица" not in text  # тексты запросов в журнал не пишутся


def test_invalid_json_is_retried_with_validation_error(tmp_path):
    transport = FakeTransport(
        ok('```json\n{"answer": "Москва", "n": "четыре"}\n```'),
        ok('Вот ответ: {"answer": "Москва", "n": 4}'),
    )
    client = make_client(transport, tmp_path)
    result = client.complete("draft", MESSAGES, schema=Answer)
    assert result.value.n == 4
    retry = transport.bodies[1]["messages"]
    assert retry[-2]["role"] == "assistant"
    assert "n" in retry[-1]["content"] and "integer" in retry[-1]["content"]
    assert len(result.calls) == 2 and result.cost == pytest.approx(0.02)
    entries = journal(tmp_path)
    assert [e["ok"] for e in entries] == [False, True]


def test_invalid_response_gives_up(tmp_path):
    transport = FakeTransport(ok("не знаю"), ok("{}"), ok('{"answer": 1}'))
    client = make_client(transport, tmp_path, validation_attempts=2)
    with pytest.raises(LlmBadResponse) as exc:
        client.complete("draft", MESSAGES, schema=Answer)
    assert len(exc.value.calls) == 3
    assert not (tmp_path / "cache").exists() or not any((tmp_path / "cache").rglob("*.json"))


def test_cut_by_length_retries_once_without_reasoning(tmp_path):
    # у плана рассуждения не выключены: обрыв на лимите — повтор без рассуждений, лимит тот же
    transport = FakeTransport(ok("", finish="length"), ok('{"answer": "Москва", "n": 4}'))
    client = make_client(transport, tmp_path)
    client.complete("plan", MESSAGES, schema=Answer, max_tokens=500)
    assert [b["max_tokens"] for b in transport.bodies] == [500, 500]
    assert "reasoning" not in transport.bodies[0]
    assert transport.bodies[1]["reasoning"] == {"enabled": False}


def test_cut_by_length_without_reasoning_is_not_repeated(tmp_path):
    from api.llm import LlmBadResponse

    transport = FakeTransport(ok("", finish="length"), ok('{"answer": "Москва", "n": 4}'))
    client = make_client(transport, tmp_path)
    with pytest.raises(LlmBadResponse, match="оборвался на лимите"):
        client.complete("draft", MESSAGES, schema=Answer, max_tokens=500)
    assert len(transport.bodies) == 1  # тот же запрос оборвётся снова — не тратим время и деньги


def test_long_steps_go_without_reasoning(tmp_path):
    transport = FakeTransport(ok('{"answer": "Москва", "n": 4}'))
    make_client(transport, tmp_path).complete("draft", MESSAGES, schema=Answer)
    assert transport.bodies[0]["reasoning"] == {"enabled": False}


def test_retries_network_and_server_errors(tmp_path):
    transport = FakeTransport(
        TransportError("ConnectTimeout"),
        TransportResponse(502, None, "Bad Gateway"),
        ok('{"answer": "Москва", "n": 4}'),
    )
    client = make_client(transport, tmp_path)
    assert client.complete("draft", MESSAGES, schema=Answer).value.n == 4
    assert len(transport.bodies) == 3


def test_gives_up_after_max_attempts(tmp_path):
    transport = FakeTransport(*[TransportResponse(503, None, "unavailable")] * 4)
    client = make_client(transport, tmp_path)
    with pytest.raises(LlmUnavailable, match="503"):
        client.complete("draft", MESSAGES)


def test_client_error_is_not_retried(tmp_path):
    bad = TransportResponse(400, {"error": {"message": "bad model"}}, '{"error": "bad"}')
    transport = FakeTransport(bad, bad)
    client = make_client(transport, tmp_path)
    with pytest.raises(LlmUnavailable, match="400"):
        client.complete("draft", MESSAGES)
    # один повтор без нестандартных параметров (reasoning), дальше ошибка клиента не повторяется
    assert len(transport.bodies) == 2 and "reasoning" not in transport.bodies[1]


def test_gateway_budget_error_stops_calls(tmp_path):
    body = '{"error": {"message": "Budget has been exceeded! Current cost: 500.1, Max budget: 500.0"}}'
    transport = FakeTransport(TransportResponse(400, json.loads(body), body))
    client = make_client(transport, tmp_path)
    with pytest.raises(BudgetExceeded, match="Budget has been exceeded"):
        client.complete("draft", MESSAGES)
    # до сброса суток клиент больше не ходит к шлюзу
    with pytest.raises(BudgetExceeded):
        client.complete("draft", [{"role": "user", "content": "другое"}])
    assert len(transport.bodies) == 1


def test_own_daily_limit(tmp_path):
    transport = FakeTransport(
        ok('{"answer": "a", "n": 1}', cost=0.6), ok('{"answer": "b", "n": 2}', cost=0.6)
    )
    client = make_client(transport, tmp_path, limit=1.0)
    client.complete("draft", [{"role": "user", "content": "1"}], schema=Answer)
    client.complete("draft", [{"role": "user", "content": "2"}], schema=Answer)
    with pytest.raises(BudgetExceeded, match="Budget has been exceeded: за сутки потрачено 1.20"):
        client.complete("draft", [{"role": "user", "content": "3"}], schema=Answer)
    assert len(transport.bodies) == 2


def test_cache_hit_is_free_even_over_budget(tmp_path):
    transport = FakeTransport(ok('{"answer": "a", "n": 1}', cost=2.0))
    client = make_client(transport, tmp_path, limit=1.0)
    client.complete("draft", MESSAGES, schema=Answer)
    assert client.complete("draft", MESSAGES, schema=Answer).cached


def test_budget_resets_at_3am_msk():
    clock = {"now": dt.datetime(2026, 10, 24, 2, 59, tzinfo=MSK)}
    budget = Budget(1.0, now=lambda: clock["now"])
    budget.add(1.5)
    with pytest.raises(BudgetExceeded):
        budget.check()
    clock["now"] = dt.datetime(2026, 10, 24, 3, 0, tzinfo=MSK)
    budget.check()
    assert budget.spent == 0
    assert budget_day(dt.datetime(2026, 10, 24, 2, 0, tzinfo=MSK)) == dt.date(2026, 10, 23)


def test_budget_restored_from_journal(tmp_path):
    now = dt.datetime(2026, 10, 24, 12, 0, tzinfo=MSK)
    log = Journal(tmp_path / "calls.jsonl")
    log.write({"at": "2026-10-24T02:00:00+03:00", "cost": 9.0, "cached": False})  # прошлые сутки
    log.write({"at": "2026-10-24T04:00:00+03:00", "cost": 0.7, "cached": False})
    log.write({"at": "2026-10-24T05:00:00+03:00", "cost": 0.0, "cached": True})
    budget = Budget(1.0, now=lambda: now)
    budget.restore(log.spending())
    assert budget.spent == pytest.approx(0.7)


def test_extract_json_strips_reasoning_and_fences():
    assert extract_json('<think>хм {"x": 0}</think>\n```json\n{"a": 1}\n```') == '{"a": 1}'


def test_text_mode_without_schema(tmp_path):
    client = make_client(FakeTransport(ok("Просто текст")), tmp_path)
    result = client.complete("ask", MESSAGES)
    assert result.text == "Просто текст" and result.value is None


def test_cut_by_length_without_reasoning_gets_one_bigger_try(tmp_path):
    # ответ сам длиннее лимита (рассуждений не было) — один повтор с бо́льшим лимитом, дальше ошибка
    def cut():
        r = ok("", finish="length")
        r.data["usage"]["completion_tokens_details"]["reasoning_tokens"] = 0
        return r

    transport = FakeTransport(cut(), cut(), ok('{"answer": "Москва", "n": 4}'))
    client = make_client(transport, tmp_path)
    with pytest.raises(LlmBadResponse, match="оборвался на лимите"):
        client.complete("plan", MESSAGES, schema=Answer, max_tokens=500)
    assert [b["max_tokens"] for b in transport.bodies] == [500, 1000]
