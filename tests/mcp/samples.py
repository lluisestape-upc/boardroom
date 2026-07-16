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

# ---------------------------------------------------------------------------
# Day-2 samples (formats verified against the kicad-mcp-server source:
# tools/pcb.py, tools/netlist.py, tools/pin_analysis.py, tools/device_tree.py,
# tools/schematic.py)
# ---------------------------------------------------------------------------

SIGNAL_INTEGRITY = """# Signal Integrity Analysis: C:/boards/demo/demo.kicad_pcb

**Diff Pair Design Rules:** width=0.2000 mm, gap=0.2000 mm

## Differential Pair Analysis
| Pair | Net P | Net N | Length P | Length N | Delta | Status |
|------|-------|-------|----------|----------|--------|---------|
| USB | USB_P | USB_N | 45.230 mm | 45.180 mm | 0.050 mm | OK |
| USB_C | USB_C_P | USB_C_N | 18.400 mm | 19.100 mm | 0.700 mm | ❌ Mismatch |

## RF Traces
| Net | Length | Widths | Segments |
|-----|--------|--------|----------|
| ANT_FEED | 12.300 mm | 0.350 mm | 4 |

## Longest Signal Nets (Top 15)
| Net | Length (mm) | Segments | Layers |
|-----|-------------|----------|--------|
| /ADC_IN | 88.20 | 22 | F.Cu, B.Cu |
| I2S_DOUT | 64.10 | 15 | F.Cu |

## Nets with Most Vias (Layer Transitions)
| Net | Via Count |
|-----|-----------|
| GND | 44 |
| VDD_3V3 | 12 |
"""

SIGNAL_INTEGRITY_NET_DETAIL = """# Signal Integrity Analysis: C:/boards/demo/demo.kicad_pcb

**Diff Pair Design Rules:** width=0.2000 mm, gap=0.2000 mm

## Net: I2S_DOUT
**Segments:** 15, **Total Length:** 64.100 mm"""

SIGNAL_INTEGRITY_DEGRADED = """# Signal Integrity Analysis: C:/boards/demo/demo.kicad_pcb

⚠️ pcbnew not available — text-based analysis (limited)

## Differential Pair Analysis
| Pair | Net P | Net N | Length P | Length N | Delta | Status |
|------|-------|-------|----------|----------|--------|---------|
| USB | USB_P | USB_N | 45.230 mm | 44.800 mm | 0.430 mm | ⚠️ Marginal |

## Longest Signal Nets (Top 15)
| Net | Length (mm) | Segments | Layers |
|-----|-------------|----------|--------|
| /ADC_IN | 88.20 | 22 | F.Cu |
"""

SIGNAL_INTEGRITY_NO_TRACKS = "No tracks found in PCB file."

SIGNAL_INTEGRITY_NET_MISSING = "No tracks found for net 'SPARE1'."

TRACKS_BY_NET = """# Track Analysis: VDD_3V3

**Track Segments:** 3
**Vias:** 2
**Copper Zones:** 1
**Total Track Length:** 19.200 mm
**Layers Used:** B.Cu, F.Cu
**Track Widths:** 0.2500, 0.5000 mm
⚠️ Mixed track widths detected — may indicate manual routing or design rule override.

## Track Segments
| # | Start | End | Width | Layer | Length |
|---|-------|-----|-------|-------|--------|
| 1 | (12.70, 45.10) | (18.20, 45.10) | 0.2500 | F.Cu | 5.500 |
| 2 | (18.20, 45.10) | (18.20, 52.00) | 0.5000 | F.Cu | 6.900 |
| 3 | (18.20, 52.00) | (25.00, 52.00) | 0.5000 | B.Cu | 6.800 |

## Vias
| # | Position | Size | Drill | Span |
|---|----------|------|-------|------|
| 1 | (18.20, 45.10) | 0.600 | 0.300 | F.Cu -> B.Cu |
| 2 | (18.20, 52.00) | 0.600 | 0.300 | F.Cu -> B.Cu |

## Copper Zones
| Net | Layer | Filled |
|-----|-------|--------|
| VDD_3V3 | In1.Cu | Yes |
"""

