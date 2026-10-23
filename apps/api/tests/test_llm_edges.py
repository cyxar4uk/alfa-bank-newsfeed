"""Граничные случаи клиента моделей: бюджет, ошибки шлюза, обрывы, пустой ключ."""

import json

import pytest
from test_llm import MESSAGES, Answer, FakeTransport, journal, make_client, ok

from api.llm import LlmUnavailable, TransportError, TransportResponse


def test_budget_phrase_in_model_answer_does_not_stop_service(tmp_path):
    # модель процитировала новость со словами «Budget has been exceeded» — это не отказ шлюза
    client = make_client(FakeTransport(ok('{"answer": "Budget has been exceeded", "n": 1}')), tmp_path)
    assert client.complete("draft", MESSAGES, schema=Answer).value.answer == "Budget has been exceeded"
    assert client.budget.remaining > 0


def test_upstream_error_text_stays_in_journal(tmp_path):
    body = '{"error": {"message": "internal: upstream db=10.0.0.5 failed"}}'
    client = make_client(FakeTransport(TransportResponse(400, json.loads(body), body)), tmp_path)
    with pytest.raises(LlmUnavailable) as exc:
        client.complete("draft", MESSAGES)
    assert "10.0.0.5" not in str(exc.value) and "400" in str(exc.value)
    assert "10.0.0.5" in (tmp_path / "calls.jsonl").read_text(encoding="utf-8")


def test_lost_request_is_retried_only_once(tmp_path):
    # обрыв после отправки: запрос мог быть оплачен — повторяем один раз, а не четыре
    lost = TransportError("ReadTimeout", before_send=False)
    transport = FakeTransport(lost, lost, ok('{"answer": "a", "n": 1}'))
    client = make_client(transport, tmp_path)
    with pytest.raises(LlmUnavailable):
        client.complete("draft", MESSAGES)
    assert len(transport.bodies) == 2


def test_missing_cost_is_marked(tmp_path):
    response = ok('{"answer": "a", "n": 1}')
    del response.data["usage"]["cost"]
    client = make_client(FakeTransport(response), tmp_path)
    client.complete("draft", MESSAGES, schema=Answer)
    assert "usage.cost" in journal(tmp_path)[0]["error"]


def test_empty_key_disables_agent(tmp_path):
    from api.config import Settings
    from api.llm import client_from_settings

    settings = Settings(
        llm_api_key="", llm_base_url="https://example.test/v1", llm_journal=tmp_path / "j.jsonl"
    )
    assert client_from_settings(settings) is None


def test_cache_write_failure_does_not_lose_paid_answer(tmp_path):
    client = make_client(FakeTransport(ok('{"answer": "a", "n": 1}')), tmp_path)

    def broken(key, value):
        raise OSError("диск заполнен")

    client.cache.put = broken
    assert client.complete("draft", MESSAGES, schema=Answer).value.n == 1
