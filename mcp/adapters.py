"""Typed adapters over the kicad-mcp-server tools.

The server returns *markdown reports*, not JSON (verified against the
Seeed-Studio kicad-mcp-server source). Each adapter therefore bundles:

- a pydantic **request model** (exact server parameter names, extra="forbid"),
- a pydantic **result model** with a ``summary()`` used for evidence entries,
- a **parse function** that converts the markdown into the result model, or
  raises a typed error (:class:`MissingArtifactError` for absent project
  files, :class:`ToolExecutionError` for tool failures,
  :class:`AdapterParseError` for unrecognized output).

Adding a Day-2 tool = one request model (or reuse), one result model, one
``@adapter(...)``-decorated parse function. Nothing else changes: the
registry, evidence cache, and allowlist layer pick it up automatically.

Entry point for the orchestrator: :func:`run_tool` (or, with allowlist
enforcement, ``mcp.allowlist.AgentToolbox.call``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, ValidationError

from .client import SupportsCallTool
from .errors import (
    AdapterParseError,
    BoardRoomMcpError,
    InvalidToolArgumentsError,
    MissingArtifactError,
    ToolExecutionError,
    UnknownToolError,
)
from .evidence import EvidenceCache, EvidenceEntry

# ---------------------------------------------------------------------------
# Markdown parsing helpers (kicad-mcp-server report conventions)
# ---------------------------------------------------------------------------

_KV_RE = re.compile(r"\*\*([^*]+?):\*\*\s*(.*?)\s*$", re.M)
_FLOAT_RE = re.compile(r"-?\d+(?:\.\d+)?")
_NOT_FOUND_RE = re.compile(r"(file not found|no such file|not found:)", re.I)


def _kv(text: str) -> dict[str, str]:
    """All ``**Key:** value`` pairs (first occurrence wins)."""
    out: dict[str, str] = {}
    for key, value in _KV_RE.findall(text):
        out.setdefault(key.strip(), value.strip())
    return out


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_divider(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and set(s) <= set("|-: ")


@dataclass
class _Table:
    section: str | None
    header: list[str]
    rows: list[list[str]]

    def col(self, name: str) -> int | None:
        for i, h in enumerate(self.header):
            if h.lower() == name.lower():
                return i
        return None


def _tables(text: str) -> list[_Table]:
    """All markdown tables, tagged with the nearest preceding heading."""
    lines = text.splitlines()
    tables: list[_Table] = []
    section: str | None = None
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("#"):
            section = stripped.lstrip("#").strip()
        if (
            stripped.startswith("|")
            and i + 1 < len(lines)
            and _is_divider(lines[i + 1])
        ):
            header = _cells(stripped)
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not _is_divider(lines[i]):
                    rows.append(_cells(lines[i]))
                i += 1
            tables.append(_Table(section=section, header=header, rows=rows))
            continue
        i += 1
    return tables


def _table_in_section(text: str, section_prefix: str) -> _Table | None:
    for table in _tables(text):
        if table.section and table.section.lower().startswith(section_prefix.lower()):
            return table
    return None


def _strip_icon(cell: str) -> str:
    """'❌ error' -> 'error' (severity cells carry a leading icon)."""
    parts = cell.split()
    return parts[-1] if parts else ""


def _float(text: str | None) -> float | None:
    if not text:
        return None
    m = _FLOAT_RE.search(text)
    return float(m.group()) if m else None


def _int(text: str | None) -> int | None:
    f = _float(text)
    return int(f) if f is not None else None


def _first_line(raw: str) -> str:
    for line in raw.strip().splitlines():
        if line.strip():
            return line.strip()
    return ""


def _section_body(text: str, heading_prefix: str) -> str:
    """Text between a ``## Heading`` (matched by prefix) and the next heading."""
    lines = text.splitlines()
    body: list[str] = []
    capturing = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip().lower()
            if capturing:
                break
            capturing = title.startswith(heading_prefix.lower())
            continue
        if capturing:
            body.append(line)
    return "\n".join(body)


def _raise_if_missing_artifact(raw: str) -> None:
    if _NOT_FOUND_RE.search(_first_line(raw)):
        raise MissingArtifactError(_first_line(raw), detail=raw)


# ---------------------------------------------------------------------------
# Request models — parameter names mirror the server's tool signatures exactly
# ---------------------------------------------------------------------------


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SchematicPathArgs(_Args):
    schematic_path: str


class ErcViolationsArgs(_Args):
    schematic_path: str
    severity: str = ""  # '', 'error', 'warning'


class PcbPathArgs(_Args):
    pcb_path: str


class DrcViolationsArgs(_Args):
    pcb_path: str
    violation_type: str = ""  # '', 'clearance', 'spacing', ...


class NetlistComponentsArgs(_Args):
    netlist_path: str
    filter_ref: str = ""


class SignalIntegrityArgs(_Args):
    file_path: str
    net_name: str = ""


class TracksByNetArgs(_Args):
    file_path: str
    net_name: str


class TraceConnectionArgs(_Args):
    netlist_path: str
    reference: str
    pin_number: str = ""


class PinFunctionsArgs(_Args):
    schematic_path: str
    reference: str = ""


class GpioConfigArgs(_Args):
    schematic_path: str
    soc_family: str = ""


class DeviceTreeArgs(_Args):
    schematic_path: str
    target_soc: str = "stm32f4"
    output_path: str = ""


class PcbFootprintsArgs(_Args):
    file_path: str
    filter_layer: str | None = None


class SchematicComponentsArgs(_Args):
    file_path: str
    filter_type: str | None = None
    filter_value: str | None = None
    filter_dnp: bool | None = None


class NetlistNetsArgs(_Args):
    netlist_path: str
    filter_pattern: str = ""


class FilePathArgs(_Args):
    file_path: str


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


class ToolReport(BaseModel):
    """Base class for parsed tool outputs."""

    def summary(self) -> str:  # pragma: no cover - overridden
        raise NotImplementedError


class RuleViolation(BaseModel):
    severity: str  # 'error' | 'warning'
    type: str
    description: str
    components: list[str] = []
    x_mm: float | None = None
    y_mm: float | None = None


class RuleCheckReport(ToolReport):
    """Shared shape for ERC and DRC reports/violation listings."""

    check: str  # 'ERC' | 'DRC'
    path: str | None = None
    passed: bool
    error_count: int = 0
    warning_count: int = 0
    violation_count: int = 0
    violations: list[RuleViolation] = []
    truncated: bool = False
    note: str | None = None

    def summary(self) -> str:
        if self.passed:
            return f"{self.check} clean on {self.path or 'design'} (no violations)"
        more = " (list truncated)" if self.truncated else ""
        return (
            f"{self.check} on {self.path or 'design'}: {self.violation_count} "
            f"violations ({self.error_count} errors, {self.warning_count} "
            f"warnings){more}"
        )


class NetlistArtifact(ToolReport):
    netlist_path: str
    note: str | None = None

    def summary(self) -> str:
        return f"Netlist generated at {self.netlist_path}"


class NetlistComponentEntry(BaseModel):
    reference: str
    value: str | None = None
    library: str | None = None
    footprint: str | None = None
    pins: dict[str, str] = {}  # pin number -> net name


class NetlistComponents(ToolReport):
    netlist_path: str | None = None
    total: int = 0
    components: list[NetlistComponentEntry] = []

    def summary(self) -> str:
        shown = len(self.components)
        return f"Netlist lists {self.total} components ({shown} returned after filter)"


class NetPinRef(BaseModel):
    reference: str
    pin: str


class NetlistNetEntry(BaseModel):
    name: str
    code: str | None = None
    pin_count: int = 0
    pins: list[NetPinRef] = []
    truncated: bool = False


class NetlistNets(ToolReport):
    netlist_path: str | None = None
    total: int = 0
    nets: list[NetlistNetEntry] = []

    def summary(self) -> str:
        shown = len(self.nets)
        return f"Netlist lists {self.total} nets ({shown} returned after filter)"


class PowerComponent(BaseModel):
    reference: str
    value: str
    type: str


class PowerDomains(ToolReport):
    schematic_path: str | None = None
    total: int = 0
    components: list[PowerComponent] = []
    note: str | None = None

    def summary(self) -> str:
        if not self.components:
            return "No power-management components found in schematic"
        refs = ", ".join(c.reference for c in self.components[:8])
        return f"{self.total} power components found: {refs}"


class CopperZoneInfo(BaseModel):
    net: str
    zone_count: int | None = None
    layers: str = ""


class PowerTrackStats(BaseModel):
    net: str
    length_mm: float | None = None
    segments: int | None = None
    min_width_mm: float | None = None
    max_width_mm: float | None = None


