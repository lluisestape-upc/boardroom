"""Day-2 adapter parsing tests (signal, netlist trace, pins, firmware, listings).

Sample formats in samples.py are verified against the kicad-mcp-server source
(tools/pcb.py, tools/netlist.py, tools/pin_analysis.py, tools/device_tree.py,
tools/schematic.py).
"""

from __future__ import annotations

import pytest

import samples
from mcp.adapters import (
    ConnectionTrace,
    DeviceTreeResult,
    GpioConfig,
    I2cDevices,
    NetTrackAnalysis,
    PcbFootprints,
    PcbRoutingReport,
    PinConflictReport,
    PinFunctionAnalysis,
    PinValidationReport,
    SchematicComponents,
    SignalIntegrityReport,
    SpiDevices,
    get_adapter,
    registered_tools,
    run_tool,
)
from mcp.allowlist import DEFAULT_ALLOWLIST, WILDCARD
from mcp.errors import (
    AdapterParseError,
    InvalidToolArgumentsError,
    MissingArtifactError,
    ToolExecutionError,
)

DAY2_TOOLS = (
    "analyze_pcb_signal_integrity",
    "find_tracks_by_net",
    "trace_netlist_connection",
    "detect_pin_conflicts",
    "validate_pin_configuration",
    "analyze_pin_functions",
    "extract_i2c_devices",
    "extract_spi_devices",
    "extract_gpio_config",
    "generate_device_tree",
    "list_pcb_footprints",
    "analyze_pcb_nets",
    "list_schematic_components",
)


def test_all_day2_tools_registered():
    assert set(DAY2_TOOLS) <= set(registered_tools())


def test_every_allowlisted_tool_has_an_adapter():
    """The allowlist is a stable contract; after Day 2 every named tool must
    resolve to an adapter (no more UnknownToolError windows)."""
    named = set().union(*DEFAULT_ALLOWLIST.values()) - {WILDCARD}
    assert named <= set(registered_tools())


# --- analyze_pcb_signal_integrity -------------------------------------------


def test_signal_integrity_parsed():
    report = get_adapter("analyze_pcb_signal_integrity").parse(samples.SIGNAL_INTEGRITY)
    assert isinstance(report, SignalIntegrityReport)
    assert report.path == "C:/boards/demo/demo.kicad_pcb"
    assert not report.degraded
    assert report.diff_pair_rule_width_mm == pytest.approx(0.2)
    assert report.diff_pair_rule_gap_mm == pytest.approx(0.2)
    pairs = {p.pair: p for p in report.diff_pairs}
    assert set(pairs) == {"USB", "USB_C"}
    assert pairs["USB"].status == "OK"
    assert pairs["USB"].delta_mm == pytest.approx(0.05)
    assert pairs["USB_C"].status == "Mismatch"
    assert pairs["USB_C"].net_n == "USB_C_N"
    assert [t.net for t in report.rf_traces] == ["ANT_FEED"]
    assert report.rf_traces[0].length_mm == pytest.approx(12.3)
    assert [n.net for n in report.longest_signal_nets] == ["/ADC_IN", "I2S_DOUT"]
    assert report.longest_signal_nets[0].segments == 22
    assert report.top_via_nets == {"GND": 44, "VDD_3V3": 12}
    assert "1 mismatched" in report.summary()


def test_signal_integrity_net_detail_variant():
    report = get_adapter("analyze_pcb_signal_integrity").parse(
        samples.SIGNAL_INTEGRITY_NET_DETAIL
    )
    assert report.net_detail is not None
    assert report.net_detail.net == "I2S_DOUT"
    assert report.net_detail.segments == 15
    assert report.net_detail.total_length_mm == pytest.approx(64.1)


def test_signal_integrity_degraded_variant():
    report = get_adapter("analyze_pcb_signal_integrity").parse(
        samples.SIGNAL_INTEGRITY_DEGRADED
    )
    assert report.degraded
    assert report.diff_pairs[0].status == "Marginal"
    assert report.diff_pair_rule_width_mm is None


def test_signal_integrity_no_tracks_is_a_report_not_an_error():
    report = get_adapter("analyze_pcb_signal_integrity").parse(
        samples.SIGNAL_INTEGRITY_NO_TRACKS
    )
    assert report.note and "unrouted" in report.note
    report = get_adapter("analyze_pcb_signal_integrity").parse(
        samples.SIGNAL_INTEGRITY_NET_MISSING
    )
    assert "SPARE1" in (report.note or "")


