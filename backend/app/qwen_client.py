"""Single gateway for every model call in BoardRoom.

All agents — Moderator and specialists — call Qwen models through this module so that
per-agent token accounting is complete and comparable across benchmark configurations.
Bypassing this module breaks the efficiency benchmark; don't.

Model ids live in society/registry.yaml, not here. Verify current ids in the
Model Studio console (qwen3-max / qwen-flash / qwen3-coder-plus / qwen3-vl-plus).

Also provides:
- retry with exponential backoff on 429/5xx/connection errors,
- JSON-mode / structured output via ``response_format``,
- multimodal message helpers (``text_part`` / ``image_part``) for the qwen3-vl
  layout critic,
- ``MockQwenClient`` — the drop-in test double every other workstream uses.
"""

import asyncio
import json
import os
import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import openai
from openai import AsyncOpenAI

DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

# HTTP statuses worth retrying: rate limit + server-side failures.
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

# USD per 1M tokens (prompt, completion). PLACEHOLDER prices — verify in the
# Model Studio pricing page before quoting costs in the benchmark report.
COST_PER_MTOK: dict[str, tuple[float, float]] = {
    "qwen3-max": (1.20, 6.00),
    "qwen-flash": (0.05, 0.40),
    "qwen3-vl-plus": (0.20, 1.60),
    "qwen3-coder-plus": (0.30, 1.50),
}


def text_part(text: str) -> dict:
    """OpenAI-compatible text content part for multimodal messages."""
    return {"type": "text", "text": text}


def image_part(url: str) -> dict:
    """OpenAI-compatible image content part.

    ``url`` may be an https URL or a ``data:image/png;base64,...`` data URI
    (how mcp/render.py board PNGs are inlined for the qwen3-vl layout critic).
    """
    return {"type": "image_url", "image_url": {"url": url}}


@dataclass(frozen=True)
class ToolCall:
    """One tool call the model requested (arguments already JSON-parsed)."""

    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class AssistantTurn:
    """A model turn in a tool-calling loop: free text and/or tool calls."""

    content: str | None
    tool_calls: list[ToolCall]

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