TRACKS_BY_NET_TRUNCATED = """# Track Analysis: GND

**Track Segments:** 74
**Vias:** 44
**Copper Zones:** 0
**Total Track Length:** 288.100 mm
**Layers Used:** B.Cu
**Track Widths:** 0.2500 mm

## Track Segments
| # | Start | End | Width | Layer | Length |
|---|-------|-----|-------|-------|--------|
| 1 | (5.00, 5.00) | (9.00, 5.00) | 0.2500 | B.Cu | 4.000 |
| ... | (24 more segments) | | | | |

## Vias
| # | Position | Size | Drill | Span |
|---|----------|------|-------|------|
| 1 | (9.00, 5.00) | 0.600 | 0.300 | F.Cu -> B.Cu |
| ... | (24 more vias) | | | |
"""

TRACKS_BY_NET_SUGGESTIONS = """# Tracks for 'VDD'

Exact match not found. Did you mean one of these?
- `VDD_3V3` (87 segments)
- `VDD_1V8` (14 segments)"""

TRACKS_BY_NET_NONE = "No tracks or vias found for net 'SPARE1'."

TRACE_CONNECTION_PIN = """## Netlist Connection Trace: R5

**Pin:** 1
**Net:** VDD_3V3

### Connected Components:

| Reference | Pin |
|-----------|-----|
| U1 | 2 |
| C3 | 1 |"""

TRACE_CONNECTION_ALL = """## Netlist Connection Trace: R5

**Total Nets:** 2

### Net: VDD_3V3
**Pin:** 1

| Reference | Pin |
|-----------|-----|
| U1 | 2 |
| C3 | 1 |

### Net: /ADC_IN
**Pin:** 2

No other components on this net.
"""

TRACE_CONNECTION_NOT_FOUND = "❌ Component 'R99' not found in netlist"

TRACE_FILE_NOT_FOUND = (
    "❌ File not found: [Errno 2] No such file or directory: 'C:/temp/missing.xml'"
)

PIN_CONFLICTS = """❌ **Pin Conflicts Detected**

**Schematic:** C:/boards/demo/demo.kicad_sch
**Total Conflicts:** 3

## Conflicts

| Severity | Type | Location | Description |
|----------|------|----------|-------------|
| ❌ error | multiple_outputs | I2S_DOUT | Multiple outputs on same net: U1:5, U3:2 |
| ⚠️ warning | single_pin_net | /TP1 | Net '/TP1' has only one pin: TP1:1 |
| ⚠️ info | unconnected_pin | unconnected-(U1-Pad9) | U1 pin 9 is unconnected (unconnected-(U1-Pad9)) |

## Recommendations

1. **Fix all errors** before proceeding to PCB layout
2. Review warnings - some may be acceptable design choices
"""

PIN_CONFLICTS_NONE = """✅ **No Pin Conflicts Detected**

**Schematic:** C:/boards/demo/demo.kicad_sch

The schematic has been analyzed and no pin conflicts were found.

**Checked:**
- ✅ No multiple outputs on same net
- ✅ No power-to-power connections
- ✅ No unconnected input pins
- ✅ No pin type mismatches"""

PIN_CONFLICTS_NOT_FOUND = "❌ **Schematic file not found:** C:/boards/missing.kicad_sch"

PIN_CONFLICTS_NETLIST_FAIL = "❌ **Failed to generate netlist for conflict detection**"

PIN_VALIDATION_OK = """OK **Pin Configuration Validation Passed**

**Schematic:** C:/boards/demo/demo.kicad_sch

The schematic is ready for device tree generation.

## Validation Results

- OK No pin conflicts detected
- OK MCU component found
- OK Net connections valid
- OK Pin assignments compatible"""

PIN_VALIDATION_NO_MCU = """WARN **No MCU Component Found**

**Schematic:** C:/boards/demo/demo.kicad_sch

Device tree generation requires an MCU component in the schematic.

**Supported MCU families:**
- STM32 (STM32F, STM32H, STM32L series)
- ESP32 (ESP32, ESP32-S2, ESP32-S3, etc.)"""

