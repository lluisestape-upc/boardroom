"""In-process fake KiCad MCP session shared by the mcp test suite.

Lives in its own uniquely-named module (not conftest.py): bare ``conftest``
imports are ambiguous when several suites' conftests are loaded in one run.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from mcp.client import ToolResult  # noqa: E402

import samples  # noqa: E402


class FakeKicadSession:
    """In-process stand-in for a live kicad-mcp-server session.

    Implements the ``SupportsCallTool`` protocol. Responses are plain strings
    or ``callable(args) -> str`` keyed by tool name; every call is recorded so
    tests can assert on caching/allowlist behaviour.
    """

    def __init__(
        self,
        responses: dict[str, str | Callable[[dict[str, Any]], str]] | None = None,
        *,
        mcp_error_tools: set[str] | None = None,
    ) -> None:
        self.responses = dict(samples.DEFAULT_RESPONSES)
        if responses:
            self.responses.update(responses)
        self.mcp_error_tools = mcp_error_tools or set()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append((name, dict(arguments)))
        if name in self.mcp_error_tools:
            return ToolResult(text=f"internal server error in {name}", is_error=True)
        response = self.responses[name]
        text = response(arguments) if callable(response) else response
        return ToolResult(text=text)

    def call_count(self, tool: str) -> int:
        return sum(1 for name, _ in self.calls if name == tool)
