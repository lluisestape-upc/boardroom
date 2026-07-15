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