def test_signal_integrity_missing_pcb():
    with pytest.raises(MissingArtifactError):
        get_adapter("analyze_pcb_signal_integrity").parse(
            "Error: [Errno 2] No such file or directory: 'C:/boards/missing.kicad_pcb'"
        )


def test_signal_integrity_garbage_raises():
    with pytest.raises(AdapterParseError):
        get_adapter("analyze_pcb_signal_integrity").parse("<html>nope</html>")


# --- find_tracks_by_net ------------------------------------------------------


def test_find_tracks_by_net_parsed():
    report = get_adapter("find_tracks_by_net").parse(samples.TRACKS_BY_NET)
    assert isinstance(report, NetTrackAnalysis)
    assert report.net == "VDD_3V3"
    assert report.found
    assert report.segment_count == 3
    assert report.via_count == 2
    assert report.zone_count == 1
    assert report.total_length_mm == pytest.approx(19.2)
    assert report.layers == ["B.Cu", "F.Cu"]
    assert report.widths_mm == [0.25, 0.5]
    assert report.mixed_widths
    assert len(report.segments) == 3
    seg = report.segments[0]
    assert (seg.start_x_mm, seg.start_y_mm) == (pytest.approx(12.7), pytest.approx(45.1))
    assert seg.width_mm == pytest.approx(0.25)
    assert seg.layer == "F.Cu"
    assert len(report.vias) == 2
    assert report.vias[0].span == "F.Cu -> B.Cu"
    assert report.vias[0].drill_mm == pytest.approx(0.3)
    assert report.zones[0].filled is True
    assert not report.truncated


def test_find_tracks_by_net_truncated_lists():
    report = get_adapter("find_tracks_by_net").parse(samples.TRACKS_BY_NET_TRUNCATED)
    assert report.truncated
    assert report.segment_count == 74  # header count, not table length
    assert len(report.segments) == 1  # ellipsis rows skipped
    assert len(report.vias) == 1
    assert not report.mixed_widths


def test_find_tracks_by_net_not_found_variants():
    report = get_adapter("find_tracks_by_net").parse(samples.TRACKS_BY_NET_NONE)
    assert not report.found
    assert report.net == "SPARE1"
    assert "No tracks routed" in report.summary()

    report = get_adapter("find_tracks_by_net").parse(samples.TRACKS_BY_NET_SUGGESTIONS)
    assert not report.found
    assert report.net == "VDD"
    assert report.suggestions == ["VDD_3V3", "VDD_1V8"]


def test_find_tracks_by_net_requires_net_name_arg():
    adapter = get_adapter("find_tracks_by_net")
    with pytest.raises(Exception):
        adapter.request_model(file_path="C:/b.kicad_pcb")  # net_name required


# --- trace_netlist_connection ------------------------------------------------


def test_trace_connection_single_pin_variant():
    trace = get_adapter("trace_netlist_connection").parse(samples.TRACE_CONNECTION_PIN)
    assert isinstance(trace, ConnectionTrace)
    assert trace.reference == "R5"
    assert len(trace.nets) == 1
    net = trace.nets[0]
    assert net.net == "VDD_3V3"
    assert net.pin == "1"
    assert [(p.reference, p.pin) for p in net.connected_to] == [("U1", "2"), ("C3", "1")]


def test_trace_connection_all_pins_variant():
    trace = get_adapter("trace_netlist_connection").parse(samples.TRACE_CONNECTION_ALL)
    assert trace.reference == "R5"
    nets = {n.net: n for n in trace.nets}
    assert set(nets) == {"VDD_3V3", "/ADC_IN"}
    assert nets["VDD_3V3"].pin == "1"
    assert len(nets["VDD_3V3"].connected_to) == 2
    assert nets["/ADC_IN"].connected_to == []
    assert "2 nets" in trace.summary()


def test_trace_connection_errors():
    with pytest.raises(ToolExecutionError):
        get_adapter("trace_netlist_connection").parse(samples.TRACE_CONNECTION_NOT_FOUND)
    with pytest.raises(MissingArtifactError):
        get_adapter("trace_netlist_connection").parse(samples.TRACE_FILE_NOT_FOUND)


# --- detect_pin_conflicts ----------------------------------------------------