PIN_VALIDATION_BLOCKED = """X **Pin Configuration Validation Failed**

The schematic has pin conflicts that must be resolved before
device tree generation.

❌ **Pin Conflicts Detected**

**Schematic:** C:/boards/demo/demo.kicad_sch
**Total Conflicts:** 1

## Conflicts

| Severity | Type | Location | Description |
|----------|------|----------|-------------|
| ❌ error | multiple_outputs | I2S_DOUT | Multiple outputs on same net: U1:5, U3:2 |

## Device Tree Generation Blocked

Pin conflicts prevent reliable device tree generation. Please
resolve all conflicts before attempting device tree generation."""

PIN_VALIDATION_NOT_FOUND = "X **Schematic file not found:** C:/boards/missing.kicad_sch"

PIN_FUNCTIONS = """# Pin Function Analysis

**Schematic:** C:/boards/demo/demo.kicad_sch

**Total Pins Analyzed:** 3

## Pin Details

| Component | Pin | Type | Nets | Inferred Functions | MCU Family |
|-----------|-----|------|------|-------------------|------------|
| U1 | GPIO4 (24) | bidirectional | I2C1_SDA | I2C, GPIO | esp32 |
| U1 | GPIO5 (25) | bidirectional | I2C1_SCL, GPIO_X (+2 more) | I2C, GPIO | esp32 |
| U5 | SDA (3) | input | I2C1_SDA | I2C | N/A |

## MCU Pin Details

**U1 - GPIO4 (24)**
- Primary Function: GPIO
- Alternate Functions: GPIO, ADC, DAC, I2C, SPI, UART, TOUCH
- Max Current: 40.0 mA
- 5V Tolerant: No
"""

PIN_FUNCTIONS_EMPTY = """⚠️ **No Pin Analysis Available**

**Schematic:** C:/boards/demo/demo.kicad_sch

Unable to extract pin information. This could be due to:
- No components found in schematic
- Missing symbol definitions
- Netlist not available

**Next Steps:**
1. Ensure schematic has components with pins
2. Generate netlist first: `generate_netlist()`
3. Verify schematic file is valid KiCad 9.0+ format"""

PIN_FUNCTIONS_COMPONENT_MISSING = "❌ **Component not found:** U99"

I2C_DEVICES = """# I2C Device Extraction

**Schematic:** C:/boards/demo/demo.kicad_sch
**Total I2C Devices:** 2

## I2C Device Details

| Component | Device | Compatible | Address | Net |
|-----------|--------|------------|---------|-----|
| U5 | BME280 | bosch,bme280 | 0x76 | I2C1_SDA_0x76 |
| U6 | SSD1306 | solomon,ssd1306fb-i2c | Unknown | I2C1_SDA |

## Device Tree Configuration

```dts
&i2c1 {
    status = "okay";

    u5: bosch,bme280@0x76 {
        compatible = "bosch,bme280";
        reg = <0x76>;
    };

};
```"""

I2C_DEVICES_NONE = """WARN **No I2C Devices Found**

**Schematic:** C:/boards/demo/demo.kicad_sch

No I2C devices were found in the schematic.

**Next Steps:**
1. Ensure schematic has I2C peripherals
2. Check net names contain 'I2C' or 'TWI'
3. Include I2C addresses in net names (e.g., I2C_SDA_0x76)"""

I2C_DEVICES_NOT_FOUND = "X **Schematic file not found:** C:/boards/missing.kicad_sch"

SPI_DEVICES = """# SPI Device Extraction

**Schematic:** C:/boards/demo/demo.kicad_sch
**Total SPI Devices:** 1

## SPI Device Details

| Component | Device | Compatible | Net |
|-----------|--------|------------|-----|
| U7 | W25Q128JV | winbond,w25q128 | SPI1_CS_FLASH |

## Device Tree Configuration

```dts
&spi1 {
    status = "okay";

    u7: winbond,w25q128@0 {
        compatible = "winbond,w25q128";
        reg = <0>;
        spi-max-frequency = <1000000>;
    };

};
```"""

