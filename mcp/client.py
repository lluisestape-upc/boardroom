"""Async stdio MCP client for the Seeed-Studio kicad-mcp-server.

The server command is configurable via the ``KICAD_MCP_COMMAND`` environment
variable (a full command line, e.g. ``kicad-mcp-server`` or
``C:\\Users\\me\\kicad-mcp-env\\Scripts\\kicad-mcp-server.exe``). Default is
``kicad-mcp-server`` resolved on PATH, with a fallback probe for the known
local venv install.

Import-machinery note: this module is imported as ``mcp.client`` and therefore
shadows the MCP SDK's ``mcp.client`` subpackage (see ``mcp/__init__.py``). We
mount the SDK's ``client/`` directory as this module's ``__path__`` so the
SDK's submodules (``mcp.client.session``, ``mcp.client.stdio``, ...) keep
importing normally — both for our own use below and for SDK-internal absolute
imports.
"""

from __future__ import annotations

import os
import shlex
import shutil
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Protocol, Sequence, runtime_checkable

from pydantic import BaseModel, ConfigDict

from . import MCP_SDK_DIR
from .errors import McpUnavailableError

# Mount the SDK's client/ subpackage under this module (see docstring).
if MCP_SDK_DIR is not None:
    __path__ = [str(MCP_SDK_DIR / "client")]  # noqa: F841 (import machinery)

ENV_VAR = "KICAD_MCP_COMMAND"
DEFAULT_COMMAND = "kicad-mcp-server"

# Probed only when KICAD_MCP_COMMAND is unset and the default is not on PATH.
_FALLBACK_LOCATIONS: tuple[Path, ...] = (
    Path.home() / "kicad-mcp-env" / "Scripts" / "kicad-mcp-server.exe",
    Path.home() / "kicad-mcp-env" / "bin" / "kicad-mcp-server",
)


class ToolResult(BaseModel):
    """Transport-level result of one MCP tool call (text already joined)."""

    model_config = ConfigDict(frozen=True)

    text: str
    is_error: bool = False


@runtime_checkable
class SupportsCallTool(Protocol):
    """The minimal session surface the adapter layer consumes.

    :class:`KicadMCPClient` implements it against a live server; tests
    implement it with an in-process fake.
    """

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        ...  # pragma: no cover - protocol


def _split_command(raw: str) -> list[str]:
    """Split a command line into argv, tolerating Windows paths and quotes."""
    if os.name == "nt":
        parts = shlex.split(raw, posix=False)
        return [
            p[1:-1] if len(p) > 1 and p[0] == p[-1] and p[0] in "\"'" else p
            for p in parts
        ]
    return shlex.split(raw)


def resolve_server_command(env: dict[str, str] | None = None) -> list[str]:
    """Resolve the kicad-mcp-server command line as argv.

    Precedence: ``KICAD_MCP_COMMAND`` env var > ``kicad-mcp-server`` on PATH >
    known local venv locations > bare default (connection will then fail with
    :class:`McpUnavailableError`).
    """
    environ = os.environ if env is None else env
    raw = (environ.get(ENV_VAR) or "").strip()
    if raw:
        argv = _split_command(raw)
        if not argv:
            raise McpUnavailableError(f"{ENV_VAR} is set but empty after parsing: {raw!r}")
        return argv
    if shutil.which(DEFAULT_COMMAND):
        return [DEFAULT_COMMAND]
    for cand in _FALLBACK_LOCATIONS:
        if cand.is_file():
            return [str(cand)]
    return [DEFAULT_COMMAND]


def _sdk_imports():
    """Import the MCP SDK pieces lazily so the fake-server test path never
    needs the SDK, and a missing SDK degrades to a typed error."""
    if MCP_SDK_DIR is None:
        raise McpUnavailableError(
            "the 'mcp' Python SDK is not installed (pip install -r "
            "backend/requirements.txt); cannot open a stdio session"
        )
    try:
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client
    except Exception as exc:  # pragma: no cover - environment-specific
        raise McpUnavailableError(f"failed to import the mcp SDK: {exc}") from exc
    return ClientSession, StdioServerParameters, stdio_client


def tool_result_from_sdk(result: Any) -> ToolResult:
    """Convert an SDK ``CallToolResult`` into our transport-level ToolResult."""
    parts: list[str] = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if text:
            parts.append(text)
    return ToolResult(text="\n".join(parts), is_error=bool(getattr(result, "isError", False)))


class KicadMCPClient:
    """Spawns kicad-mcp-server over stdio and exposes ``call_tool``.

    Usage::

        async with KicadMCPClient() as client:
            tools = await client.list_tools()
            result = await client.call_tool("run_erc", {"schematic_path": p})

    Satisfies :class:`SupportsCallTool`, so it plugs directly into
    ``mcp.adapters.run_tool`` and ``mcp.allowlist.AgentToolbox``.
    """

    def __init__(
        self,
        command: str | Sequence[str] | None = None,
        *,
        extra_args: Sequence[str] = (),
        env: dict[str, str] | None = None,
        cwd: str | Path | None = None,
    ) -> None:
        if command is None:
            self._argv = resolve_server_command()
        elif isinstance(command, str):
            self._argv = _split_command(command)
        else:
            self._argv = list(command)
        self._argv += list(extra_args)
        if not self._argv:
            raise McpUnavailableError("empty kicad-mcp-server command")
        self._env = env
        self._cwd = str(cwd) if cwd is not None else None
        self._stack: AsyncExitStack | None = None
        self._session: Any = None

    @property
    def command(self) -> list[str]:
        return list(self._argv)

    @property
    def connected(self) -> bool:
        return self._session is not None

    async def connect(self) -> "KicadMCPClient":
        if self._session is not None:
            return self
        ClientSession, StdioServerParameters, stdio_client = _sdk_imports()

        params_kwargs: dict[str, Any] = {
            "command": self._argv[0],
            "args": self._argv[1:],
            "env": self._env,
        }
        if self._cwd is not None and "cwd" in StdioServerParameters.model_fields:
            params_kwargs["cwd"] = self._cwd
        params = StdioServerParameters(**params_kwargs)

        stack = AsyncExitStack()
        try:
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except McpUnavailableError:
            await stack.aclose()
            raise
        except Exception as exc:
            await stack.aclose()
            raise McpUnavailableError(
                f"could not start kicad-mcp-server via {self._argv!r}: {exc}"
            ) from exc
        self._stack = stack
        self._session = session
        return self

    async def aclose(self) -> None:
        session, stack = self._session, self._stack
        self._session = None
        self._stack = None
        if stack is not None:
            await stack.aclose()
        del session

    async def __aenter__(self) -> "KicadMCPClient":
        return await self.connect()

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.aclose()

    async def list_tools(self) -> list[str]:
        """Names of all tools the connected server exposes."""
        if self._session is None:
            raise McpUnavailableError("client is not connected (call connect())")
        result = await self._session.list_tools()
        return [t.name for t in result.tools]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        if self._session is None:
            raise McpUnavailableError("client is not connected (call connect())")
        result = await self._session.call_tool(name, arguments or {})
        return tool_result_from_sdk(result)