class PowerIntegrityReport(ToolReport):
    path: str | None = None
    degraded: bool = False  # True when pcbnew was unavailable server-side
    copper_layers: int | None = None
    board_thickness_mm: float | None = None
    power_zones: list[CopperZoneInfo] = []
    gnd_zones: list[CopperZoneInfo] = []
    gnd_coverage: str | None = None
    power_tracks: list[PowerTrackStats] = []
    warnings: list[str] = []

    def summary(self) -> str:
        deg = " [degraded: no pcbnew]" if self.degraded else ""
        return (
            f"Power integrity on {self.path or 'board'}: "
            f"{len(self.power_zones)} power zones, {len(self.gnd_zones)} GND "
            f"zones, {len(self.power_tracks)} power nets routed, "
            f"{len(self.warnings)} warnings{deg}"
        )


class SchematicInfo(ToolReport):
    path: str | None = None
    title: str | None = None
    company: str | None = None
    date: str | None = None
    revision: str | None = None
    total_components: int = 0
    total_nets: int = 0
    sheet_count: int = 0
    components_by_type: dict[str, int] = {}
    sheets: dict[str, str] = {}  # name -> file

    def summary(self) -> str:
        return (
            f"Schematic {self.title or self.path or ''}: "
            f"{self.total_components} components, {self.total_nets} nets, "
            f"{self.sheet_count} sheets"
        )


class PcbStatistics(ToolReport):
    path: str | None = None
    board_width_mm: float | None = None
    board_height_mm: float | None = None
    copper_layers: int | None = None
    board_thickness_mm: float | None = None
    footprints: int | None = None
    pads: int | None = None
    tracks: int | None = None
    vias: int | None = None
    zones: int | None = None
    nets: int | None = None
    smallest_clearance_mm: float | None = None
    default_track_width_mm: float | None = None

    def summary(self) -> str:
        dims = (
            f"{self.board_width_mm} x {self.board_height_mm} mm, "
            if self.board_width_mm is not None
            else ""
        )
        return (
            f"PCB {self.path or ''}: {dims}{self.copper_layers or '?'} layers, "
            f"{self.footprints or 0} footprints, {self.tracks or 0} tracks, "
            f"{self.vias or 0} vias"
        )


# ---------------------------------------------------------------------------
# Adapter registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolAdapter:
    tool: str
    request_model: type[_Args]
    parse: Callable[[str], ToolReport]
    description: str = ""


ADAPTERS: dict[str, ToolAdapter] = {}


def register_adapter(
    tool: str,
    request_model: type[_Args],
    parse: Callable[[str], ToolReport],
    description: str = "",
) -> None:
    ADAPTERS[tool] = ToolAdapter(tool, request_model, parse, description)


def adapter(tool: str, request_model: type[_Args], description: str = ""):
    """Decorator: register ``fn`` as the parse function for ``tool``."""

    def deco(fn: Callable[[str], ToolReport]) -> Callable[[str], ToolReport]:
        register_adapter(tool, request_model, fn, description)
        return fn

    return deco


def get_adapter(tool: str) -> ToolAdapter:
    try:
        return ADAPTERS[tool]
    except KeyError:
        raise UnknownToolError(
            f"no adapter registered for tool {tool!r}", tool=tool
        ) from None


def registered_tools() -> tuple[str, ...]:
    return tuple(sorted(ADAPTERS))


@dataclass(frozen=True)
class ToolCallOutcome:
    """What a specialist gets back from one adapter call."""

    tool: str
    args: dict[str, Any]
    data: ToolReport
    evidence: EvidenceEntry
    cached: bool


async def run_tool(
    session: SupportsCallTool,
    cache: EvidenceCache,
    tool: str,
    args: dict[str, Any] | None = None,
    **kwargs: Any,
) -> ToolCallOutcome:
    """Validate args, call the tool (or hit the evidence cache), parse, and
    return typed data plus its evidence entry.

    Failures never produce evidence entries: they raise typed
    :class:`BoardRoomMcpError` subclasses so a later retry is not poisoned by
    a cached failure and uncited claims stay impossible.
    """
    tool_adapter = get_adapter(tool)
    merged = {**(args or {}), **kwargs}
    try:
        request = tool_adapter.request_model(**merged)
    except ValidationError as exc:
        raise InvalidToolArgumentsError(
            f"invalid arguments for {tool}: {exc.errors(include_url=False)}",
            tool=tool,
        ) from exc
    norm_args = request.model_dump()

    cached_entry = cache.get(tool, norm_args)
    if cached_entry is not None:
        data = _parse_with_tool(tool_adapter, cached_entry.raw)
        return ToolCallOutcome(tool, norm_args, data, cached_entry, cached=True)

    result = await session.call_tool(tool, norm_args)
    if result.is_error:
        raise ToolExecutionError(
            f"MCP server reported an error for {tool}", tool=tool, detail=result.text
        )
    data = _parse_with_tool(tool_adapter, result.text)
    entry = cache.put(tool, norm_args, raw=result.text, summary=data.summary())
    return ToolCallOutcome(tool, norm_args, data, entry, cached=False)


def _parse_with_tool(tool_adapter: ToolAdapter, raw: str) -> ToolReport:
    try:
        return tool_adapter.parse(raw)
    except BoardRoomMcpError as exc:
        if exc.tool is None:
            exc.tool = tool_adapter.tool
        raise


# ---------------------------------------------------------------------------
# ERC / DRC parsing
# ---------------------------------------------------------------------------

_CHECK_FAILURE_MARKERS = (
    "check failed",
    "file not found",
    "unexpected error",
    "report parse error",
    "**error**",
)
_CHECK_PASS_MARKERS = ("check passed", "no erc violations", "no drc violations", "no matching violations")


def _parse_rule_check(raw: str, *, check: str, path_key: str) -> RuleCheckReport:
    first = _first_line(raw).lower()
    if any(marker in first for marker in _CHECK_FAILURE_MARKERS):
        _raise_if_missing_artifact(raw)
        raise ToolExecutionError(_first_line(raw), detail=raw)

    kv = _kv(raw)
    path = kv.get(path_key)
    passed = any(marker in first for marker in _CHECK_PASS_MARKERS)

    violations: list[RuleViolation] = []
    truncated = "... and" in raw
    table = next((t for t in _tables(raw) if t.col("Severity") is not None), None)
    if table is not None:
        i_sev = table.col("Severity")
        i_type = table.col("Type")
        i_desc = table.col("Description")
        i_comp = table.col("Components")
        i_loc = table.col("Location")
        for row in table.rows:
            def cell(idx: int | None) -> str:
                return row[idx] if idx is not None and idx < len(row) else ""

            components: list[str] = []
            comp_cell = cell(i_comp)
            if comp_cell and comp_cell.upper() != "N/A":
                components = [c.strip() for c in comp_cell.split(",") if c.strip()]
            x = y = None
            loc_cell = cell(i_loc)
            if loc_cell:
                nums = _FLOAT_RE.findall(loc_cell)
                if len(nums) >= 2:
                    x, y = float(nums[0]), float(nums[1])
            violations.append(
                RuleViolation(
                    severity=_strip_icon(cell(i_sev)) or "error",
                    type=cell(i_type),
                    description=cell(i_desc),
                    components=components,
                    x_mm=x,
                    y_mm=y,
                )
            )

    if not passed and table is None and "violations detected" not in first and not first.startswith("#"):
        raise AdapterParseError(
            f"unrecognized {check} output: {_first_line(raw)[:120]}", detail=raw
        )

    def _count_line(label: str) -> int | None:
        m = re.search(rf"^-\s*{label}:\s*(\d+)", raw, re.M)
        return int(m.group(1)) if m else None

    error_count = _count_line("Errors")
    warning_count = _count_line("Warnings")
    total = _int(kv.get("Total Violations") or kv.get("Count"))

    if error_count is None:
        error_count = sum(1 for v in violations if v.severity == "error")
    if warning_count is None:
        warning_count = sum(1 for v in violations if v.severity == "warning")
    if total is None:
        total = len(violations)

    return RuleCheckReport(
        check=check,
        path=path,
        passed=passed and not violations,
        error_count=error_count,
        warning_count=warning_count,
        violation_count=total,
        violations=violations,
        truncated=truncated,
    )


@adapter("run_erc", SchematicPathArgs, "Run Electrical Rules Check on a schematic")
def parse_run_erc(raw: str) -> RuleCheckReport:
    return _parse_rule_check(raw, check="ERC", path_key="Schematic")


@adapter("get_erc_violations", ErcViolationsArgs, "Filtered ERC violations")
def parse_get_erc_violations(raw: str) -> RuleCheckReport:
    return _parse_rule_check(raw, check="ERC", path_key="Schematic")


@adapter("run_drc", PcbPathArgs, "Run Design Rules Check on a PCB")
def parse_run_drc(raw: str) -> RuleCheckReport:
    return _parse_rule_check(raw, check="DRC", path_key="PCB")


@adapter("get_drc_violations", DrcViolationsArgs, "Filtered DRC violations")
def parse_get_drc_violations(raw: str) -> RuleCheckReport:
    return _parse_rule_check(raw, check="DRC", path_key="PCB")