SPI_DEVICES_NONE = """WARN **No SPI Devices Found**

**Schematic:** C:/boards/demo/demo.kicad_sch

No SPI devices were found in the schematic.

**Next Steps:**
1. Ensure schematic has SPI peripherals
2. Check net names contain 'SPI'
3. Include CS signals in net naming"""

GPIO_CONFIG = """# GPIO Configuration Extraction

**Schematic:** C:/boards/demo/demo.kicad_sch

**Total GPIO Pins:** 2

## GPIO Pin Details

| Component | Pin | Net | SOC |
|-----------|-----|-----|-----|
| U1 | IO2 (24) | GPIO_LED | ESP32-S3 |
| U1 | IO4 (26) | GPIO_BTN | ESP32-S3 |

## Code Generation Suggestions

### ESP32-S3

```c
// GPIO configuration for ESP32-S3

// IO2 (24): GPIO_LED
gpio_set_direction(GPIO24, GPIO_MODE_OUTPUT);

// IO4 (26): GPIO_BTN
gpio_set_direction(GPIO26, GPIO_MODE_OUTPUT);

```

"""

GPIO_CONFIG_NONE = """WARN **No GPIO Configurations Found**

**Schematic:** C:/boards/demo/demo.kicad_sch


No GPIO configurations were found in the schematic.

**Next Steps:**
1. Ensure schematic has MCU components
2. Check net names contain 'GPIO' or 'IO'
3. Try without SOC family filter"""

DEVICE_TREE_OK = """OK **Device Tree Generated Successfully**

**Schematic:** C:/boards/demo/demo.kicad_sch
**Target SOC:** esp32

## Device Tree Contents

- **GPIO Pins:** 4
- **I2C Buses:** 1
- **SPI Buses:** 0
- **UARTs:** 1

## Generated Device Tree

```dts
/dts-v1/;

/ {
    model = "demo";
};
```

## Next Steps

1. Review and customize the generated device tree
2. Save to file: `demo.dts`
3. Compile with device tree compiler: `dtc -I dts -O dtb -o output.dtb`
4. Test on target hardware"""

DEVICE_TREE_SAVED = """OK **Device Tree Generated Successfully**

**Schematic:** C:/boards/demo/demo.kicad_sch
**Target SOC:** stm32f4
**Output:** C:/temp/demo.dts

## Device Tree Contents

- **GPIO Pins:** 4
- **I2C Buses:** 1
- **SPI Buses:** 0
- **UARTs:** 1

The device tree source file has been generated and saved to the specified location.

## Next Steps

1. Review and customize the generated device tree
2. Compile with device tree compiler: `dtc -I dts -O dtb -o output.dtb C:/temp/demo.dts`
3. Test on target hardware
4. Iterate as needed"""

DEVICE_TREE_UNSUPPORTED = """X **Unsupported SOC Family**

**Requested:** pic32
**Supported:** stm32f4, esp32, nrf52

Please specify a supported SOC family."""

PCB_FOOTPRINTS = """# Footprints in C:/boards/demo/demo.kicad_pcb
Total: 3 footprint(s)

| Reference | Value | Library | Layer | Position | Rotation | Pads |
|-----------|-------|---------|-------|----------|----------|------|
| U1 | ESP32-S3-WROOM-1 | RF_Module | F.Cu | (50.00, 40.00) | 0.0° | 41 |
| R5 | 10k | Resistor_SMD | F.Cu | (12.70, 45.10) | 90.0° | 2 |
| C3 | 100nF | Capacitor_SMD | B.Cu | (48.00, 41.50) | 180.0° | 2 |"""

# Text-parser fallback variant: column 3 is "Footprint" instead of "Library".
PCB_FOOTPRINTS_TEXT = """# Footprints in C:/boards/demo/demo.kicad_pcb
Total: 1 footprint(s)

| Reference | Value | Footprint | Layer | Position | Rotation | Pads |
|-----------|-------|-----------|-------|----------|----------|------|
| U1 | ESP32-S3-WROOM-1 | ESP32-S3-WROOM-1 | F.Cu | (50.00, 40.00) | 0.0° | 41 |"""