def test_detect_pin_conflicts_parsed():
    report = get_adapter("detect_pin_conflicts").parse(samples.PIN_CONFLICTS)
    assert isinstance(report, PinConflictReport)
    assert not report.passed
    assert report.schematic_path == "C:/boards/demo/demo.kicad_sch"
    assert report.total_conflicts == 3
    assert [c.severity for c in report.conflicts] == ["error", "warning", "info"]
    assert report.conflicts[0].type == "multiple_outputs"
    assert report.conflicts[0].location == "I2S_DOUT"
    assert report.error_count == 1
    assert "3 pin conflicts" in report.summary()


def test_detect_pin_conflicts_clean():
    report = get_adapter("detect_pin_conflicts").parse(samples.PIN_CONFLICTS_NONE)
    assert report.passed
    assert report.conflicts == []


def test_detect_pin_conflicts_errors():
    with pytest.raises(MissingArtifactError):
        get_adapter("detect_pin_conflicts").parse(samples.PIN_CONFLICTS_NOT_FOUND)
    with pytest.raises(ToolExecutionError):
        get_adapter("detect_pin_conflicts").parse(samples.PIN_CONFLICTS_NETLIST_FAIL)


# --- validate_pin_configuration ----------------------------------------------


def test_validate_pin_configuration_passed():
    report = get_adapter("validate_pin_configuration").parse(samples.PIN_VALIDATION_OK)
    assert isinstance(report, PinValidationReport)
    assert report.passed
    assert report.mcu_found


def test_validate_pin_configuration_no_mcu_is_degraded_not_error():
    report = get_adapter("validate_pin_configuration").parse(samples.PIN_VALIDATION_NO_MCU)
    assert not report.passed
    assert not report.mcu_found
    assert not report.blocked_by_conflicts
    assert report.note


def test_validate_pin_configuration_blocked_carries_conflicts():
    report = get_adapter("validate_pin_configuration").parse(samples.PIN_VALIDATION_BLOCKED)
    assert not report.passed
    assert report.blocked_by_conflicts
    assert len(report.conflicts) == 1
    assert report.conflicts[0].severity == "error"


def test_validate_pin_configuration_missing_file():
    with pytest.raises(MissingArtifactError):
        get_adapter("validate_pin_configuration").parse(samples.PIN_VALIDATION_NOT_FOUND)


# --- analyze_pin_functions ----------------------------------------------------


def test_analyze_pin_functions_parsed():
    report = get_adapter("analyze_pin_functions").parse(samples.PIN_FUNCTIONS)
    assert isinstance(report, PinFunctionAnalysis)
    assert report.schematic_path == "C:/boards/demo/demo.kicad_sch"
    assert report.total_pins == 3
    assert len(report.pins) == 3
    p = report.pins[0]
    assert (p.component, p.pin_name, p.pin_number) == ("U1", "GPIO4", "24")
    assert p.pin_type == "bidirectional"
    assert p.nets == ["I2C1_SDA"]
    assert p.functions == ["I2C", "GPIO"]
    assert p.mcu_family == "esp32"
    # "(+N more)" marker is stripped from the nets cell
    assert report.pins[1].nets == ["I2C1_SCL", "GPIO_X"]
    assert report.pins[2].mcu_family is None


def test_analyze_pin_functions_empty_is_a_note():
    report = get_adapter("analyze_pin_functions").parse(samples.PIN_FUNCTIONS_EMPTY)
    assert report.total_pins == 0
    assert report.note


def test_analyze_pin_functions_component_missing_raises():
    with pytest.raises(ToolExecutionError) as exc_info:
        get_adapter("analyze_pin_functions").parse(samples.PIN_FUNCTIONS_COMPONENT_MISSING)
    assert not isinstance(exc_info.value, MissingArtifactError)


# --- firmware extraction ------------------------------------------------------


def test_extract_i2c_devices_parsed():
    report = get_adapter("extract_i2c_devices").parse(samples.I2C_DEVICES)
    assert isinstance(report, I2cDevices)
    assert report.total == 2
    devices = {d.component: d for d in report.devices}
    assert devices["U5"].address == "0x76"
    assert devices["U5"].compatible == "bosch,bme280"
    assert devices["U6"].address is None  # 'Unknown' normalized
    assert "U5@0x76" in report.summary()


