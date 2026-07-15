"""Per-agent tool allowlists, enforced in code.

The orchestrator hands each specialist an :class:`AgentToolbox` — the ONLY
path a specialist has to MCP tools. A request for a non-allowlisted tool
raises :class:`ToolNotAllowedError` before anything touches the server. This
is the in-code enforcement of the architecture's per-specialist scoping
claim; prompts are never trusted for it.

The mapping ships with defaults below and is lazily overridden by
``society/registry.yaml`` (owned by the society-engineer): the file is
re-checked on every lookup (mtime-based), so it wins as soon as it exists —
no restart, no import-order coupling.

Accepted registry.yaml shapes (tolerant on purpose)::

    agents:
      power_integrity:
        model: qwen-flash
        tools: [extract_power_domains, ...]     # or allowlist: / allowed_tools:
    # ... or a bare  agent -> [tools]  mapping at top level

An entry of ``"*"`` allows every registered tool (used by the moderator).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from .adapters import ToolCallOutcome, registered_tools, run_tool
from .client import SupportsCallTool
from .errors import ToolNotAllowedError, UnknownAgentError
from .evidence import EvidenceCache

#: Agent names — must stay in sync with finding.schema.json's "agent" enum.
KNOWN_AGENTS: tuple[str, ...] = (
    "power_integrity",
    "signal_integrity",
    "connectivity_erc",
    "dfm_layout",
    "firmware_bringup",
    "moderator",
)

WILDCARD = "*"

# Default allowlists. Day-2 tools are listed even though their adapters land
# later — the allowlist is a stable contract; calling an allowed tool without
# an adapter raises UnknownToolError until the adapter exists.
DEFAULT_ALLOWLIST: dict[str, frozenset[str]] = {
    "power_integrity": frozenset({
        "extract_power_domains",
        "analyze_pcb_power_integrity",
        "get_netlist_nets",
        "get_netlist_components",
        "get_schematic_info",
        "get_pcb_statistics",
    }),
    "signal_integrity": frozenset({
        "analyze_pcb_signal_integrity",
        "find_tracks_by_net",
        "trace_netlist_connection",
        "get_netlist_nets",
        "get_pcb_statistics",
    }),
    "connectivity_erc": frozenset({
        "run_erc",
        "get_erc_violations",
        "run_drc",
        "get_drc_violations",
        "generate_netlist",
        "get_netlist_components",
        "get_netlist_nets",
    }),
    "dfm_layout": frozenset({
        "run_drc",
        "get_drc_violations",
        "get_pcb_statistics",
        "list_pcb_footprints",
        "analyze_pcb_nets",
    }),
    "firmware_bringup": frozenset({
        "extract_i2c_devices",
        "extract_spi_devices",
        "extract_gpio_config",
        "generate_device_tree",
        "detect_pin_conflicts",
        "validate_pin_configuration",
        "analyze_pin_functions",
        "get_netlist_components",
    }),
    # The chair builds the session manifest and executes debate tool calls;
    # it is deliberately unrestricted.
    "moderator": frozenset({WILDCARD}),
}

_TOOLS_KEYS = ("tools", "allowlist", "tool_allowlist", "allowed_tools")


def _default_registry_path() -> Path:
    return Path(__file__).resolve().parent.parent / "society" / "registry.yaml"


def _extract_tools(spec: Any) -> frozenset[str] | None:
    if isinstance(spec, str):
        return frozenset({spec})
    if isinstance(spec, (list, tuple, set)):
        return frozenset(str(t) for t in spec)
    if isinstance(spec, Mapping):
        for key in _TOOLS_KEYS:
            if key in spec:
                return _extract_tools(spec[key])
    return None


class AllowlistRegistry:
    """Agent -> permitted tool set, with lazy registry.yaml overrides."""

    def __init__(
        self,
        registry_path: str | Path | None = None,
        defaults: Mapping[str, frozenset[str]] = DEFAULT_ALLOWLIST,
    ) -> None:
        self._path = Path(registry_path) if registry_path is not None else _default_registry_path()
        self._defaults = {name: frozenset(tools) for name, tools in defaults.items()}
        self._overrides: dict[str, frozenset[str]] = {}
        self._mtime_ns: int | None = None

    @property
    def registry_path(self) -> Path:
        return self._path

    def _refresh(self) -> None:
        """Re-read society/registry.yaml when it appeared or changed."""
        try:
            stat = self._path.stat()
        except OSError:
            self._overrides = {}
            self._mtime_ns = None
            return
        if self._mtime_ns == stat.st_mtime_ns:
            return
        try:
            data = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        except Exception:
            # A half-written or invalid file must not take the review down;
            # defaults keep applying until the file parses.
            return
        agents = data.get("agents", data) if isinstance(data, dict) else {}
        overrides: dict[str, frozenset[str]] = {}
        if isinstance(agents, Mapping):
            for name, spec in agents.items():
                tools = _extract_tools(spec)
                if tools is not None:
                    overrides[str(name)] = tools
        self._overrides = overrides
        self._mtime_ns = stat.st_mtime_ns

    def agents(self) -> tuple[str, ...]:
        self._refresh()
        return tuple(sorted(set(self._defaults) | set(self._overrides)))

    def allowed_tools(self, agent: str) -> frozenset[str]:
        """Permitted tool names for ``agent`` (may contain ``"*"``)."""
        self._refresh()
        tools = self._overrides.get(agent, self._defaults.get(agent))
        if tools is None:
            raise UnknownAgentError(
                f"unknown agent {agent!r} (known: {', '.join(self.agents())})",
                agent=agent,
            )
        return tools

    def is_allowed(self, agent: str, tool: str) -> bool:
        allowed = self.allowed_tools(agent)
        return WILDCARD in allowed or tool in allowed

    def check(self, agent: str, tool: str) -> None:
        """Raise :class:`ToolNotAllowedError` unless ``agent`` may call ``tool``."""
        allowed = self.allowed_tools(agent)
        if WILDCARD not in allowed and tool not in allowed:
            raise ToolNotAllowedError(agent=agent, tool=tool, allowed=tuple(sorted(allowed)))

    def toolbox(
        self, agent: str, session: SupportsCallTool, cache: EvidenceCache
    ) -> "AgentToolbox":
        return AgentToolbox(self, agent, session, cache)


class AgentToolbox:
    """The scoped tool surface handed to one specialist for one session."""

    def __init__(
        self,
        registry: AllowlistRegistry,
        agent: str,
        session: SupportsCallTool,
        cache: EvidenceCache,
    ) -> None:
        registry.allowed_tools(agent)  # fail fast on unknown agents
        self._registry = registry
        self._agent = agent
        self._session = session
        self._cache = cache

    @property
    def agent(self) -> str:
        return self._agent

    def allowed_tools(self) -> frozenset[str]:
        allowed = self._registry.allowed_tools(self._agent)
        if WILDCARD in allowed:
            return frozenset(registered_tools())
        return allowed

    async def call(
        self, tool: str, args: dict[str, Any] | None = None, **kwargs: Any
    ) -> ToolCallOutcome:
        """Allowlist check, then the full adapter path (validate -> cache ->
        call -> parse -> evidence). The check happens BEFORE any server or
        cache access."""
        self._registry.check(self._agent, tool)
        return await run_tool(self._session, self._cache, tool, args, **kwargs)
