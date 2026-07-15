"""Adapter parsing tests against realistic kicad-mcp-server markdown."""

from __future__ import annotations

import pytest

import samples
from mcp.adapters import (
    NetlistArtifact,
    PcbStatistics,
    PowerDomains,
    PowerIntegrityReport,
    RuleCheckReport,
    SchematicInfo,
    get_adapter,
    registered_tools,
    run_tool,
)
from mcp.errors import (
    AdapterParseError,
    InvalidToolArgumentsError,
    MissingArtifactError,
    ToolExecutionError,
    UnknownToolError,
)

DAY1_TOOLS = (
    "run_erc",
    "get_erc_violations",
    "run_drc",
    "get_drc_violations",
    "generate_netlist",
    "get_netlist_components",
    "get_netlist_nets",
    "extract_power_domains",
    "analyze_pcb_power_integrity",
    "get_schematic_info",
    "get_pcb_statistics",
)


def test_all_day1_tools_registered():
    assert set(DAY1_TOOLS) <= set(registered_tools())


# --- ERC / DRC -------------------------------------------------------------


def test_run_erc_violations_parsed():
    report = get_adapter("run_erc").parse(samples.ERC_VIOLATIONS)
    assert isinstance(report, RuleCheckReport)
    assert report.check == "ERC"
    assert not report.passed
    assert report.path == "C:/boards/demo/demo.kicad_sch"
    assert report.violation_count == 3
    assert report.error_count == 2
    assert report.warning_count == 1
    assert len(report.violations) == 3
    v = report.violations[1]
    assert v.severity == "error"
    assert v.type == "power_pin_not_driven"
    assert v.components == ["U1", "C12"]
    assert report.violations[2].components == []  # N/A
    assert "3 violations" in report.summary()


def test_run_erc_passed():
    report = get_adapter("run_erc").parse(samples.ERC_PASSED)
    assert report.passed
    assert report.violations == []
    assert "clean" in report.summary()


def test_run_erc_check_failed_raises_tool_error():
    with pytest.raises(ToolExecutionError):
        get_adapter("run_erc").parse(samples.ERC_CHECK_FAILED)


def test_run_erc_missing_schematic_raises_missing_artifact():
    with pytest.raises(MissingArtifactError):
        get_adapter("run_erc").parse(samples.ERC_FILE_NOT_FOUND)


def test_get_erc_violations_count_from_header():
    report = get_adapter("get_erc_violations").parse(samples.GET_ERC_VIOLATIONS)
    assert report.violation_count == 2
    assert all(v.severity == "error" for v in report.violations)


def test_run_drc_violations_with_locations():
    report = get_adapter("run_drc").parse(samples.DRC_VIOLATIONS)
    assert report.check == "DRC"
    assert report.path == "C:/boards/demo/demo.kicad_pcb"
    assert report.violation_count == 2
    v = report.violations[0]
    assert v.type == "clearance"
    assert v.x_mm == pytest.approx(12.70)
    assert v.y_mm == pytest.approx(45.10)


def test_run_drc_passed_and_missing():
    assert get_adapter("run_drc").parse(samples.DRC_PASSED).passed
    with pytest.raises(MissingArtifactError):
        get_adapter("run_drc").parse(samples.DRC_FILE_NOT_FOUND)


def test_garbage_output_raises_parse_error():
    with pytest.raises(AdapterParseError):
        get_adapter("run_erc").parse("<html>totally unexpected</html>")


# --- Netlist ---------------------------------------------------------------


def test_generate_netlist_success_extracts_path():
    artifact = get_adapter("generate_netlist").parse(samples.NETLIST_OK)
    assert isinstance(artifact, NetlistArtifact)
    assert artifact.netlist_path == "C:/temp/demo.xml"


def test_generate_netlist_cli_missing_raises():
    with pytest.raises(ToolExecutionError):
        get_adapter("generate_netlist").parse(samples.NETLIST_CLI_MISSING)


def test_get_netlist_components_parsed():
    result = get_adapter("get_netlist_components").parse(samples.NETLIST_COMPONENTS)
    assert result.netlist_path == "C:/temp/demo.xml"
    assert result.total == 2
    refs = {c.reference: c for c in result.components}
    assert set(refs) == {"R5", "U1"}
    assert refs["R5"].value == "10k"
    assert refs["R5"].footprint == "Resistor_SMD:R_0603_1608Metric"
    assert refs["R5"].pins == {"1": "VDD_3V3", "2": "/ADC_IN"}
    assert refs["U1"].pins["1"] == "GND"


def test_get_netlist_nets_parsed_with_truncation():
    result = get_adapter("get_netlist_nets").parse(samples.NETLIST_NETS)
    assert result.total == 2
    nets = {n.name: n for n in result.nets}
    gnd = nets["GND"]
    assert gnd.code == "1"
    assert gnd.pin_count == 3
    assert [(p.reference, p.pin) for p in gnd.pins] == [("U1", "1"), ("C3", "2"), ("C4", "2")]
    vdd = nets["VDD_3V3"]
    assert vdd.pin_count == 12
    assert vdd.truncated
    assert len(vdd.pins) == 2  # ellipsis row skipped, not a pin


# --- Power -----------------------------------------------------------------


def test_extract_power_domains_parsed():
    result = get_adapter("extract_power_domains").parse(samples.POWER_DOMAINS)
    assert isinstance(result, PowerDomains)
    assert result.total == 2
    assert result.components[0].reference == "U2"
    assert result.components[0].type == "LDO Regulator"
    assert result.components[1].value == "TPS5430"


def test_extract_power_domains_none_found_is_not_an_error():
    result = get_adapter("extract_power_domains").parse(samples.POWER_DOMAINS_NONE)
    assert result.total == 0
    assert result.components == []
    assert result.note