def test_extract_i2c_devices_none_and_missing():
    report = get_adapter("extract_i2c_devices").parse(samples.I2C_DEVICES_NONE)
    assert report.total == 0
    assert report.note
    with pytest.raises(MissingArtifactError):
        get_adapter("extract_i2c_devices").parse(samples.I2C_DEVICES_NOT_FOUND)


def test_extract_spi_devices_parsed():
    report = get_adapter("extract_spi_devices").parse(samples.SPI_DEVICES)
    assert isinstance(report, SpiDevices)
    assert report.total == 1
    assert report.devices[0].component == "U7"
    assert report.devices[0].net == "SPI1_CS_FLASH"
    empty = get_adapter("extract_spi_devices").parse(samples.SPI_DEVICES_NONE)
    assert empty.total == 0 and empty.note


def test_extract_gpio_config_parsed():
    report = get_adapter("extract_gpio_config").parse(samples.GPIO_CONFIG)
    assert isinstance(report, GpioConfig)
    assert report.total == 2
    pin = report.pins[0]
    assert (pin.component, pin.pin_name, pin.pin_number) == ("U1", "IO2", "24")
    assert pin.net == "GPIO_LED"
    assert pin.soc == "ESP32-S3"
    empty = get_adapter("extract_gpio_config").parse(samples.GPIO_CONFIG_NONE)
    assert empty.total == 0 and empty.note


def test_generate_device_tree_inline_dts():
    result = get_adapter("generate_device_tree").parse(samples.DEVICE_TREE_OK)
    assert isinstance(result, DeviceTreeResult)
    assert result.target_soc == "esp32"
    assert result.output_path is None
    assert (result.gpio_pins, result.i2c_buses, result.spi_buses, result.uarts) == (4, 1, 0, 1)
    assert result.dts and "/dts-v1/;" in result.dts


def test_generate_device_tree_saved_to_file():
    result = get_adapter("generate_device_tree").parse(samples.DEVICE_TREE_SAVED)
    assert result.output_path == "C:/temp/demo.dts"
    assert result.dts is None  # saved variant does not inline the source


def test_generate_device_tree_unsupported_soc_raises():
    with pytest.raises(ToolExecutionError):
        get_adapter("generate_device_tree").parse(samples.DEVICE_TREE_UNSUPPORTED)


# --- listings -----------------------------------------------------------------


def test_list_pcb_footprints_parsed():
    report = get_adapter("list_pcb_footprints").parse(samples.PCB_FOOTPRINTS)
    assert isinstance(report, PcbFootprints)
    assert report.path == "C:/boards/demo/demo.kicad_pcb"
    assert report.total == 3
    fp = {f.reference: f for f in report.footprints}
    assert fp["U1"].library == "RF_Module"
    assert fp["U1"].pads == 41
    assert fp["R5"].x_mm == pytest.approx(12.7)
    assert fp["R5"].rotation_deg == pytest.approx(90.0)
    assert fp["C3"].layer == "B.Cu"


def test_list_pcb_footprints_text_parser_column_alias():
    report = get_adapter("list_pcb_footprints").parse(samples.PCB_FOOTPRINTS_TEXT)
    assert report.footprints[0].library == "ESP32-S3-WROOM-1"  # 'Footprint' column


def test_list_pcb_footprints_empty_is_a_note():
    report = get_adapter("list_pcb_footprints").parse(samples.PCB_FOOTPRINTS_NONE)
    assert report.total == 0
    assert report.note


def test_analyze_pcb_nets_parsed():
    report = get_adapter("analyze_pcb_nets").parse(samples.PCB_NETS)
    assert isinstance(report, PcbRoutingReport)
    assert not report.degraded
    assert report.board_width_mm == pytest.approx(100.0)
    assert report.board_height_mm == pytest.approx(80.0)
    assert report.copper_layers == 4
    assert report.track_segments == 512
    assert report.net_count == 58
    assert report.via_count == 96
    assert report.zone_count == 4
    assert report.track_width_distribution == {"0.250mm": 402, "0.500mm": 110}
    assert report.via_drill_distribution == {"0.300mm": 90, "0.400mm": 6}
    assert report.via_layer_spans == {"F.Cu -> B.Cu": 88, "F.Cu -> In1.Cu": 8}
    assert report.segments_by_layer == {"F.Cu": 300, "B.Cu": 212}
    assert [n.net for n in report.top_nets] == ["VDD_3V3", "GND"]
    assert report.top_nets[0].length_mm == pytest.approx(312.45)
    assert report.min_track_width_mm == pytest.approx(0.1)
    assert report.default_track_width_mm == pytest.approx(0.25)
    assert report.smallest_clearance_mm == pytest.approx(0.2)
    assert len(report.warnings) == 1