@dataclass
class TokenLedger:
    """Per-agent token accounting; serialized into review.json."""

    counts: dict = field(default_factory=lambda: defaultdict(lambda: {"prompt": 0, "completion": 0, "calls": 0}))

    def record(self, agent: str, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        key = f"{agent}/{model}"
        self.counts[key]["prompt"] += prompt_tokens
        self.counts[key]["completion"] += completion_tokens
        self.counts[key]["calls"] += 1

    def snapshot(self) -> dict:
        return {k: dict(v) for k, v in self.counts.items()}

    def cost_estimate_usd(self) -> float:
        """Estimated spend across all agents, from the placeholder COST_PER_MTOK table."""
        total = 0.0
        for key, c in self.counts.items():
            model = key.split("/", 1)[1]
            prompt_rate, completion_rate = COST_PER_MTOK.get(model, (0.0, 0.0))
            total += c["prompt"] / 1_000_000 * prompt_rate
            total += c["completion"] / 1_000_000 * completion_rate
        return total


def _retryable_status(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status is None:
        return False
    return status in RETRYABLE_STATUS_CODES or status >= 500


class QwenClient:
    """Thin async wrapper over the Model Studio OpenAI-compatible endpoint.

    Reads the API key from the DASHSCOPE_API_KEY environment variable only.
    """

    def __init__(
        self,
        ledger: TokenLedger | None = None,
        *,
        max_retries: int = 4,
        backoff_base: float = 1.0,
        backoff_cap: float = 30.0,
    ):
        api_key = os.environ.get("DASHSCOPE_API_KEY")
        if not api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not set")
        # Disable the SDK's own retries; we own backoff so it is observable/testable.
        self._client = AsyncOpenAI(api_key=api_key, base_url=DASHSCOPE_BASE_URL, max_retries=0)
        self.ledger = ledger or TokenLedger()
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap

    async def chat(
        self,
        *,
        agent: str,
        model: str,
        messages: list[dict],
        response_format: dict | None = None,
        **kwargs: Any,
    ) -> str:
        """One chat completion, with token accounting and retry.

        - ``messages``: standard OpenAI-shape messages. ``content`` may be a plain
          string or a list of content parts (see ``text_part`` / ``image_part``) —
          passed through unchanged, so multimodal calls (qwen3-vl) just work.
        - ``response_format``: e.g. ``{"type": "json_object"}`` for JSON mode, or a
          json_schema structured-output spec. Omitted from the request when None.
        - Retries on 429 / 5xx / connection errors with exponential backoff + jitter,
          up to ``max_retries`` attempts after the first.
        """
        request: dict[str, Any] = {"model": model, "messages": messages, **kwargs}
        if response_format is not None:
            request["response_format"] = response_format

        attempt = 0
        while True:
            try:
                resp = await self._client.chat.completions.create(**request)
                break
            except (openai.APIStatusError, openai.APIConnectionError) as exc:
                retryable = isinstance(exc, openai.APIConnectionError) or _retryable_status(exc)
                if not retryable or attempt >= self.max_retries:
                    raise
                delay = min(self.backoff_cap, self.backoff_base * (2**attempt))
                delay += random.uniform(0, delay * 0.1)  # jitter
                attempt += 1
                await asyncio.sleep(delay)

        usage = resp.usage
        if usage is not None:
            self.ledger.record(agent, model, usage.prompt_tokens, usage.completion_tokens)
        return resp.choices[0].message.content

    async def chat_json(self, *, agent: str, model: str, messages: list[dict], **kwargs: Any) -> str:
        """Convenience: chat() in JSON mode (``response_format={"type": "json_object"}``)."""
        return await self.chat(
            agent=agent,
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            **kwargs,
        )

    async def chat_with_tools(
        self,
        *,
        agent: str,
        model: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice: str = "auto",
        **kwargs: Any,
    ) -> AssistantTurn:
        """One completion that may request tool calls (function calling).

        Returns an :class:`AssistantTurn` (content + parsed tool calls). Same
        retry/backoff and token accounting as :meth:`chat`. The specialist loop
        executes the tool calls and appends the results, then calls again.
        """
        request: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            **kwargs,
        }
        attempt = 0
        while True:
            try:
                resp = await self._client.chat.completions.create(**request)
                break
            except (openai.APIStatusError, openai.APIConnectionError) as exc:
                retryable = isinstance(exc, openai.APIConnectionError) or _retryable_status(exc)
                if not retryable or attempt >= self.max_retries:
                    raise
                delay = min(self.backoff_cap, self.backoff_base * (2**attempt))
                delay += random.uniform(0, delay * 0.1)
                attempt += 1
                await asyncio.sleep(delay)

        usage = resp.usage
        if usage is not None:
            self.ledger.record(agent, model, usage.prompt_tokens, usage.completion_tokens)
        msg = resp.choices[0].message
        calls: list[ToolCall] = []
        for tc in getattr(msg, "tool_calls", None) or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except (json.JSONDecodeError, TypeError):
                args = {}
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        return AssistantTurn(content=msg.content, tool_calls=calls)


class MockQwenClient:
    """Drop-in test double for QwenClient. No network, no API key.

    Canned responses are registered per agent name and replayed in order; the last
    registered response for an agent is repeated once its queue would run dry, so a
    single registration works for any number of calls. Every call is appended to
    ``self.calls`` (dicts with agent/model/messages/response_format/kwargs) for
    assertions. Token usage is recorded into the ledger with deterministic
    fake counts so orchestrator/benchmark accounting code paths run in tests.
    """

    def __init__(self, ledger: TokenLedger | None = None):
        self.ledger = ledger or TokenLedger()
        self.calls: list[dict] = []
        self._responses: dict[str, list[str]] = {}
        self._tool_turns: dict[str, list[AssistantTurn]] = {}
        self.default_response: str | None = None

    def register(self, agent: str, response: str | list[str]) -> "MockQwenClient":
        """Queue canned response(s) for ``agent``. Chainable."""
        queue = self._responses.setdefault(agent, [])
        if isinstance(response, str):
            queue.append(response)
        else:
            queue.extend(response)
        return self

    async def chat(
        self,
        *,
        agent: str,
        model: str,
        messages: list[dict],
        response_format: dict | None = None,
        **kwargs: Any,
    ) -> str:
        self.calls.append(
            {
                "agent": agent,
                "model": model,
                "messages": messages,
                "response_format": response_format,
                "kwargs": kwargs,
            }
        )
        queue = self._responses.get(agent)
        if queue:
            response = queue.pop(0) if len(queue) > 1 else queue[0]
        elif self.default_response is not None:
            response = self.default_response
        else:
            raise LookupError(
                f"MockQwenClient has no canned response for agent {agent!r} "
                f"(registered: {sorted(self._responses)}); call register() first"
            )
        # Deterministic fake usage: ~1 token per 4 chars, floor 1.
        prompt_tokens = max(1, sum(len(str(m.get("content", ""))) for m in messages) // 4)
        completion_tokens = max(1, len(response) // 4)
        self.ledger.record(agent, model, prompt_tokens, completion_tokens)
        return response

    async def chat_json(self, *, agent: str, model: str, messages: list[dict], **kwargs: Any) -> str:
        return await self.chat(
            agent=agent,
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            **kwargs,
        )

    def calls_for(self, agent: str) -> list[dict]:
        return [c for c in self.calls if c["agent"] == agent]

    def register_tool_turns(self, agent: str, turns: list[AssistantTurn]) -> "MockQwenClient":
        """Queue an ordered script of AssistantTurns for chat_with_tools. Chainable."""
        self._tool_turns.setdefault(agent, []).extend(turns)
        return self

    async def chat_with_tools(
        self,
        *,
        agent: str,
        model: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice: str = "auto",
        **kwargs: Any,
    ) -> AssistantTurn:
        self.calls.append(
            {"agent": agent, "model": model, "messages": messages, "tools": tools, "kwargs": kwargs}
        )
        script = self._tool_turns.get(agent)
        if script:
            turn = script.pop(0) if len(script) > 1 else script[0]
        else:
            # No script → a terminal empty-findings turn, so loops always end.
            turn = AssistantTurn(content="[]", tool_calls=[])
        text_len = sum(len(str(m.get("content", ""))) for m in messages)
        self.ledger.record(agent, model, max(1, text_len // 4), max(1, len(turn.content or "") // 4))
        return turn