# ---------------------------------------------------------------------------
# Netlist tools
# ---------------------------------------------------------------------------


@adapter("generate_netlist", SchematicPathArgs, "Export KiCad XML netlist")
def parse_generate_netlist(raw: str) -> NetlistArtifact:
    first = _first_line(raw)
    if first.startswith("✅"):
        kv = _kv(raw)
        path = kv.get("Output")
        if not path:
            raise AdapterParseError(
                "netlist generation succeeded but no **Output:** path found",
                detail=raw,
            )
        note_match = re.search(r"\*\*Note:\*\*\s*(.+)", raw)
        return NetlistArtifact(
            netlist_path=path, note=note_match.group(1).strip() if note_match else None
        )
    _raise_if_missing_artifact(raw)
    if first.startswith(("⚠️", "❌")):
        raise ToolExecutionError(first, detail=raw)
    raise AdapterParseError(f"unrecognized generate_netlist output: {first[:120]}", detail=raw)


def _heading_path(raw: str, prefix: str) -> str | None:
    m = re.search(rf"^##\s*{prefix}:\s*(.+)$", raw, re.M)
    return m.group(1).strip() if m else None


def _split_h3_sections(raw: str) -> list[tuple[str, str]]:
    """[(heading, body), ...] for every ``### heading`` block."""
    parts = re.split(r"(?m)^###\s+(.+)$", raw)
    sections: list[tuple[str, str]] = []
    for i in range(1, len(parts), 2):
        sections.append((parts[i].strip(), parts[i + 1] if i + 1 < len(parts) else ""))
    return sections


@adapter("get_netlist_components", NetlistComponentsArgs, "Components with net connections")
def parse_get_netlist_components(raw: str) -> NetlistComponents:
    first = _first_line(raw)
    if first.startswith("❌"):
        _raise_if_missing_artifact(raw)
        raise ToolExecutionError(first, detail=raw)

    total = _int(_kv(raw).get("Total Components"))
    components: list[NetlistComponentEntry] = []
    for ref, body in _split_h3_sections(raw):
        kv = _kv(body)
        pins: dict[str, str] = {}
        for table in _tables(body):
            if table.col("Pin") is not None and table.col("Net") is not None:
                i_pin, i_net = table.col("Pin"), table.col("Net")
                for row in table.rows:
                    if len(row) > max(i_pin, i_net):
                        pins[row[i_pin]] = row[i_net]
        components.append(
            NetlistComponentEntry(
                reference=ref,
                value=kv.get("Value"),
                library=kv.get("Library"),
                footprint=kv.get("Footprint"),
                pins=pins,
            )
        )
    if total is None and not components:
        raise AdapterParseError(
            f"unrecognized get_netlist_components output: {first[:120]}", detail=raw
        )
    return NetlistComponents(
        netlist_path=_heading_path(raw, "Components from Netlist"),
        total=total if total is not None else len(components),
        components=components,
    )


@adapter("get_netlist_nets", NetlistNetsArgs, "Nets with pin connections")
def parse_get_netlist_nets(raw: str) -> NetlistNets:
    first = _first_line(raw)
    if first.startswith("❌"):
        _raise_if_missing_artifact(raw)
        raise ToolExecutionError(first, detail=raw)

    total = _int(_kv(raw).get("Total Nets"))
    nets: list[NetlistNetEntry] = []
    for name, body in _split_h3_sections(raw):
        kv = _kv(body)
        pins: list[NetPinRef] = []
        truncated = False
        for table in _tables(body):
            if table.col("Reference") is not None and table.col("Pin") is not None:
                i_ref, i_pin = table.col("Reference"), table.col("Pin")
                for row in table.rows:
                    if len(row) > max(i_ref, i_pin):
                        if row[i_ref].startswith("..."):
                            truncated = True
                            continue
                        pins.append(NetPinRef(reference=row[i_ref], pin=row[i_pin]))
        nets.append(
            NetlistNetEntry(
                name=name,
                code=kv.get("Code"),
                pin_count=_int(kv.get("Connections")) or len(pins),
                pins=pins,
                truncated=truncated,
            )
        )
    if total is None and not nets:
        raise AdapterParseError(
            f"unrecognized get_netlist_nets output: {first[:120]}", detail=raw
        )
    return NetlistNets(
        netlist_path=_heading_path(raw, "Nets from Netlist"),
        total=total if total is not None else len(nets),
        nets=nets,
    )


# ---------------------------------------------------------------------------
# Power tools
# ---------------------------------------------------------------------------


@adapter("extract_power_domains", SchematicPathArgs, "Power domains / regulators from schematic")
def parse_extract_power_domains(raw: str) -> PowerDomains:
    first = _first_line(raw)
    # This tool uses plain "X"/"WARN" prefixes instead of emoji.
    if first.startswith(("X ", "❌")):
        _raise_if_missing_artifact(raw)
        raise ToolExecutionError(first, detail=raw)
    kv = _kv(raw)
    if "No Power Components Found" in first:
        return PowerDomains(
            schematic_path=kv.get("Schematic"),
            total=0,
            components=[],
            note="no power-management components found",
        )
    components: list[PowerComponent] = []
    table = _table_in_section(raw, "Power Components")
    if table is not None:
        i_ref = table.col("Reference")
        i_val = table.col("Component")
        i_type = table.col("Type")
        for row in table.rows:
            if i_ref is not None and i_ref < len(row):
                components.append(
                    PowerComponent(
                        reference=row[i_ref],
                        value=row[i_val] if i_val is not None and i_val < len(row) else "",
                        type=row[i_type] if i_type is not None and i_type < len(row) else "",
                    )
                )
    if not components and "Power Domain Extraction" not in raw:
        raise AdapterParseError(
            f"unrecognized extract_power_domains output: {first[:120]}", detail=raw
        )
    total = _int(kv.get("Total Power Components"))
    return PowerDomains(
        schematic_path=kv.get("Schematic"),
        total=total if total is not None else len(components),
        components=components,
    )


def _zones_from_table(table: _Table | None) -> list[CopperZoneInfo]:
    zones: list[CopperZoneInfo] = []
    if table is None:
        return zones
    i_net = table.col("Net")
    i_layer = table.col("Layer")
    i_layers = table.col("Layers")
    i_count = table.col("Zones")
    for row in table.rows:
        if i_net is None or i_net >= len(row):
            continue
        layers = ""
        if i_layers is not None and i_layers < len(row):
            layers = row[i_layers]
        elif i_layer is not None and i_layer < len(row):
            layers = row[i_layer]
        count = _int(row[i_count]) if i_count is not None and i_count < len(row) else None
        zones.append(CopperZoneInfo(net=row[i_net], zone_count=count, layers=layers))
    return zones


