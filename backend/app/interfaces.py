"""Integration contracts between the orchestrator and the concurrent workstreams.

The orchestrator codes against these Protocols only. Concrete implementations land in
parallel workstreams and must match these shapes:

- ``ModelClient``      → ``backend/app/qwen_client.py`` (society-engineer). The seed
                         ``QwenClient`` already matches: ``chat(...)`` + a ``ledger``
                         exposing ``snapshot()``.
- ``ToolLayer``        → ``mcp/`` allowlist-enforced tool calls + evidence cache
                         (mcp-engineer). Needed for the Day 2 debate seam (one extra
                         tool call per side per round, NEGOTIATION_PROTOCOL.md §3).
- ``ManifestBuilder``  → ``mcp/`` adapters (get_schematic_info, get_pcb_statistics,
                         netlist). Day 1 uses a local filesystem fallback.
- ``SpecialistRunner`` → the specialist agent loop (prompt + tools + findings). Day 1
                         default is a single-shot model call; tests inject fakes.

Do NOT import concrete implementations from ``mcp/`` or ``society/`` here — this
module must stay dependency-free so every workstream can import it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class AgentConfig:
    """One specialist agent: name (must be a valid ``agent`` enum value in
    docs/schemas/finding.schema.json), model id, and system-prompt path."""

    name: str
    model: str
    prompt_path: str | None = None


@dataclass(frozen=True)
class EvidenceRecord:
    """A cached MCP tool-call result. ``evidence_id`` is what findings cite."""

    evidence_id: str
    tool: str
    output: Any


@runtime_checkable
class TokenLedgerLike(Protocol):
    """Per-agent token accounting; the snapshot is embedded in review.json."""

    def snapshot(self) -> dict: ...


@runtime_checkable
class ModelClient(Protocol):
    """Every model call in BoardRoom goes through this (token accounting).

    Matches the seed ``QwenClient`` in backend/app/qwen_client.py exactly.
    """

    ledger: TokenLedgerLike

    async def chat(
        self, *, agent: str, model: str, messages: list[dict], **kwargs: Any
    ) -> str: ...


@runtime_checkable
class SpecialistRunner(Protocol):
    """Runs one specialist over its scope and returns raw finding dicts.

    Raising is fine: the Moderator isolates the failure and converts it into a
    "scope not covered" coverage note — never a crashed session. Returned dicts
    are schema-validated at the boundary by the Moderator; the runner does not
    need to pre-validate.
    """

    async def run(
        self,
        *,
        config: AgentConfig,
        session_id: str,
        project_path: str,
        manifest: dict,
    ) -> list[dict]: ...


@runtime_checkable
class ToolLayer(Protocol):
    """Allowlist-enforced MCP tool execution with evidence caching (mcp/ workstream).

    ``agent`` is the caller's name so the allowlist can be enforced per agent and
    the extra debate tool call (NEGOTIATION_PROTOCOL.md §3: exactly one per side
    per round) can be attributed.
    """

    async def call_tool(
        self, *, agent: str, tool: str, arguments: dict
    ) -> EvidenceRecord: ...


@runtime_checkable
class ManifestBuilder(Protocol):
    """Builds the project manifest used for scope assignment (ARCHITECTURE.md §1)."""

    async def build(self, project_path: str) -> dict: ...


_DAY1_FALLBACK = [
    AgentConfig(name="connectivity_erc", model="qwen-flash",
                prompt_path="society/prompts/connectivity_erc.md"),
    AgentConfig(name="power_integrity", model="qwen-flash",
                prompt_path="society/prompts/power_integrity.md"),
]


def load_agent_configs() -> list[AgentConfig]:
    """The specialist roster from society/registry.yaml (the Moderator is excluded —
    it is not a filing specialist). Falls back to the Day-1 two-agent roster if the
    registry is unreadable. Return shape stays ``list[AgentConfig]`` so the Moderator
    is untouched by the swap.
    """
    try:
        from society.loader import load_registry
    except Exception:
        return list(_DAY1_FALLBACK)
    try:
        registry = load_registry()
    except Exception:
        return list(_DAY1_FALLBACK)
    configs = [
        AgentConfig(name=name, model=spec.model, prompt_path=spec.prompt)
        for name, spec in registry.agents.items()
        if name != "moderator"
    ]
    return configs or list(_DAY1_FALLBACK)
