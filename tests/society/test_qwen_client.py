"""QwenClient retry/JSON-mode behavior and the MockQwenClient contract.

No live API: QwenClient tests stub the inner OpenAI client and use a dummy env key.
"""

import asyncio
from types import SimpleNamespace

import httpx
import openai
import pytest

from backend.app.qwen_client import (
    DASHSCOPE_BASE_URL,
    MockQwenClient,
    QwenClient,
    TokenLedger,
    image_part,
    text_part,
)


def run(coro):
    return asyncio.run(coro)


def fake_completion(content: str, prompt_tokens: int = 10, completion_tokens: int = 5):
    return SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
    )


def api_status_error(status: int) -> openai.APIStatusError:
    request = httpx.Request("POST", DASHSCOPE_BASE_URL + "/chat/completions")
    response = httpx.Response(status, request=request)
    return openai.APIStatusError(f"http {status}", response=response, body=None)


class StubInner:
    """Stands in for AsyncOpenAI: raises queued errors, then returns a completion."""

    def __init__(self, errors: list[Exception], content: str = "ok"):
        self.errors = list(errors)
        self.content = content
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.requests.append(kwargs)
        if self.errors:
            raise self.errors.pop(0)
        return fake_completion(self.content)


@pytest.fixture()
def client(monkeypatch) -> QwenClient:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dummy-test-key")  # never a real key
    return QwenClient(max_retries=3, backoff_base=0.001)


def test_qwen_client_requires_env_key(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
        QwenClient()


def test_retries_on_429_then_succeeds_and_records_tokens(client):
    stub = StubInner([api_status_error(429), api_status_error(503)])
    client._client = stub
    out = run(client.chat(agent="power_integrity", model="qwen-flash", messages=[{"role": "user", "content": "hi"}]))
    assert out == "ok"
    assert len(stub.requests) == 3  # 2 failures + 1 success
    snap = client.ledger.snapshot()
    assert snap["power_integrity/qwen-flash"] == {"prompt": 10, "completion": 5, "calls": 1}


def test_gives_up_after_max_retries(client):
    stub = StubInner([api_status_error(500)] * 10)
    client._client = stub
    with pytest.raises(openai.APIStatusError):
        run(client.chat(agent="moderator", model="qwen3-max", messages=[]))
    assert len(stub.requests) == 1 + client.max_retries


def test_non_retryable_status_raises_immediately(client):
    stub = StubInner([api_status_error(400)])
    client._client = stub
    with pytest.raises(openai.APIStatusError):
        run(client.chat(agent="moderator", model="qwen3-max", messages=[]))
    assert len(stub.requests) == 1


def test_response_format_passthrough_and_chat_json(client):
    stub = StubInner([], content="{}")
    client._client = stub
    run(client.chat_json(agent="connectivity_erc", model="qwen-flash", messages=[]))
    assert stub.requests[0]["response_format"] == {"type": "json_object"}

    stub.requests.clear()
    run(client.chat(agent="connectivity_erc", model="qwen-flash", messages=[]))
    assert "response_format" not in stub.requests[0]  # omitted when None


def test_multimodal_content_parts_helpers():
    assert text_part("hello") == {"type": "text", "text": "hello"}
    part = image_part("data:image/png;base64,AAAA")
    assert part == {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}


def test_multimodal_messages_pass_through_unchanged(client):
    stub = StubInner([])
    client._client = stub
    messages = [{"role": "user", "content": [text_part("critique this board"), image_part("data:image/png;base64,AA")]}]
    run(client.chat(agent="dfm_layout", model="qwen3-vl-plus", messages=messages))
    assert stub.requests[0]["messages"] is messages


# --- MockQwenClient -------------------------------------------------------------


def test_mock_replays_canned_responses_per_agent():
    mock = MockQwenClient()
    mock.register("connectivity_erc", "[]")
    mock.register("power_integrity", ["first", "second"])

    assert run(mock.chat(agent="connectivity_erc", model="qwen-flash", messages=[])) == "[]"
    assert run(mock.chat(agent="power_integrity", model="qwen-flash", messages=[])) == "first"
    assert run(mock.chat(agent="power_integrity", model="qwen-flash", messages=[])) == "second"
    # Last response repeats once the queue is exhausted.
    assert run(mock.chat(agent="power_integrity", model="qwen-flash", messages=[])) == "second"


def test_mock_records_calls_for_assertions():
    mock = MockQwenClient()
    mock.register("moderator", "ruling")
    messages = [{"role": "user", "content": "decide"}]
    run(mock.chat(agent="moderator", model="qwen3-max", messages=messages, temperature=0.1))

    assert len(mock.calls) == 1
    call = mock.calls[0]
    assert call["agent"] == "moderator"
    assert call["model"] == "qwen3-max"
    assert call["messages"] is messages
    assert call["kwargs"] == {"temperature": 0.1}
    assert mock.calls_for("moderator") == [call]
    assert mock.calls_for("power_integrity") == []


def test_mock_unregistered_agent_raises_helpfully():
    mock = MockQwenClient()
    mock.register("moderator", "x")
    with pytest.raises(LookupError, match="signal_integrity"):
        run(mock.chat(agent="signal_integrity", model="qwen-flash", messages=[]))


def test_mock_default_response_fallback():
    mock = MockQwenClient()
    mock.default_response = "[]"
    assert run(mock.chat(agent="anyone", model="qwen-flash", messages=[])) == "[]"


def test_mock_records_token_usage_in_shared_ledger():
    ledger = TokenLedger()
    mock = MockQwenClient(ledger=ledger)
    mock.register("connectivity_erc", "some findings text")
    run(mock.chat(agent="connectivity_erc", model="qwen-flash", messages=[{"role": "user", "content": "review"}]))

    snap = ledger.snapshot()
    entry = snap["connectivity_erc/qwen-flash"]
    assert entry["calls"] == 1
    assert entry["prompt"] >= 1
    assert entry["completion"] >= 1
    assert ledger.cost_estimate_usd() >= 0


def test_mock_chat_json_sets_response_format():
    mock = MockQwenClient()
    mock.register("connectivity_erc", "[]")
    run(mock.chat_json(agent="connectivity_erc", model="qwen-flash", messages=[]))
    assert mock.calls[0]["response_format"] == {"type": "json_object"}
