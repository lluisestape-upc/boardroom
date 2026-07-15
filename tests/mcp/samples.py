"""Sample kicad-mcp-server outputs, mirroring the real server's markdown
formats (verified against the Seeed-Studio kicad-mcp-server source)."""

ERC_VIOLATIONS = """❌ **ERC Violations Detected**

**Schematic:** C:/boards/demo/demo.kicad_sch
**Total Violations:** 3
- Errors: 2
- Warnings: 1

## Violations

| Severity | Type | Description | Components |
|----------|------|-------------|------------|
| ❌ error | pin_not_connected | Input pin not connected | U3 |
| ❌ error | power_pin_not_driven | Power input pin not driven by output | U1, C12 |
| ⚠️ warning | unconnected_wire | Wire end dangling | N/A |

## Recommendations

1. **Fix all errors** before proceeding to PCB layout
"""

ERC_PASSED = """✅ **ERC Check Passed**

**Schematic:** C:/boards/demo/demo.kicad_sch

No electrical violations detected!
"""

ERC_CHECK_FAILED = """❌ **ERC Check Failed**

**Schematic:** C:/boards/demo/demo.kicad_sch

**Error:**
```
kicad-cli: command not found
```
"""

ERC_FILE_NOT_FOUND = "❌ **Schematic file not found:** C:/boards/missing.kicad_sch"

GET_ERC_VIOLATIONS = """# ERC Violations

**Schematic:** C:/boards/demo/demo.kicad_sch
**Filter:** severity = 'error'
**Count:** 2

## Violations

| Severity | Type | Description | Components |
|----------|------|-------------|------------|
| ❌ error | pin_not_connected | Input pin not connected | U3 |
| ❌ error | power_pin_not_driven | Power input pin not driven by output | U1, C12 |
"""

DRC_VIOLATIONS = """❌ **DRC Violations Detected**

**PCB:** C:/boards/demo/demo.kicad_pcb
**Total Violations:** 2
- Errors: 1
- Warnings: 1

## Violations

| Severity | Type | Location | Description |
|----------|------|----------|-------------|
| ❌ error | clearance | (12.70, 45.10) | Clearance violation between track and pad |
| ⚠️ warning | silk_over_copper | (3.05, 8.90) | Silkscreen over exposed copper |

## Violation Summary

- **clearance**: 1 violations
- **silk_over_copper**: 1 violations
"""

DRC_PASSED = """✅ **DRC Check Passed**

**PCB:** C:/boards/demo/demo.kicad_pcb

No design rule violations detected!
"""

DRC_FILE_NOT_FOUND = "❌ **PCB file not found:** C:/boards/missing.kicad_pcb"

NETLIST_OK = """✅ Netlist generated successfully

**Output:** C:/temp/demo.xml

You can now use netlist-based tools:
- `trace_netlist_connection()` - Trace component connections via netlist
"""

NETLIST_CLI_MISSING = """⚠️ kicad-cli not found in PATH.

Please:
1. Install KiCad 7+ (https://www.kicad.org/)
"""

NETLIST_COMPONENTS = """## Components from Netlist: C:/temp/demo.xml

**Total Components:** 2

### R5
**Value:** 10k
**Library:** Device
**Footprint:** Resistor_SMD:R_0603_1608Metric

**Pin Connections:**

| Pin | Net |
|-----|-----|
| 1 | VDD_3V3 |
| 2 | /ADC_IN |

### U1
**Value:** ESP32-S3
**Library:** RF_Module

| Pin | Net |
|-----|-----|
| 1 | GND |
| 2 | VDD_3V3 |
"""

NETLIST_NETS = """## Nets from Netlist: C:/temp/demo.xml

**Total Nets:** 2

### GND
**Code:** 1
**Connections:** 3 pins

| Reference | Pin |
|-----------|-----|
| U1 | 1 |
| C3 | 2 |
| C4 | 2 |

### VDD_3V3
**Code:** 2
**Connections:** 12 pins

| Reference | Pin |
|-----------|-----|
| U1 | 2 |
| R5 | 1 |
| ... | (10 more) |
"""