@adapter("analyze_pcb_power_integrity", FilePathArgs, "Zones, power routing, GND coverage")
def parse_analyze_pcb_power_integrity(raw: str) -> PowerIntegrityReport:
    first = _first_line(raw)
    if first.startswith(("❌", "Error", "X ")):
        _raise_if_missing_artifact(raw)
        raise ToolExecutionError(first, detail=raw)
    if "Power Integrity Analysis" not in raw:
        raise AdapterParseError(
            f"unrecognized analyze_pcb_power_integrity output: {first[:120]}", detail=raw
        )

    path_match = re.search(r"# Power Integrity Analysis:\s*(.+)$", raw, re.M)
    board_match = re.search(r"\*\*Board:\*\*\s*(\d+)\s*layers?,\s*([\d.]+)\s*mm", raw)
    coverage_match = re.search(r"\*\*GND Coverage:\*\*\s*(.+)$", raw, re.M)

    power_tracks: list[PowerTrackStats] = []
    track_table = _table_in_section(raw, "Power Net Track Routing")
    if track_table is not None:
        i_net = track_table.col("Net")
        i_len = next((i for i, h in enumerate(track_table.header) if "length" in h.lower()), None)
        i_seg = next((i for i, h in enumerate(track_table.header) if "segment" in h.lower()), None)
        i_min = next((i for i, h in enumerate(track_table.header) if "min" in h.lower()), None)
        i_max = next((i for i, h in enumerate(track_table.header) if "max" in h.lower()), None)
        for row in track_table.rows:
            def cell(idx: int | None) -> str | None:
                return row[idx] if idx is not None and idx < len(row) else None

            if i_net is None or i_net >= len(row):
                continue
            power_tracks.append(
                PowerTrackStats(
                    net=row[i_net],
                    length_mm=_float(cell(i_len)),
                    segments=_int(cell(i_seg)),
                    min_width_mm=_float(cell(i_min)),
                    max_width_mm=_float(cell(i_max)),
                )
            )

    degraded = "pcbnew not available" in raw
    warnings = [
        line.strip().lstrip("⚠️").strip()
        for line in raw.splitlines()
        if line.strip().startswith("⚠️") and "pcbnew not available" not in line
    ]

    return PowerIntegrityReport(
        path=path_match.group(1).strip() if path_match else None,
        degraded=degraded,
        copper_layers=int(board_match.group(1)) if board_match else None,
        board_thickness_mm=float(board_match.group(2)) if board_match else None,
        power_zones=_zones_from_table(_table_in_section(raw, "Power Copper Zones")),
        gnd_zones=_zones_from_table(_table_in_section(raw, "GND Copper Zones")),
        gnd_coverage=coverage_match.group(1).strip() if coverage_match else None,
        power_tracks=power_tracks,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Info / stats tools
# ---------------------------------------------------------------------------


@adapter("get_schematic_info", FilePathArgs, "Schematic metadata and statistics")
def parse_get_schematic_info(raw: str) -> SchematicInfo:
    first = _first_line(raw)
    if first.startswith(("Error", "❌")):
        _raise_if_missing_artifact(raw)
        raise ToolExecutionError(first, detail=raw)
    if "Schematic Information" not in raw:
        raise AdapterParseError(
            f"unrecognized get_schematic_info output: {first[:120]}", detail=raw
        )
    kv = _kv(raw)
    path_match = re.search(r"# Schematic Information:\s*(.+)$", raw, re.M)

    components_by_type: dict[str, int] = {}
    for line in _section_body(raw, "Components by Type").splitlines():
        m = re.match(r"^-\s*(\S+):\s*(\d+)\s*$", line.strip())
        if m:
            components_by_type[m.group(1)] = int(m.group(2))

    sheets: dict[str, str] = {}
    for line in _section_body(raw, "Hierarchical Sheets").splitlines():
        m = re.match(r"^-\s*([^:]+):\s*(.+)$", line.strip())
        if m:
            sheets[m.group(1).strip()] = m.group(2).strip()

    return SchematicInfo(
        path=path_match.group(1).strip() if path_match else None,
        title=kv.get("Title"),
        company=kv.get("Company"),
        date=kv.get("Date"),
        revision=kv.get("Revision"),
        total_components=_int(kv.get("Total Components")) or 0,
        total_nets=_int(kv.get("Total Nets")) or 0,
        sheet_count=_int(kv.get("Hierarchical Sheets")) or 0,
        components_by_type=components_by_type,
        sheets=sheets,
    )


@adapter("get_pcb_statistics", FilePathArgs, "PCB board statistics and design rules")
def parse_get_pcb_statistics(raw: str) -> PcbStatistics:
    first = _first_line(raw)
    if first.startswith(("Error", "❌")):
        _raise_if_missing_artifact(raw)
        raise ToolExecutionError(first, detail=raw)
    if "PCB Statistics" not in raw:
        raise AdapterParseError(
            f"unrecognized get_pcb_statistics output: {first[:120]}", detail=raw
        )
    kv = _kv(raw)
    path_match = re.search(r"# PCB Statistics:\s*(.+)$", raw, re.M)

    width = height = None
    dims = kv.get("Dimensions")
    if dims:
        nums = _FLOAT_RE.findall(dims)
        if len(nums) >= 2:
            width, height = float(nums[0]), float(nums[1])

    return PcbStatistics(
        path=path_match.group(1).strip() if path_match else None,
        board_width_mm=width,
        board_height_mm=height,
        copper_layers=_int(kv.get("Copper Layers") or kv.get("Layers")),
        board_thickness_mm=_float(kv.get("Board Thickness") or kv.get("Thickness")),
        footprints=_int(kv.get("Footprints")),
        pads=_int(kv.get("Total Pads")),
        tracks=_int(kv.get("Track Segments")),
        vias=_int(kv.get("Vias")),
        zones=_int(kv.get("Copper Zones")),
        nets=_int(kv.get("Nets")),
        smallest_clearance_mm=_float(kv.get("Smallest Clearance")),
        default_track_width_mm=_float(kv.get("Default Track Width")),
    )


# ---------------------------------------------------------------------------
# Day-2 result models (formats verified against the kicad-mcp-server source:
# tools/pcb.py, tools/netlist.py, tools/pin_analysis.py, tools/device_tree.py,
# tools/schematic.py)
# ---------------------------------------------------------------------------


def _row_get(table: _Table, row: list[str], *names: str) -> str:
    """First existing cell among column ``names`` (header aliases)."""
    for name in names:
        i = table.col(name)
        if i is not None and i < len(row):
            return row[i]
    return ""


def _pin_name_number(cell: str) -> tuple[str, str]:
    """'GPIO4 (24)' -> ('GPIO4', '24'); plain cells come back with '' number."""
    m = re.match(r"^(.*?)\s*\(([^()]+)\)\s*$", cell.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return cell.strip(), ""


_DEGRADED_MARKER = "pcbnew not available"


class DiffPairStats(BaseModel):
    pair: str
    net_p: str
    net_n: str
    length_p_mm: float | None = None
    length_n_mm: float | None = None
    delta_mm: float | None = None
    status: str = ""  # 'OK' | 'Marginal' | 'Mismatch'


class RfTraceStats(BaseModel):
    net: str
    length_mm: float | None = None
    widths: str = ""
    segments: int | None = None


class SignalNetStats(BaseModel):
    net: str
    length_mm: float | None = None
    segments: int | None = None
    layers: str = ""


class NetDetail(BaseModel):
    net: str
    segments: int | None = None
    total_length_mm: float | None = None


class SignalIntegrityReport(ToolReport):
    path: str | None = None
    degraded: bool = False
    diff_pair_rule_width_mm: float | None = None
    diff_pair_rule_gap_mm: float | None = None
    diff_pairs: list[DiffPairStats] = []
    rf_traces: list[RfTraceStats] = []
    longest_signal_nets: list[SignalNetStats] = []
    top_via_nets: dict[str, int] = {}
    net_detail: NetDetail | None = None
    note: str | None = None

    def summary(self) -> str:
        if self.note:
            return f"Signal integrity on {self.path or 'board'}: {self.note}"
        if self.net_detail is not None:
            return (
                f"Signal integrity detail for net {self.net_detail.net}: "
                f"{self.net_detail.segments or 0} segments, "
                f"{self.net_detail.total_length_mm or 0} mm total"
            )
        mismatched = sum(1 for p in self.diff_pairs if p.status != "OK")
        deg = " [degraded: no pcbnew]" if self.degraded else ""
        return (
            f"Signal integrity on {self.path or 'board'}: "
            f"{len(self.diff_pairs)} diff pairs ({mismatched} mismatched), "
            f"{len(self.rf_traces)} RF traces, "
            f"{len(self.longest_signal_nets)} signal nets ranked{deg}"
        )


class TrackSegment(BaseModel):
    start_x_mm: float | None = None
    start_y_mm: float | None = None
    end_x_mm: float | None = None
    end_y_mm: float | None = None
    width_mm: float | None = None
    layer: str = ""
    length_mm: float | None = None


class TrackVia(BaseModel):
    x_mm: float | None = None
    y_mm: float | None = None
    size_mm: float | None = None
    drill_mm: float | None = None
    span: str = ""


class TrackZone(BaseModel):
    net: str
    layer: str = ""
    filled: bool | None = None


class NetTrackAnalysis(ToolReport):
    net: str
    found: bool = True
    degraded: bool = False
    segment_count: int = 0
    via_count: int = 0
    zone_count: int = 0
    total_length_mm: float | None = None
    layers: list[str] = []
    widths_mm: list[float] = []
    mixed_widths: bool = False
    segments: list[TrackSegment] = []
    vias: list[TrackVia] = []
    zones: list[TrackZone] = []
    suggestions: list[str] = []
    truncated: bool = False

    def summary(self) -> str:
        if not self.found:
            hint = f" (similar nets: {', '.join(self.suggestions[:5])})" if self.suggestions else ""
            return f"No tracks routed for net {self.net!r}{hint}"
        mixed = ", mixed widths" if self.mixed_widths else ""
        return (
            f"Net {self.net}: {self.segment_count} segments, "
            f"{self.total_length_mm or 0} mm on {', '.join(self.layers) or '?'}"
            f", {self.via_count} vias, {self.zone_count} zones{mixed}"
        )


class TracedNet(BaseModel):
    net: str
    pin: str | None = None
    connected_to: list[NetPinRef] = []


class ConnectionTrace(ToolReport):
    reference: str | None = None
    nets: list[TracedNet] = []

    def summary(self) -> str:
        counterparts = sum(len(n.connected_to) for n in self.nets)
        return (
            f"Trace {self.reference or '?'}: {len(self.nets)} nets, "
            f"{counterparts} counterpart pins"
        )


class PinConflict(BaseModel):
    severity: str  # 'error' | 'warning' | 'info'
    type: str
    location: str = ""
    description: str = ""


class PinConflictReport(ToolReport):
    schematic_path: str | None = None
    passed: bool
    total_conflicts: int = 0
    conflicts: list[PinConflict] = []
    truncated: bool = False

    @property
    def error_count(self) -> int:
        return sum(1 for c in self.conflicts if c.severity == "error")

    def summary(self) -> str:
        if self.passed:
            return f"No pin conflicts in {self.schematic_path or 'schematic'}"
        more = " (list truncated)" if self.truncated else ""
        return (
            f"{self.total_conflicts} pin conflicts in "
            f"{self.schematic_path or 'schematic'} ({self.error_count} errors){more}"
        )


class PinValidationReport(ToolReport):
    schematic_path: str | None = None
    passed: bool
    mcu_found: bool = True
    blocked_by_conflicts: bool = False
    conflicts: list[PinConflict] = []
    note: str | None = None

    def summary(self) -> str:
        if self.passed:
            return f"Pin configuration valid for device tree generation ({self.schematic_path})"
        if self.blocked_by_conflicts:
            return (
                f"Pin configuration invalid: {len(self.conflicts)} conflicts block "
                f"device tree generation ({self.schematic_path})"
            )
        return f"Pin configuration validation: {self.note or 'failed'} ({self.schematic_path})"


class PinFunctionEntry(BaseModel):
    component: str
    pin_name: str = ""
    pin_number: str = ""
    pin_type: str = ""
    nets: list[str] = []
    functions: list[str] = []
    mcu_family: str | None = None


class PinFunctionAnalysis(ToolReport):
    schematic_path: str | None = None
    component: str | None = None
    total_pins: int = 0
    pins: list[PinFunctionEntry] = []
    truncated: bool = False
    note: str | None = None

    def summary(self) -> str:
        if self.note:
            return f"Pin function analysis on {self.schematic_path or 'schematic'}: {self.note}"
        scope = f" for {self.component}" if self.component else ""
        return (
            f"Pin function analysis{scope}: {self.total_pins} pins analyzed, "
            f"{sum(1 for p in self.pins if p.functions)} with inferred functions"
        )


class I2cDevice(BaseModel):
    component: str
    value: str = ""
    compatible: str = ""
    address: str | None = None  # '0x76' or None when unknown
    net: str = ""


class I2cDevices(ToolReport):
    schematic_path: str | None = None
    total: int = 0
    devices: list[I2cDevice] = []
    note: str | None = None

    def summary(self) -> str:
        if not self.devices:
            return "No I2C devices found in schematic"
        named = ", ".join(f"{d.component}@{d.address or '?'}" for d in self.devices[:8])
        return f"{self.total} I2C devices: {named}"


class SpiDevice(BaseModel):
    component: str
    value: str = ""
    compatible: str = ""
    net: str = ""


class SpiDevices(ToolReport):
    schematic_path: str | None = None
    total: int = 0
    devices: list[SpiDevice] = []
    note: str | None = None

    def summary(self) -> str:
        if not self.devices:
            return "No SPI devices found in schematic"
        named = ", ".join(d.component for d in self.devices[:8])
        return f"{self.total} SPI devices: {named}"


class GpioPin(BaseModel):
    component: str
    pin_name: str = ""
    pin_number: str = ""
    net: str = ""
    soc: str = ""


class GpioConfig(ToolReport):
    schematic_path: str | None = None
    soc_family: str | None = None
    total: int = 0
    pins: list[GpioPin] = []
    note: str | None = None

    def summary(self) -> str:
        if not self.pins:
            return "No GPIO configurations found in schematic"
        return f"{self.total} GPIO pins extracted ({len({p.component for p in self.pins})} MCUs)"


class DeviceTreeResult(ToolReport):
    schematic_path: str | None = None
    target_soc: str | None = None
    output_path: str | None = None
    gpio_pins: int = 0
    i2c_buses: int = 0
    spi_buses: int = 0
    uarts: int = 0
    dts: str | None = None

    def summary(self) -> str:
        return (
            f"Device tree generated for {self.target_soc or '?'}: "
            f"{self.gpio_pins} GPIOs, {self.i2c_buses} I2C buses, "
            f"{self.spi_buses} SPI buses, {self.uarts} UARTs"
        )


class FootprintEntry(BaseModel):
    reference: str
    value: str = ""
    library: str = ""
    layer: str = ""
    x_mm: float | None = None
    y_mm: float | None = None
    rotation_deg: float | None = None
    pads: int | None = None


class PcbFootprints(ToolReport):
    path: str | None = None
    total: int = 0
    footprints: list[FootprintEntry] = []
    note: str | None = None

    def summary(self) -> str:
        if not self.footprints:
            return f"No footprints found ({self.note or 'empty board or filtered out'})"
        layers = sorted({f.layer for f in self.footprints if f.layer})
        return (
            f"{self.total} footprints on {self.path or 'board'} "
            f"(layers: {', '.join(layers) or '?'})"
        )


class NetRouteStats(BaseModel):
    net: str
    length_mm: float | None = None
    segments: int | None = None
    widths: str = ""
    layers: str = ""


class PcbRoutingReport(ToolReport):
    path: str | None = None
    degraded: bool = False
    board_width_mm: float | None = None
    board_height_mm: float | None = None
    copper_layers: int | None = None
    track_segments: int | None = None
    net_count: int | None = None
    via_count: int | None = None
    zone_count: int | None = None
    track_width_distribution: dict[str, int] = {}
    via_drill_distribution: dict[str, int] = {}
    via_layer_spans: dict[str, int] = {}
    segments_by_layer: dict[str, int] = {}
    top_nets: list[NetRouteStats] = []
    min_track_width_mm: float | None = None
    default_track_width_mm: float | None = None
    smallest_clearance_mm: float | None = None
    warnings: list[str] = []

    def summary(self) -> str:
        deg = " [degraded: no pcbnew]" if self.degraded else ""
        return (
            f"Routing analysis on {self.path or 'board'}: "
            f"{self.track_segments or 0} segments"
            + (f" across {self.net_count} nets" if self.net_count else "")
            + f", {self.via_count or 0} vias, "
            f"{len(self.track_width_distribution)} track widths, "
            f"{len(self.warnings)} warnings{deg}"
        )


class SchematicComponentEntry(BaseModel):
    reference: str
    value: str = ""
    footprint: str | None = None
    library: str = ""
    dnp: bool = False
    in_bom: bool = True


class SchematicComponents(ToolReport):
    path: str | None = None
    total: int = 0
    components: list[SchematicComponentEntry] = []
    note: str | None = None

    def summary(self) -> str:
        if not self.components:
            return f"No schematic components matched ({self.note or 'no filter hits'})"
        dnp = sum(1 for c in self.components if c.dnp)
        extra = f", {dnp} DNP" if dnp else ""
        return f"{self.total} schematic components listed{extra}"


# ---------------------------------------------------------------------------
# Signal tools
# ---------------------------------------------------------------------------


def _diff_pairs_from_table(table: _Table | None) -> list[DiffPairStats]:
    pairs: list[DiffPairStats] = []
    if table is None:
        return pairs
    for row in table.rows:
        pair = _row_get(table, row, "Pair")
        if not pair:
            continue
        pairs.append(
            DiffPairStats(
                pair=pair,
                net_p=_row_get(table, row, "Net P"),
                net_n=_row_get(table, row, "Net N"),
                length_p_mm=_float(_row_get(table, row, "Length P")),
                length_n_mm=_float(_row_get(table, row, "Length N")),
                delta_mm=_float(_row_get(table, row, "Delta")),
                status=_strip_icon(_row_get(table, row, "Status")),
            )
        )
    return pairs


_NO_TRACKS_FOR_NET_RE = re.compile(r"^No tracks(?: or vias)? found for net '(.+)'\.$")


@adapter(
    "analyze_pcb_signal_integrity",
    SignalIntegrityArgs,
    "Diff pair matching, RF traces, longest signal nets",
)
def parse_analyze_pcb_signal_integrity(raw: str) -> SignalIntegrityReport:
    first = _first_line(raw)
    if first.startswith(("Error", "❌", "X ")):
        _raise_if_missing_artifact(raw)
        raise ToolExecutionError(first, detail=raw)
    if first == "No tracks found in PCB file.":
        return SignalIntegrityReport(note="no tracks in PCB (board unrouted)")
    no_net = _NO_TRACKS_FOR_NET_RE.match(first)
    if no_net:
        return SignalIntegrityReport(note=f"no tracks found for net '{no_net.group(1)}'")
    if "Signal Integrity Analysis" not in raw:
        raise AdapterParseError(
            f"unrecognized analyze_pcb_signal_integrity output: {first[:120]}", detail=raw
        )

    path_match = re.search(r"# Signal Integrity Analysis:\s*(.+)$", raw, re.M)
    rules_match = re.search(
        r"\*\*Diff Pair Design Rules:\*\*\s*width=([\d.]+)\s*mm,\s*gap=([\d.]+)\s*mm", raw
    )

    net_detail: NetDetail | None = None
    detail_match = re.search(
        r"^##\s*Net:\s*(.+)\n\*\*Segments:\*\*\s*(\d+),\s*\*\*Total Length:\*\*\s*([\d.]+)\s*mm",
        raw,
        re.M,
    )
    if detail_match:
        net_detail = NetDetail(
            net=detail_match.group(1).strip(),
            segments=int(detail_match.group(2)),
            total_length_mm=float(detail_match.group(3)),
        )

    rf_traces: list[RfTraceStats] = []
    rf_table = _table_in_section(raw, "RF Traces")
    if rf_table is not None:
        for row in rf_table.rows:
            net = _row_get(rf_table, row, "Net")
            if net:
                rf_traces.append(
                    RfTraceStats(
                        net=net,
                        length_mm=_float(_row_get(rf_table, row, "Length")),
                        widths=_row_get(rf_table, row, "Widths"),
                        segments=_int(_row_get(rf_table, row, "Segments")),
                    )
                )

    longest: list[SignalNetStats] = []
    signals_table = _table_in_section(raw, "Longest Signal Nets")
    if signals_table is not None:
        for row in signals_table.rows:
            net = _row_get(signals_table, row, "Net")
            if net:
                longest.append(
                    SignalNetStats(
                        net=net,
                        length_mm=_float(_row_get(signals_table, row, "Length (mm)", "Length")),
                        segments=_int(_row_get(signals_table, row, "Segments")),
                        layers=_row_get(signals_table, row, "Layers"),
                    )
                )

    top_via_nets: dict[str, int] = {}
    via_table = _table_in_section(raw, "Nets with Most Vias")
    if via_table is not None:
        for row in via_table.rows:
            net = _row_get(via_table, row, "Net")
            count = _int(_row_get(via_table, row, "Via Count"))
            if net and count is not None:
                top_via_nets[net] = count

    return SignalIntegrityReport(
        path=path_match.group(1).strip() if path_match else None,
        degraded=_DEGRADED_MARKER in raw,
        diff_pair_rule_width_mm=float(rules_match.group(1)) if rules_match else None,
        diff_pair_rule_gap_mm=float(rules_match.group(2)) if rules_match else None,
        diff_pairs=_diff_pairs_from_table(_table_in_section(raw, "Differential Pair Analysis")),
        rf_traces=rf_traces,
        longest_signal_nets=longest,
        top_via_nets=top_via_nets,
        net_detail=net_detail,
    )


@adapter("find_tracks_by_net", TracksByNetArgs, "Track segments, vias, zones for one net")
def parse_find_tracks_by_net(raw: str) -> NetTrackAnalysis:
    first = _first_line(raw)
    if first.startswith(("Error", "❌", "X ")):
        _raise_if_missing_artifact(raw)
        raise ToolExecutionError(first, detail=raw)

    no_net = _NO_TRACKS_FOR_NET_RE.match(first)
    if no_net:
        return NetTrackAnalysis(net=no_net.group(1), found=False)

    # "Did you mean" variant: exact match failed but similar nets exist.
    sugg_match = re.match(r"^# Tracks for '(.+)'$", first)
    if sugg_match and "Exact match not found" in raw:
        suggestions = re.findall(r"^-\s*`([^`]+)`", raw, re.M)
        return NetTrackAnalysis(net=sugg_match.group(1), found=False, suggestions=suggestions)

    head_match = re.match(r"^# Track Analysis:\s*(.+)$", first)
    if not head_match:
        raise AdapterParseError(
            f"unrecognized find_tracks_by_net output: {first[:120]}", detail=raw
        )

    kv = _kv(raw)
    layers_raw = kv.get("Layers Used", "")
    layers = [] if layers_raw in ("", "N/A") else [s.strip() for s in layers_raw.split(",")]
    widths_mm = [float(w) for w in _FLOAT_RE.findall(kv.get("Track Widths", ""))]

    segments: list[TrackSegment] = []
    seg_table = _table_in_section(raw, "Track Segments")
    if seg_table is not None:
        for row in seg_table.rows:
            if _row_get(seg_table, row, "#").startswith("..."):
                continue
            start = _FLOAT_RE.findall(_row_get(seg_table, row, "Start"))
            end = _FLOAT_RE.findall(_row_get(seg_table, row, "End"))
            segments.append(
                TrackSegment(
                    start_x_mm=float(start[0]) if len(start) >= 2 else None,
                    start_y_mm=float(start[1]) if len(start) >= 2 else None,
                    end_x_mm=float(end[0]) if len(end) >= 2 else None,
                    end_y_mm=float(end[1]) if len(end) >= 2 else None,
                    width_mm=_float(_row_get(seg_table, row, "Width")),
                    layer=_row_get(seg_table, row, "Layer"),
                    length_mm=_float(_row_get(seg_table, row, "Length")),
                )
            )

    vias: list[TrackVia] = []
    via_table = _table_in_section(raw, "Vias")
    if via_table is not None:
        for row in via_table.rows:
            if _row_get(via_table, row, "#").startswith("..."):
                continue
            pos = _FLOAT_RE.findall(_row_get(via_table, row, "Position"))
            vias.append(
                TrackVia(
                    x_mm=float(pos[0]) if len(pos) >= 2 else None,
                    y_mm=float(pos[1]) if len(pos) >= 2 else None,
                    size_mm=_float(_row_get(via_table, row, "Size")),
                    drill_mm=_float(_row_get(via_table, row, "Drill")),
                    span=_row_get(via_table, row, "Span", "Layers"),
                )
            )

    zones: list[TrackZone] = []
    zone_table = _table_in_section(raw, "Copper Zones")
    if zone_table is not None:
        for row in zone_table.rows:
            net = _row_get(zone_table, row, "Net")
            if not net:
                continue
            filled_cell = _row_get(zone_table, row, "Filled")
            zones.append(
                TrackZone(
                    net=net,
                    layer=_row_get(zone_table, row, "Layer"),
                    filled=None if not filled_cell else filled_cell.lower() == "yes",
                )
            )

    return NetTrackAnalysis(
        net=head_match.group(1).strip(),
        degraded=_DEGRADED_MARKER in raw,
        segment_count=_int(kv.get("Track Segments")) or 0,
        via_count=_int(kv.get("Vias")) or 0,
        zone_count=_int(kv.get("Copper Zones")) or 0,
        total_length_mm=_float(kv.get("Total Track Length")),
        layers=layers,
        widths_mm=widths_mm,
        mixed_widths="Mixed track widths detected" in raw,
        segments=segments,
        vias=vias,
        zones=zones,
        truncated="more segments" in raw or "more vias" in raw,
    )


# ---------------------------------------------------------------------------
# Netlist connection tracing
# ---------------------------------------------------------------------------


def _ref_pin_table(body: str) -> list[NetPinRef]:
    pins: list[NetPinRef] = []
    for table in _tables(body):
        if table.col("Reference") is not None and table.col("Pin") is not None:
            for row in table.rows:
                ref = _row_get(table, row, "Reference")
                if ref and not ref.startswith("..."):
                    pins.append(NetPinRef(reference=ref, pin=_row_get(table, row, "Pin")))
    return pins


@adapter("trace_netlist_connection", TraceConnectionArgs, "Pin-accurate connection trace via netlist")
def parse_trace_netlist_connection(raw: str) -> ConnectionTrace:
    first = _first_line(raw)
    if first.startswith("❌"):
        _raise_if_missing_artifact(raw)
        raise ToolExecutionError(first, detail=raw)

    ref_match = re.search(r"^##\s*Netlist Connection Trace:\s*(.+)$", raw, re.M)
    if not ref_match:
        raise AdapterParseError(
            f"unrecognized trace_netlist_connection output: {first[:120]}", detail=raw
        )
    reference = ref_match.group(1).strip()

    nets: list[TracedNet] = []
    if "**Total Nets:**" in raw:
        # All-pins variant: one "### Net: NAME" section per connected net.
        for heading, body in _split_h3_sections(raw):
            if not heading.startswith("Net:"):
                continue
            nets.append(
                TracedNet(
                    net=heading.removeprefix("Net:").strip(),
                    pin=_kv(body).get("Pin"),
                    connected_to=_ref_pin_table(body),
                )
            )
    else:
        # Single-pin variant: **Pin:** / **Net:** header + one connections table.
        kv = _kv(raw)
        net_name = kv.get("Net")
        if net_name is None:
            raise AdapterParseError(
                f"trace_netlist_connection output has no **Net:** field: {first[:120]}",
                detail=raw,
            )
        nets.append(
            TracedNet(net=net_name, pin=kv.get("Pin"), connected_to=_ref_pin_table(raw))
        )

    return ConnectionTrace(reference=reference, nets=nets)


# ---------------------------------------------------------------------------
# Pin tools
# ---------------------------------------------------------------------------


def _conflicts_from_table(raw: str) -> tuple[list[PinConflict], bool]:
    conflicts: list[PinConflict] = []
    table = next((t for t in _tables(raw) if t.col("Severity") is not None), None)
    if table is not None:
        for row in table.rows:
            sev = _strip_icon(_row_get(table, row, "Severity"))
            if not sev:
                continue
            conflicts.append(
                PinConflict(
                    severity=sev,
                    type=_row_get(table, row, "Type"),
                    location=_row_get(table, row, "Location"),
                    description=_row_get(table, row, "Description"),
                )
            )
    truncated = "more conflicts" in raw
    return conflicts, truncated


@adapter("detect_pin_conflicts", SchematicPathArgs, "Electrical pin conflicts from netlist")
def parse_detect_pin_conflicts(raw: str) -> PinConflictReport:
    first = _first_line(raw)
    kv = _kv(raw)
    if "No Pin Conflicts Detected" in first:
        return PinConflictReport(schematic_path=kv.get("Schematic"), passed=True)
    if "Pin Conflicts Detected" in first:
        conflicts, truncated = _conflicts_from_table(raw)
        total = _int(kv.get("Total Conflicts"))
        return PinConflictReport(
            schematic_path=kv.get("Schematic"),
            passed=False,
            total_conflicts=total if total is not None else len(conflicts),
            conflicts=conflicts,
            truncated=truncated,
        )
    if first.startswith("❌"):
        _raise_if_missing_artifact(raw)
        raise ToolExecutionError(first, detail=raw)
    raise AdapterParseError(
        f"unrecognized detect_pin_conflicts output: {first[:120]}", detail=raw
    )


@adapter(
    "validate_pin_configuration",
    SchematicPathArgs,
    "Pin configuration readiness for device tree generation",
)
def parse_validate_pin_configuration(raw: str) -> PinValidationReport:
    first = _first_line(raw)
    kv = _kv(raw)
    # This tool uses plain "OK"/"WARN"/"X" prefixes instead of emoji.
    if "Pin Configuration Validation Passed" in first:
        return PinValidationReport(schematic_path=kv.get("Schematic"), passed=True)
    if "No MCU Component Found" in first:
        return PinValidationReport(
            schematic_path=kv.get("Schematic"),
            passed=False,
            mcu_found=False,
            note="no MCU component found (device tree generation not applicable)",
        )
    if "Pin Configuration Validation Failed" in first:
        conflicts, _ = _conflicts_from_table(raw)
        return PinValidationReport(
            schematic_path=kv.get("Schematic"),
            passed=False,
            blocked_by_conflicts=True,
            conflicts=conflicts,
            note="pin conflicts block device tree generation",
        )
    if first.startswith(("X ", "❌")):
        _raise_if_missing_artifact(raw)
        raise ToolExecutionError(first, detail=raw)
    raise AdapterParseError(
        f"unrecognized validate_pin_configuration output: {first[:120]}", detail=raw
    )


@adapter("analyze_pin_functions", PinFunctionsArgs, "Inferred pin functions from net names")
def parse_analyze_pin_functions(raw: str) -> PinFunctionAnalysis:
    first = _first_line(raw)
    if first.startswith("❌"):
        if "Component not found" in first:
            raise ToolExecutionError(first, detail=raw)
        _raise_if_missing_artifact(raw)
        raise ToolExecutionError(first, detail=raw)
    kv = _kv(raw)
    if "No Pin Analysis Available" in first:
        return PinFunctionAnalysis(
            schematic_path=kv.get("Schematic"),
            component=kv.get("Component"),
            total_pins=0,
            note="no pin information could be extracted",
        )
    if "Pin Function Analysis" not in raw:
        raise AdapterParseError(
            f"unrecognized analyze_pin_functions output: {first[:120]}", detail=raw
        )

    pins: list[PinFunctionEntry] = []
    table = _table_in_section(raw, "Pin Details")
    if table is not None:
        for row in table.rows:
            component = _row_get(table, row, "Component")
            if not component:
                continue
            name, number = _pin_name_number(_row_get(table, row, "Pin"))
            nets_cell = re.sub(r"\(\+\d+ more\)", "", _row_get(table, row, "Nets")).strip()
            nets = (
                []
                if nets_cell in ("", "N/A")
                else [n.strip() for n in nets_cell.split(",") if n.strip()]
            )
            functions_cell = _row_get(table, row, "Inferred Functions")
            functions = (
                []
                if functions_cell in ("", "Unknown")
                else [f.strip() for f in functions_cell.split(",") if f.strip()]
            )
            family = _row_get(table, row, "MCU Family")
            pins.append(
                PinFunctionEntry(
                    component=component,
                    pin_name=name,
                    pin_number=number,
                    pin_type=_row_get(table, row, "Type"),
                    nets=nets,
                    functions=functions,
                    mcu_family=None if family in ("", "N/A") else family,
                )
            )

    total = _int(kv.get("Total Pins Analyzed"))
    return PinFunctionAnalysis(
        schematic_path=kv.get("Schematic"),
        component=kv.get("Component"),
        total_pins=total if total is not None else len(pins),
        pins=pins,
        truncated="more pins" in raw,
    )


# ---------------------------------------------------------------------------
# Firmware tools
# ---------------------------------------------------------------------------


def _dts_block(raw: str) -> str | None:
    m = re.search(r"```dts\n(.*?)```", raw, re.S)
    return m.group(1).rstrip() if m else None


@adapter("extract_i2c_devices", SchematicPathArgs, "I2C devices with inferred addresses")
def parse_extract_i2c_devices(raw: str) -> I2cDevices:
    first = _first_line(raw)
    # This tool uses plain "X"/"WARN" prefixes instead of emoji.
    if first.startswith(("X ", "❌")):
        _raise_if_missing_artifact(raw)
        raise ToolExecutionError(first, detail=raw)
    kv = _kv(raw)
    if "No I2C Devices Found" in first:
        return I2cDevices(
            schematic_path=kv.get("Schematic"), total=0, note="no I2C devices found"
        )
    if "I2C Device Extraction" not in raw:
        raise AdapterParseError(
            f"unrecognized extract_i2c_devices output: {first[:120]}", detail=raw
        )
    devices: list[I2cDevice] = []
    table = _table_in_section(raw, "I2C Device Details")
    if table is not None:
        for row in table.rows:
            component = _row_get(table, row, "Component")
            if not component:
                continue
            address = _row_get(table, row, "Address")
            devices.append(
                I2cDevice(
                    component=component,
                    value=_row_get(table, row, "Device"),
                    compatible=_row_get(table, row, "Compatible"),
                    address=None if address in ("", "Unknown") else address,
                    net=_row_get(table, row, "Net"),
                )
            )
    total = _int(kv.get("Total I2C Devices"))
    return I2cDevices(
        schematic_path=kv.get("Schematic"),
        total=total if total is not None else len(devices),
        devices=devices,
    )


@adapter("extract_spi_devices", SchematicPathArgs, "SPI devices from schematic nets")
def parse_extract_spi_devices(raw: str) -> SpiDevices:
    first = _first_line(raw)
    if first.startswith(("X ", "❌")):
        _raise_if_missing_artifact(raw)
        raise ToolExecutionError(first, detail=raw)
    kv = _kv(raw)
    if "No SPI Devices Found" in first:
        return SpiDevices(
            schematic_path=kv.get("Schematic"), total=0, note="no SPI devices found"
        )
    if "SPI Device Extraction" not in raw:
        raise AdapterParseError(
            f"unrecognized extract_spi_devices output: {first[:120]}", detail=raw
        )
    devices: list[SpiDevice] = []
    table = _table_in_section(raw, "SPI Device Details")
    if table is not None:
        for row in table.rows:
            component = _row_get(table, row, "Component")
            if not component:
                continue
            devices.append(
                SpiDevice(
                    component=component,
                    value=_row_get(table, row, "Device"),
                    compatible=_row_get(table, row, "Compatible"),
                    net=_row_get(table, row, "Net"),
                )
            )
    total = _int(kv.get("Total SPI Devices"))
    return SpiDevices(
        schematic_path=kv.get("Schematic"),
        total=total if total is not None else len(devices),
        devices=devices,
    )


@adapter("extract_gpio_config", GpioConfigArgs, "GPIO pin configuration from MCU nets")
def parse_extract_gpio_config(raw: str) -> GpioConfig:
    first = _first_line(raw)
    if first.startswith(("X ", "❌")):
        _raise_if_missing_artifact(raw)
        raise ToolExecutionError(first, detail=raw)
    kv = _kv(raw)
    if "No GPIO Configurations Found" in first:
        return GpioConfig(
            schematic_path=kv.get("Schematic"),
            soc_family=kv.get("SOC Family Filter") or kv.get("SOC Family"),
            total=0,
            note="no GPIO configurations found",
        )
    if "GPIO Configuration Extraction" not in raw:
        raise AdapterParseError(
            f"unrecognized extract_gpio_config output: {first[:120]}", detail=raw
        )
    pins: list[GpioPin] = []
    table = _table_in_section(raw, "GPIO Pin Details")
    if table is not None:
        for row in table.rows:
            component = _row_get(table, row, "Component")
            if not component:
                continue
            name, number = _pin_name_number(_row_get(table, row, "Pin"))
            pins.append(
                GpioPin(
                    component=component,
                    pin_name=name,
                    pin_number=number,
                    net=_row_get(table, row, "Net"),
                    soc=_row_get(table, row, "SOC"),
                )
            )
    total = _int(kv.get("Total GPIO Pins"))
    return GpioConfig(
        schematic_path=kv.get("Schematic"),
        soc_family=kv.get("SOC Family"),
        total=total if total is not None else len(pins),
        pins=pins,
    )


@adapter("generate_device_tree", DeviceTreeArgs, "Device tree source from schematic")
def parse_generate_device_tree(raw: str) -> DeviceTreeResult:
    first = _first_line(raw)
    if first.startswith(("X ", "❌")):
        _raise_if_missing_artifact(raw)
        raise ToolExecutionError(first, detail=raw)
    if "Device Tree Generated Successfully" not in first:
        raise AdapterParseError(
            f"unrecognized generate_device_tree output: {first[:120]}", detail=raw
        )
    kv = _kv(raw)
    return DeviceTreeResult(
        schematic_path=kv.get("Schematic"),
        target_soc=kv.get("Target SOC"),
        output_path=kv.get("Output"),
        gpio_pins=_int(kv.get("GPIO Pins")) or 0,
        i2c_buses=_int(kv.get("I2C Buses")) or 0,
        spi_buses=_int(kv.get("SPI Buses")) or 0,
        uarts=_int(kv.get("UARTs")) or 0,
        dts=_dts_block(raw),
    )


# ---------------------------------------------------------------------------
# Listing tools (footprints / routing / schematic components)
# ---------------------------------------------------------------------------


def _listing_total(raw: str) -> int | None:
    m = re.search(r"^Total:\s*(\d+)", raw, re.M)
    return int(m.group(1)) if m else None


@adapter("list_pcb_footprints", PcbFootprintsArgs, "All footprints with position and layer")
def parse_list_pcb_footprints(raw: str) -> PcbFootprints:
    first = _first_line(raw)
    if first.startswith(("Error", "❌")):
        _raise_if_missing_artifact(raw)
        raise ToolExecutionError(first, detail=raw)
    if first == "No footprints found.":
        return PcbFootprints(total=0, note="no footprints found")
    path_match = re.match(r"^# Footprints in\s*(.+)$", first)
    if not path_match:
        raise AdapterParseError(
            f"unrecognized list_pcb_footprints output: {first[:120]}", detail=raw
        )
    footprints: list[FootprintEntry] = []
    table = next((t for t in _tables(raw) if t.col("Reference") is not None), None)
    if table is not None:
        for row in table.rows:
            ref = _row_get(table, row, "Reference")
            if not ref:
                continue
            pos = _FLOAT_RE.findall(_row_get(table, row, "Position"))
            footprints.append(
                FootprintEntry(
                    reference=ref,
                    value=_row_get(table, row, "Value"),
                    # pcbnew parser emits a Library column; text parser Footprint.
                    library=_row_get(table, row, "Library", "Footprint"),
                    layer=_row_get(table, row, "Layer"),
                    x_mm=float(pos[0]) if len(pos) >= 2 else None,
                    y_mm=float(pos[1]) if len(pos) >= 2 else None,
                    rotation_deg=_float(_row_get(table, row, "Rotation")),
                    pads=_int(_row_get(table, row, "Pads")),
                )
            )
    total = _listing_total(raw)
    return PcbFootprints(
        path=path_match.group(1).strip(),
        total=total if total is not None else len(footprints),
        footprints=footprints,
    )


def _count_dist(table: _Table | None, key_col: str, count_col: str = "Count") -> dict[str, int]:
    dist: dict[str, int] = {}
    if table is None:
        return dist
    for row in table.rows:
        key = _row_get(table, row, key_col)
        count = _int(_row_get(table, row, count_col))
        if key and count is not None:
            dist[key] = count
    return dist


@adapter("analyze_pcb_nets", FilePathArgs, "Routing analysis: widths, vias, layers, top nets")
def parse_analyze_pcb_nets(raw: str) -> PcbRoutingReport:
    first = _first_line(raw)
    if first.startswith(("Error", "❌")):
        _raise_if_missing_artifact(raw)
        raise ToolExecutionError(first, detail=raw)
    path_match = re.match(r"^# PCB Routing Analysis:\s*(.+)$", first)
    if not path_match:
        raise AdapterParseError(
            f"unrecognized analyze_pcb_nets output: {first[:120]}", detail=raw
        )
    kv = _kv(raw)
    degraded = _DEGRADED_MARKER in raw

    board_match = re.search(
        r"\*\*Board:\*\*\s*([\d.]+)\s*x\s*([\d.]+)\s*mm,\s*(\d+)\s*copper layers", raw
    )
    tracks_match = re.search(r"\*\*Tracks:\*\*\s*(\d+)\s*segments across\s*(\d+)\s*nets", raw)

    spans: dict[str, int] = {}
    for line in _section_body(raw, "Via Layer Spans").splitlines():
        m = re.match(r"^-\s*(.+?):\s*(\d+)x\s*$", line.strip())
        if m:
            spans[m.group(1).strip()] = int(m.group(2))

    top_nets: list[NetRouteStats] = []
    top_table = _table_in_section(raw, "Top 20 Nets by Track Length")
    if top_table is not None:
        for row in top_table.rows:
            net = _row_get(top_table, row, "Net")
            if net:
                top_nets.append(
                    NetRouteStats(
                        net=net,
                        length_mm=_float(_row_get(top_table, row, "Length (mm)", "Length")),
                        segments=_int(_row_get(top_table, row, "Segments")),
                        widths=_row_get(top_table, row, "Widths"),
                        layers=_row_get(top_table, row, "Layers"),
                    )
                )

    warnings = [
        line.strip().lstrip("⚠️").strip()
        for line in raw.splitlines()
        if line.strip().startswith("⚠️") and _DEGRADED_MARKER not in line
    ]

    return PcbRoutingReport(
        path=path_match.group(1).strip(),
        degraded=degraded,
        board_width_mm=float(board_match.group(1)) if board_match else None,
        board_height_mm=float(board_match.group(2)) if board_match else None,
        copper_layers=int(board_match.group(3)) if board_match else None,
        track_segments=(
            int(tracks_match.group(1)) if tracks_match else _int(kv.get("Track Segments"))
        ),
        net_count=int(tracks_match.group(2)) if tracks_match else None,
        via_count=_int(kv.get("Vias") or kv.get("Total vias")),
        zone_count=_int(kv.get("Zones") or kv.get("Copper Zones")),
        track_width_distribution=_count_dist(
            _table_in_section(raw, "Track Width Distribution"), "Width"
        ),
        via_drill_distribution=_count_dist(
            _table_in_section(raw, "Via Drill Distribution"), "Drill Size"
        ),
        via_layer_spans=spans,
        segments_by_layer=_count_dist(
            _table_in_section(raw, "Track Segments by Layer"), "Layer", "Segments"
        ),
        top_nets=top_nets,
        min_track_width_mm=_float(kv.get("Min track width in design")),
        default_track_width_mm=_float(kv.get("Default track width (design rules)")),
        smallest_clearance_mm=_float(kv.get("Smallest clearance")),
        warnings=warnings,
    )


@adapter(
    "list_schematic_components",
    SchematicComponentsArgs,
    "All schematic components with value/footprint/DNP",
)
def parse_list_schematic_components(raw: str) -> SchematicComponents:
    first = _first_line(raw)
    if first.startswith(("Error", "❌")):
        _raise_if_missing_artifact(raw)
        raise ToolExecutionError(first, detail=raw)
    if first == "No components found matching the specified criteria.":
        return SchematicComponents(total=0, note="no components matched the filters")
    path_match = re.match(r"^# Components in\s*(.+)$", first)
    if not path_match:
        raise AdapterParseError(
            f"unrecognized list_schematic_components output: {first[:120]}", detail=raw
        )
    components: list[SchematicComponentEntry] = []
    table = next((t for t in _tables(raw) if t.col("Reference") is not None), None)
    if table is not None:
        for row in table.rows:
            ref = _row_get(table, row, "Reference")
            if not ref:
                continue
            footprint = _row_get(table, row, "Footprint")
            components.append(
                SchematicComponentEntry(
                    reference=ref,
                    value=_row_get(table, row, "Value"),
                    footprint=None if footprint in ("", "-") else footprint,
                    library=_row_get(table, row, "Library"),
                    # DNP / In BOM columns only appear when a non-default flag
                    # exists somewhere in the listing; cells are blank otherwise.
                    dnp=_row_get(table, row, "DNP").strip().lower() == "yes",
                    in_bom=_row_get(table, row, "In BOM").strip().lower() != "no",
                )
            )
    total = _listing_total(raw)
    return SchematicComponents(
        path=path_match.group(1).strip(),
        total=total if total is not None else len(components),
        components=components,
    )
