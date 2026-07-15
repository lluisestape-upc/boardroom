"""Typed errors for the BoardRoom MCP tool layer.

Every degraded case the orchestrator must survive (missing .kicad_pcb, a tool
failing, an agent requesting a tool outside its allowlist, ...) is raised as a
subclass of :class:`BoardRoomMcpError`. The orchestrator converts these into
"scope not covered" coverage notes via :meth:`BoardRoomMcpError.as_coverage_note`.
"""

from __future__ import annotations

from typing import Any, ClassVar


class BoardRoomMcpError(Exception):
    """Base class for all typed errors raised by the ``mcp`` package."""

    kind: ClassVar[str] = "mcp_error"

    def __init__(
        self,
        message: str,
        *,
        tool: str | None = None,
        agent: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.tool = tool
        self.agent = agent
        self.detail = detail

    def as_coverage_note(self) -> dict[str, Any]:
        """Shape the orchestrator persists as a 'scope not covered' note."""
        return {
            "kind": self.kind,
            "reason": str(self),
            "tool": self.tool,
            "agent": self.agent,
            "detail": self.detail,
        }


class McpUnavailableError(BoardRoomMcpError):
    """The MCP SDK is missing, the server could not be spawned, or the
    client is not connected."""

    kind: ClassVar[str] = "mcp_unavailable"


class ToolExecutionError(BoardRoomMcpError):
    """The tool ran but reported a failure (kicad-cli missing, parse error
    inside the server, MCP-level isError, ...). ``detail`` carries the raw
    tool output when available."""

    kind: ClassVar[str] = "tool_failure"


class MissingArtifactError(ToolExecutionError):
    """A required project file is absent (.kicad_pcb, .kicad_sch, netlist
    .xml). The orchestrator turns this into a 'scope not covered' note for
    the affected specialist."""

    kind: ClassVar[str] = "missing_artifact"


class AdapterParseError(ToolExecutionError):
    """The tool returned output the adapter does not recognize. Raised
    instead of guessing, so unparsed text can never silently become
    evidence."""

    kind: ClassVar[str] = "unparseable_tool_output"


class InvalidToolArgumentsError(BoardRoomMcpError):
    """Arguments failed the adapter's pydantic request-model validation."""

    kind: ClassVar[str] = "invalid_tool_arguments"


class UnknownToolError(BoardRoomMcpError):
    """No adapter is registered for the requested tool name."""

    kind: ClassVar[str] = "unknown_tool"


class UnknownAgentError(BoardRoomMcpError):
    """The agent name is not present in the allowlist registry."""

    kind: ClassVar[str] = "unknown_agent"


class ToolNotAllowedError(BoardRoomMcpError):
    """An agent requested a tool outside its allowlist. This is the in-code
    enforcement of the per-specialist tool scoping (a core architecture
    claim — never rely on prompts for this)."""

    kind: ClassVar[str] = "tool_not_allowed"

    def __init__(self, *, agent: str, tool: str, allowed: tuple[str, ...]) -> None:
        super().__init__(
            f"agent {agent!r} is not allowed to call tool {tool!r} "
            f"(allowed: {', '.join(allowed) or 'none'})",
            tool=tool,
            agent=agent,
        )
        self.allowed = allowed


class EvidenceNotFoundError(BoardRoomMcpError):
    """A finding referenced an evidence_id that is not in the session cache."""

    kind: ClassVar[str] = "evidence_not_found"