def test_extract_power_domains_missing_file():
    with pytest.raises(MissingArtifactError):
        get_adapter("extract_power_domains").parse(samples.POWER_DOMAINS_NOT_FOUND)


def test_power_integrity_parsed():
    report = get_adapter("analyze_pcb_power_integrity").parse(samples.POWER_INTEGRITY)
    assert isinstance(report, PowerIntegrityReport)
    assert not report.degraded
    assert report.copper_layers == 4
    assert report.board_thickness_mm == pytest.approx(1.6)
    assert [z.net for z in report.power_zones] == ["VDD_3V3"]
    assert report.power_zones[0].zone_count == 2
    assert [z.net for z in report.gnd_zones] == ["GND"]
    assert "2 zones across 2 layers" in report.gnd_coverage
    tracks = {t.net: t for t in report.power_tracks}
    assert tracks["VDD_3V3"].length_mm == pytest.approx(312.45)
    assert tracks["VDD_3V3"].segments == 87
    assert tracks["VDD_3V3"].min_width_mm == pytest.approx(0.25)
    assert tracks["5V"].max_width_mm == pytest.approx(0.5)
    assert len(report.warnings) == 1  # the GND-layers warning


def test_power_integrity_degraded_variant():
    report = get_adapter("analyze_pcb_power_integrity").parse(
        samples.POWER_INTEGRITY_DEGRADED
    )
    assert report.degraded
    assert report.power_zones[0].layers == "F.Cu"
    assert report.power_zones[0].zone_count is None


# --- Info / stats ----------------------------------------------------------


def test_schematic_info_parsed():
    info = get_adapter("get_schematic_info").parse(samples.SCHEMATIC_INFO)
    assert isinstance(info, SchematicInfo)
    assert info.title == "Cyberdeck Audio Board"
    assert info.revision == "B"
    assert info.total_components == 42
    assert info.total_nets == 58
    assert info.sheet_count == 2
    assert info.components_by_type == {"C": 18, "R": 12, "U": 6}
    assert info.sheets == {"audio": "audio.kicad_sch", "power": "power.kicad_sch"}


def test_schematic_info_missing_file():
    with pytest.raises(MissingArtifactError):
        get_adapter("get_schematic_info").parse(samples.SCHEMATIC_INFO_NOT_FOUND)


def test_pcb_statistics_parsed():
    stats = get_adapter("get_pcb_statistics").parse(samples.PCB_STATISTICS)
    assert isinstance(stats, PcbStatistics)
    assert stats.board_width_mm == pytest.approx(100.0)
    assert stats.board_height_mm == pytest.approx(80.0)
    assert stats.copper_layers == 4
    assert stats.board_thickness_mm == pytest.approx(1.6)
    assert stats.footprints == 42
    assert stats.tracks == 512
    assert stats.vias == 96
    assert stats.zones == 4
    assert stats.nets == 58
    assert stats.smallest_clearance_mm == pytest.approx(0.2)
    assert stats.default_track_width_mm == pytest.approx(0.25)


def test_pcb_statistics_parse_failure_raises():
    with pytest.raises(ToolExecutionError):
        get_adapter("get_pcb_statistics").parse(samples.PCB_STATS_ERROR)


# --- run_tool flow ---------------------------------------------------------


@pytest.mark.asyncio
async def test_run_tool_returns_data_and_evidence(fake_session, cache):
    outcome = await run_tool(
        fake_session, cache, "run_erc", schematic_path="C:/boards/demo/demo.kicad_sch"
    )
    assert isinstance(outcome.data, RuleCheckReport)
    assert outcome.evidence.evidence_id == "EV-0001"
    assert outcome.evidence.tool == "run_erc"
    assert outcome.evidence.raw == samples.ERC_VIOLATIONS
    assert not outcome.cached
    assert outcome.args == {"schematic_path": "C:/boards/demo/demo.kicad_sch"}


@pytest.mark.asyncio
async def test_run_tool_unknown_tool(fake_session, cache):
    with pytest.raises(UnknownToolError):
        await run_tool(fake_session, cache, "render_board_to_png", file_path="x")
    assert fake_session.calls == []


@pytest.mark.asyncio
async def test_run_tool_rejects_bad_args(fake_session, cache):
    with pytest.raises(InvalidToolArgumentsError):
        await run_tool(fake_session, cache, "run_erc", pcb_path="wrong-name.kicad_pcb")
    with pytest.raises(InvalidToolArgumentsError):
        await run_tool(fake_session, cache, "run_erc")  # missing required arg
    assert fake_session.calls == []


@pytest.mark.asyncio
async def test_run_tool_mcp_level_error_is_typed_and_uncached(cache):
    from fake_kicad import FakeKicadSession

    session = FakeKicadSession(mcp_error_tools={"run_drc"})
    with pytest.raises(ToolExecutionError) as exc_info:
        await run_tool(session, cache, "run_drc", pcb_path="C:/b.kicad_pcb")
    assert exc_info.value.tool == "run_drc"
    note = exc_info.value.as_coverage_note()
    assert note["kind"] == "tool_failure"
    assert note["tool"] == "run_drc"
    assert len(cache) == 0


@pytest.mark.asyncio
async def test_run_tool_missing_artifact_flows_through(cache):
    from fake_kicad import FakeKicadSession

    session = FakeKicadSession({"run_drc": samples.DRC_FILE_NOT_FOUND})
    with pytest.raises(MissingArtifactError) as exc_info:
        await run_tool(session, cache, "run_drc", pcb_path="C:/boards/missing.kicad_pcb")
    assert exc_info.value.as_coverage_note()["kind"] == "missing_artifact"
    assert len(cache) == 0  # failures never become evidence