PCB_FOOTPRINTS_NONE = "No footprints found."

PCB_NETS = """# PCB Routing Analysis: C:/boards/demo/demo.kicad_pcb

## Overview
**Board:** 100.00 x 80.00 mm, 4 copper layers
**Tracks:** 512 segments across 58 nets
**Vias:** 96
**Zones:** 4 copper zones

## Track Width Distribution
| Width | Count |
|-------|-------|
| 0.250mm | 402x |
| 0.500mm | 110x |

## Via Drill Distribution
**Total vias:** 96

| Drill Size | Count |
|------------|-------|
| 0.300mm | 90x |
| 0.400mm | 6x |

### Via Layer Spans
- F.Cu -> B.Cu: 88x
- F.Cu -> In1.Cu: 8x

## Track Segments by Layer
| Layer | Segments |
|-------|----------|
| F.Cu | 300 |
| B.Cu | 212 |

## Top 20 Nets by Track Length
| Net | Length (mm) | Segments | Widths | Layers |
|-----|-------------|----------|--------|--------|
| VDD_3V3 | 312.45 | 87 | 0.250, 0.500 | F.Cu, B.Cu |
| GND | 288.10 | 74 | 0.250 | B.Cu |

## Design Rule Comparison
**Min track width in design:** 0.1000 mm
**Default track width (design rules):** 0.2500 mm
**Smallest clearance:** 0.2000 mm
⚠️ Some tracks are significantly narrower than the default (0.1000 vs 0.2500 mm)"""

PCB_NETS_DEGRADED = """# PCB Routing Analysis: C:/boards/demo/demo.kicad_pcb

⚠️ pcbnew not available — text-based analysis (limited precision)

## Overview
**Track Segments:** 512
**Vias:** 96
**Copper Zones:** 4

## Track Width Distribution
| Width | Count |
|-------|-------|
| 0.250mm | 402x |

## Top 20 Nets by Track Length
| Net | Length (mm) | Segments | Widths | Layers |
|-----|-------------|----------|--------|--------|
| VDD_3V3 | 312.45 | 87 | 0.250 | F.Cu |"""

SCHEMATIC_COMPONENTS = """# Components in C:/boards/demo/demo.kicad_sch
Total: 3 component(s)

| Reference | Value | Footprint | Library |
|-----------|-------|-----------|---------|
| C3 | 100nF | Capacitor_SMD:C_0603_1608Metric | C |
| R5 | 10k | Resistor_SMD:R_0603_1608Metric | R |
| U1 | ESP32-S3-WROOM-1 | RF_Module:ESP32-S3-WROOM-1 | ESP32-S3-WROOM-1 |"""

# When any DNP / not-in-BOM flag exists, two extra columns appear (blank for
# components with default flags).
SCHEMATIC_COMPONENTS_DNP = """# Components in C:/boards/demo/demo.kicad_sch
Total: 2 component(s)

| Reference | Value | Footprint | Library | DNP | In BOM |
|-----------|-------|-----------|---------|-----|--------|
| R5 | 10k | Resistor_SMD:R_0603_1608Metric | R |  |  |
| R9 | 0R | - | R | Yes | No |"""

SCHEMATIC_COMPONENTS_NONE = "No components found matching the specified criteria."

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
    "analyze_pcb_signal_integrity": SIGNAL_INTEGRITY,
    "find_tracks_by_net": TRACKS_BY_NET,
    "trace_netlist_connection": TRACE_CONNECTION_ALL,
    "detect_pin_conflicts": PIN_CONFLICTS,
    "validate_pin_configuration": PIN_VALIDATION_OK,
    "analyze_pin_functions": PIN_FUNCTIONS,
    "extract_i2c_devices": I2C_DEVICES,
    "extract_spi_devices": SPI_DEVICES,
    "extract_gpio_config": GPIO_CONFIG,
    "generate_device_tree": DEVICE_TREE_OK,
    "list_pcb_footprints": PCB_FOOTPRINTS,
    "analyze_pcb_nets": PCB_NETS,
    "list_schematic_components": SCHEMATIC_COMPONENTS,
}