def test_analyze_pcb_nets_degraded_variant():
    report = get_adapter("analyze_pcb_nets").parse(samples.PCB_NETS_DEGRADED)
    assert report.degraded
    assert report.board_width_mm is None
    assert report.track_segments == 512
    assert report.via_count == 96
    assert report.zone_count == 4
    assert report.warnings == []  # the pcbnew banner is not a design warning


def test_list_schematic_components_parsed():
    report = get_adapter("list_schematic_components").parse(samples.SCHEMATIC_COMPONENTS)
    assert isinstance(report, SchematicComponents)
    assert report.total == 3
    comp = {c.reference: c for c in report.components}
    assert comp["R5"].value == "10k"
    assert comp["R5"].footprint == "Resistor_SMD:R_0603_1608Metric"
    assert comp["U1"].library == "ESP32-S3-WROOM-1"
    assert all(not c.dnp and c.in_bom for c in report.components)


def test_list_schematic_components_dnp_columns():
    report = get_adapter("list_schematic_components").parse(samples.SCHEMATIC_COMPONENTS_DNP)
    comp = {c.reference: c for c in report.components}
    assert not comp["R5"].dnp and comp["R5"].in_bom
    assert comp["R9"].dnp and not comp["R9"].in_bom
    assert comp["R9"].footprint is None  # '-' normalized
    assert "1 DNP" in report.summary()


def test_list_schematic_components_empty_is_a_note():
    report = get_adapter("list_schematic_components").parse(samples.SCHEMATIC_COMPONENTS_NONE)
    assert report.total == 0
    assert report.note


# --- run_tool flow with Day-2 tools ------------------------------------------


@pytest.mark.asyncio
async def test_run_tool_day2_default_samples_all_parse(fake_session, cache):
    """Every Day-2 tool round-trips through run_tool against its default
    sample: args validate, output parses, evidence is cached."""
    calls = {
        "analyze_pcb_signal_integrity": {"file_path": "C:/b.kicad_pcb"},
        "find_tracks_by_net": {"file_path": "C:/b.kicad_pcb", "net_name": "VDD_3V3"},
        "trace_netlist_connection": {"netlist_path": "C:/t/demo.xml", "reference": "R5"},
        "detect_pin_conflicts": {"schematic_path": "C:/b.kicad_sch"},
        "validate_pin_configuration": {"schematic_path": "C:/b.kicad_sch"},
        "analyze_pin_functions": {"schematic_path": "C:/b.kicad_sch"},
        "extract_i2c_devices": {"schematic_path": "C:/b.kicad_sch"},
        "extract_spi_devices": {"schematic_path": "C:/b.kicad_sch"},
        "extract_gpio_config": {"schematic_path": "C:/b.kicad_sch"},
        "generate_device_tree": {"schematic_path": "C:/b.kicad_sch"},
        "list_pcb_footprints": {"file_path": "C:/b.kicad_pcb"},
        "analyze_pcb_nets": {"file_path": "C:/b.kicad_pcb"},
        "list_schematic_components": {"file_path": "C:/b.kicad_sch"},
    }
    assert set(calls) == set(DAY2_TOOLS)
    for tool, args in calls.items():
        outcome = await run_tool(fake_session, cache, tool, args)
        assert outcome.evidence.summary == outcome.data.summary()
        assert not outcome.cached
    assert len(cache) == len(calls)


@pytest.mark.asyncio
async def test_run_tool_day2_rejects_bad_args(fake_session, cache):
    with pytest.raises(InvalidToolArgumentsError):
        await run_tool(fake_session, cache, "find_tracks_by_net", file_path="C:/b.kicad_pcb")
    with pytest.raises(InvalidToolArgumentsError):
        await run_tool(
            fake_session,
            cache,
            "generate_device_tree",
            schematic_path="C:/b.kicad_sch",
            soc="esp32",  # wrong parameter name (server expects target_soc)
        )
    assert fake_session.calls == []