POWER_DOMAINS = """# Power Domain Extraction

**Schematic:** C:/boards/demo/demo.kicad_sch
**Total Power Components:** 2

## Power Components

| Reference | Component | Type |
|-----------|-----------|------|
| U2 | AMS1117-LDO-3.3 | LDO Regulator |
| U4 | TPS5430 | Buck Converter |

## Device Tree Configuration

```dts
/ {
    regulators {
    };
};
```
"""

POWER_DOMAINS_NONE = """WARN **No Power Components Found**

**Schematic:** C:/boards/demo/demo.kicad_sch

No power management components were found in the schematic.
"""

POWER_DOMAINS_NOT_FOUND = "X **Schematic file not found:** C:/boards/missing.kicad_sch"

POWER_INTEGRITY = """# Power Integrity Analysis: C:/boards/demo/demo.kicad_pcb

**Board:** 4 layers, 1.600 mm thick

## Power Copper Zones
| Net | Zones | Layers |
|-----|-------|--------|
| VDD_3V3 | 2 | In1.Cu (filled), F.Cu (filled) |

## GND Copper Zones
| Net | Zones | Layers |
|-----|-------|--------|
| GND | 2 | In2.Cu (filled), B.Cu (filled) |

**GND Coverage:** 2 zones across 2 layers (2 filled)
⚠️ GND zones only on 2 of 4 copper layers. Consider adding GND pour on inner layers for better EMI performance.

## Power Net Track Routing
| Net | Length (mm) | Segments | Min Width | Max Width |
|-----|-------------|----------|-----------|-----------|
| VDD_3V3 | 312.45 | 87 | 0.2500 mm | 0.5000 mm |
| 5V | 88.10 | 14 | 0.5000 mm | 0.5000 mm |
"""

POWER_INTEGRITY_DEGRADED = """# Power Integrity Analysis: C:/boards/demo/demo.kicad_pcb

⚠️ pcbnew not available — text-based analysis (limited)

## Power Copper Zones
| Net | Layer |
|-----|-------|
| VDD_3V3 | F.Cu |

## GND Copper Zones
| Net | Layer |
|-----|-------|
| GND | B.Cu |

**GND Coverage:** 1 zones across 1 layers
"""

SCHEMATIC_INFO = """# Schematic Information: C:/boards/demo/demo.kicad_sch

## Project Information
**Title:** Cyberdeck Audio Board
**Company:** Lluís Estapé
**Date:** 2026-06-10
**Revision:** B

## Statistics
**Total Components:** 42
**Total Nets:** 58
**Hierarchical Sheets:** 2

## Components by Type
- C: 18
- R: 12
- U: 6

## Hierarchical Sheets
- audio: audio.kicad_sch
- power: power.kicad_sch
"""

PCB_STATISTICS = """# PCB Statistics: C:/boards/demo/demo.kicad_pcb

## Board Information
**Dimensions:** 100.00 x 80.00 mm
**Copper Layers:** 4
**Board Thickness:** 1.600 mm

## Elements
**Footprints:** 42
**Track Segments:** 512
**Vias:** 96
**Copper Zones:** 4
**Nets:** 58

## Design Rules
**Smallest Clearance:** 0.2000 mm
**Default Track Width:** 0.2500 mm
**Default Via Size/Drill:** 0.6000 / 0.3000 mm
**Diff Pair Width/Gap:** 0.2000 / 0.2000 mm
"""

PCB_STATS_ERROR = "Error parsing PCB: unbalanced s-expression"

SCHEMATIC_INFO_NOT_FOUND = "Error: [Errno 2] No such file or directory: 'C:/boards/missing.kicad_sch'"

#: tool name -> default happy-path sample (used by the fake session fixture)
DEFAULT_RESPONSES = {
    "run_erc": ERC_VIOLATIONS,
    "get_erc_violations": GET_ERC_VIOLATIONS,
    "run_drc": DRC_VIOLATIONS,
    "get_drc_violations": DRC_VIOLATIONS,
    "generate_netlist": NETLIST_OK,
    "get_netlist_components": NETLIST_COMPONENTS,
    "get_netlist_nets": NETLIST_NETS,
    "extract_power_domains": POWER_DOMAINS,
    "analyze_pcb_power_integrity": POWER_INTEGRITY,
    "get_schematic_info": SCHEMATIC_INFO,
    "get_pcb_statistics": PCB_STATISTICS,
}
