window.BOARDROOM_SAMPLE_REVIEW = {
  "session_id": "session-20260715-e3d8",
  "project_name": "Antigravity Power Controller (v1.2)",
  "findings": [
    {
      "id": "PI-001",
      "agent": "power_integrity",
      "claim": "VCC_3V3 rail shows excessive voltage drop under transient load.",
      "severity": "critical",
      "evidence": [
        {
          "evidence_id": "EV-PI-001A",
          "tool": "run_transient_sim",
          "summary": "Simulated drop to 2.85V (13.6% droop) during 500mA load step on U1."
        }
      ],
      "affected_nets": ["VCC_3V3"],
      "affected_components": ["U1", "C12", "C13"],
      "board_region": {
        "x": 120,
        "y": 145,
        "w": 65,
        "h": 50,
        "image": "board.png"
      },
      "recommendation": "Increase local decoupling capacitance near U1 by replacing C12 and C13 with 10uF ceramic capacitors.",
      "status": "upheld"
    },
    {
      "id": "SI-001",
      "agent": "signal_integrity",
      "claim": "SPI_CLK line has excessive ringing due to trace impedance mismatch.",
      "severity": "major",
      "evidence": [
        {
          "evidence_id": "EV-SI-001A",
          "tool": "calculate_impedance",
          "summary": "Calculated trace impedance of SPI_CLK is 72 ohms; driver output impedance is 24 ohms."
        }
      ],
      "affected_nets": ["SPI_CLK"],
      "affected_components": ["U1", "U2", "R1"],
      "board_region": {
        "x": 210,
        "y": 95,
        "w": 180,
        "h": 40,
        "image": "board.png"
      },
      "recommendation": "Place a 33-ohm series termination resistor near driver U1 pin 12.",
      "status": "merged",
      "conflicts_with": ["DFM-001"],
      "debate": [
        {
          "round": 1,
          "agent": "signal_integrity",
          "position": "A series termination resistor is critical to match the driver source impedance (24 ohms) to the line and prevent reflection-induced clock double-triggering.",
          "new_evidence_id": null
        },
        {
          "round": 1,
          "agent": "dfm_layout",
          "position": "Adding a series resistor near U1 pin 12 increases component density and creates clearance issues with adjacent high-density escape routing.",
          "new_evidence_id": null
        },
        {
          "round": 2,
          "agent": "signal_integrity",
          "position": "We can shift the resistor (R1) 1.5mm further out from the pin without significantly degrading the termination effectiveness, resolving density issues.",
          "new_evidence_id": "EV-SI-001B"
        },
        {
          "round": 2,
          "agent": "dfm_layout",
          "position": "If the resistor is shifted 1.5mm away, we can route it on the outer layer, which is manufacturable if we widen the trace to reduce intrinsic impedance.",
          "new_evidence_id": "EV-DFM-001B"
        }
      ],
      "ruling": {
        "decision": "merged",
        "rationale": "The Moderator merges the constraints: shift the series resistor (R1) 1.5mm from U1 pin 12 (satisfying SI termination requirements) and widen the SPI_CLK trace to 0.22mm (satisfying DFM impedance & spacing constraints).",
        "cited_evidence_ids": ["EV-SI-001B", "EV-DFM-001B"]
      }
    },
    {
      "id": "DFM-001",
      "agent": "dfm_layout",
      "claim": "Trace width on SPI_CLK is too thin for 50-ohm impedance match.",
      "severity": "major",
      "evidence": [
        {
          "evidence_id": "EV-DFM-001A",
          "tool": "check_clearance",
          "summary": "Current trace width of 0.15mm results in 72-ohm characteristic impedance on 1.6mm 4-layer stackup."
        }
      ],
      "affected_nets": ["SPI_CLK"],
      "affected_components": ["U1", "U2"],
      "recommendation": "Increase trace width of SPI_CLK to 0.25mm on Top Layer.",
      "status": "merged",
      "conflicts_with": ["SI-001"],
      "debate": [
        {
          "round": 1,
          "agent": "signal_integrity",
          "position": "A series termination resistor is critical to match the driver source impedance (24 ohms) to the line and prevent reflection-induced clock double-triggering.",
          "new_evidence_id": null
        },
        {
          "round": 1,
          "agent": "dfm_layout",
          "position": "Adding a series resistor near U1 pin 12 increases component density and creates clearance issues with adjacent high-density escape routing.",
          "new_evidence_id": null
        },
        {
          "round": 2,
          "agent": "signal_integrity",
          "position": "We can shift the resistor (R1) 1.5mm further out from the pin without significantly degrading the termination effectiveness, resolving density issues.",
          "new_evidence_id": "EV-SI-001B"
        },
        {
          "round": 2,
          "agent": "dfm_layout",
          "position": "If the resistor is shifted 1.5mm away, we can route it on the outer layer, which is manufacturable if we widen the trace to reduce intrinsic impedance.",
          "new_evidence_id": "EV-DFM-001B"
        }
      ],
      "ruling": {
        "decision": "merged",
        "rationale": "The Moderator merges the constraints: shift the series resistor (R1) 1.5mm from U1 pin 12 (satisfying SI termination requirements) and widen the SPI_CLK trace to 0.22mm (satisfying DFM impedance & spacing constraints).",
        "cited_evidence_ids": ["EV-SI-001B", "EV-DFM-001B"]
      }
    },
    {
      "id": "ERC-001",
      "agent": "connectivity_erc",
      "claim": "Unconnected input pin detected on microcontroller U1 pin 5.",
      "severity": "major",
      "evidence": [
        {
          "evidence_id": "EV-ERC-001A",
          "tool": "run_erc",
          "summary": "Pin 5 (GPIO_1/INT) is configured as input but has no driving source or pull resistor."
        }
      ],
      "affected_nets": ["MCU_GPIO1"],
      "affected_components": ["U1"],
      "recommendation": "Add a 10k pull-down resistor to net MCU_GPIO1, or configure internal pull-down in firmware.",
      "status": "upheld"
    },
    {
      "id": "FW-001",
      "agent": "firmware_bringup",
      "claim": "MCU pin 5 is configured as active-high interrupt but lacks hardware pull-down.",
      "severity": "minor",
      "evidence": [
        {
          "evidence_id": "EV-FW-001A",
          "tool": "inspect_dts",
          "summary": "Device tree node gpios-interrupt sets pin 5 as high-level triggered with pull-up disabled."
        }
      ],
      "affected_nets": ["MCU_GPIO1"],
      "affected_components": ["U1"],
      "recommendation": "Enable internal pull-down resistor in MCU initialization code, or route to ground.",
      "status": "upheld"
    },
    {
      "id": "PI-002",
      "agent": "power_integrity",
      "claim": "LDO regulator U3 thermal dissipation is excessive under max load.",
      "severity": "critical",
      "evidence": [
        {
          "evidence_id": "EV-PI-002A",
          "tool": "calculate_thermal",
          "summary": "U3 drops 5V to 1.8V at 400mA. Dissipation is 1.28W; junction temp exceeds 135C on SOT-23 package."
        }
      ],
      "affected_nets": ["VCC_5V", "VCC_1V8"],
      "affected_components": ["U3"],
      "recommendation": "Add a copper pour area of at least 150 mm^2 connected to the GND pin of U3 for thermal relief.",
      "status": "upheld"
    },
    {
      "id": "DFM-002",
      "agent": "dfm_layout",
      "claim": "Thermal relief on U3 GND pin is missing, which could cause manufacturing defects.",
      "severity": "minor",
      "evidence": [
        {
          "evidence_id": "EV-DFM-002A",
          "tool": "verify_thermal_relief",
          "summary": "U3 pad 2 is directly connected to the solid ground plane without thermal spokes."
        }
      ],
      "affected_nets": ["GND"],
      "affected_components": ["U3"],
      "recommendation": "Use standard 4-spoke thermal relief for U3 pad 2 connection to GND plane.",
      "status": "upheld"
    },
    {
      "id": "ERC-002",
      "agent": "connectivity_erc",
      "claim": "Power net VCC_5V is shorted to GND through misplaced copper island near C10.",
      "severity": "critical",
      "evidence": [
        {
          "evidence_id": "EV-ERC-002A",
          "tool": "run_drc",
          "summary": "Clearence error #42: Copper fill zone overlaps with VCC_5V via pads near C10."
        }
      ],
      "affected_nets": ["VCC_5V", "GND"],
      "affected_components": ["C10"],
      "board_region": {
        "x": 420,
        "y": 280,
        "w": 90,
        "h": 90,
        "image": "board.png"
      },
      "recommendation": "Remove the redundant copper zone connection on the bottom layer near C10.",
      "status": "upheld"
    },
    {
      "id": "SI-002",
      "agent": "signal_integrity",
      "claim": "Differential pair USB_D_P and USB_D_N trace lengths differ by 4.2mm.",
      "severity": "major",
      "evidence": [
        {
          "evidence_id": "EV-SI-002A",
          "tool": "measure_skew",
          "summary": "Trace length difference: USB_D_P = 22.3mm, USB_D_N = 18.1mm. High-speed USB 2.0 skew exceeds 150ps."
        }
      ],
      "affected_nets": ["USB_D_P", "USB_D_N"],
      "affected_components": ["J1", "U1"],
      "board_region": {
        "x": 35,
        "y": 320,
        "w": 130,
        "h": 60,
        "image": "board.png"
      },
      "recommendation": "Length-match the USB differential traces to within 0.15mm by adding trace meanders near J1.",
      "status": "upheld"
    },
    {
      "id": "FW-002",
      "agent": "firmware_bringup",
      "claim": "I2C address conflict: EEPROM and Temp Sensor share address 0x50.",
      "severity": "critical",
      "evidence": [
        {
          "evidence_id": "EV-FW-002A",
          "tool": "parse_i2c_addresses",
          "summary": "EEPROM (U4) has hardwired address 0x50. Temp Sensor (U5) pin ADDR0 is tied to GND, setting address to 0x50."
        }
      ],
      "affected_nets": ["I2C_SDA", "I2C_SCL"],
      "affected_components": ["U4", "U5"],
      "recommendation": "Change address select pin ADDR0 on Temp Sensor U5 to VCC to set its address to 0x51.",
      "status": "upheld"
    },
    {
      "id": "DFM-003",
      "agent": "dfm_layout",
      "claim": "Component clearance between U4 and U5 is too small (0.2mm).",
      "severity": "minor",
      "evidence": [
        {
          "evidence_id": "EV-DFM-003A",
          "tool": "check_clearance",
          "summary": "Distance between bodies of U4 (SOIC-8) and U5 (MSOP-8) is 0.20mm, violating the 0.50mm minimum clearance limit."
        }
      ],
      "affected_nets": [],
      "affected_components": ["U4", "U5"],
      "board_region": {
        "x": 310,
        "y": 210,
        "w": 85,
        "h": 70,
        "image": "board.png"
      },
      "recommendation": "Move U5 1.5mm to the right to satisfy the 0.5mm clearance rule.",
      "status": "upheld"
    },
    {
      "id": "PI-003",
      "agent": "power_integrity",
      "claim": "Bypass capacitor C1 is placed too far (12mm) from MCU power pin.",
      "severity": "major",
      "evidence": [
        {
          "evidence_id": "EV-PI-003A",
          "tool": "measure_distance",
          "summary": "Distance from C1 pad 1 to U1 pin 1 (VCC) is 12.3mm. Recommended maximum is 3.0mm."
        }
      ],
      "affected_nets": ["VCC_3V3"],
      "affected_components": ["C1", "U1"],
      "recommendation": "Move C1 to within 2mm of U1 pin 1.",
      "status": "overruled",
      "conflicts_with": ["DFM-004"],
      "debate": [
        {
          "round": 1,
          "agent": "power_integrity",
          "position": "Bypass capacitor loop inductance will be too high if placed 12mm away, causing severe high-frequency voltage noise on the MCU core and potentially causing system resets.",
          "new_evidence_id": null
        },
        {
          "round": 1,
          "agent": "dfm_layout",
          "position": "Moving C1 close to U1 pin 1 blocks the escape routing channels of the 8-bit SPI high-speed data bus. The board will fail signal integrity and become unroutable on a 4-layer stackup.",
          "new_evidence_id": null
        },
        {
          "round": 2,
          "agent": "power_integrity",
          "position": "Can we place C1 on the bottom side of the PCB directly under U1 pin 1 to minimize distance without blocking the top layer signals?",
          "new_evidence_id": "EV-PI-003B"
        },
        {
          "round": 2,
          "agent": "dfm_layout",
          "position": "Placing C1 on the bottom side requires adding two vias. Vias add parasitic inductance (~1.2nH), which negates the benefit of closer proximity, and increases assembly costs.",
          "new_evidence_id": "EV-DFM-004B"
        }
      ],
      "ruling": {
        "decision": "overruled",
        "rationale": "The Moderator rules to overrule PI-003 and uphold DFM-004. Moving C1 to the top side blocks critical signal routing. A bottom-side placement is also rejected due to the inductance of the vias and manufacturing costs. C1 will remain in its original position, but a wider trace and dual ground vias will be added to minimize loop inductance.",
        "cited_evidence_ids": ["EV-DFM-004B"]
      }
    },
    {
      "id": "DFM-004",
      "agent": "dfm_layout",
      "claim": "Moving C1 closer to U1 pin 1 violates routing clearance of high-speed SPI bus.",
      "severity": "major",
      "evidence": [
        {
          "evidence_id": "EV-DFM-004A",
          "tool": "check_clearance",
          "summary": "Proposed placement of C1 conflicts with SPI_MISO, SPI_MOSI, SPI_CLK, and SPI_CS routing lines."
        }
      ],
      "affected_nets": ["VCC_3V3", "SPI_CLK"],
      "affected_components": ["C1", "U1"],
      "recommendation": "Keep C1 at current position but add a small ground via to minimize loop inductance.",
      "status": "upheld",
      "conflicts_with": ["PI-003"],
      "debate": [
        {
          "round": 1,
          "agent": "power_integrity",
          "position": "Bypass capacitor loop inductance will be too high if placed 12mm away, causing severe high-frequency voltage noise on the MCU core and potentially causing system resets.",
          "new_evidence_id": null
        },
        {
          "round": 1,
          "agent": "dfm_layout",
          "position": "Moving C1 close to U1 pin 1 blocks the escape routing channels of the 8-bit SPI high-speed data bus. The board will fail signal integrity and become unroutable on a 4-layer stackup.",
          "new_evidence_id": null
        },
        {
          "round": 2,
          "agent": "power_integrity",
          "position": "Can we place C1 on the bottom side of the PCB directly under U1 pin 1 to minimize distance without blocking the top layer signals?",
          "new_evidence_id": "EV-PI-003B"
        },
        {
          "round": 2,
          "agent": "dfm_layout",
          "position": "Placing C1 on the bottom side requires adding two vias. Vias add parasitic inductance (~1.2nH), which negates the benefit of closer proximity, and increases assembly costs.",
          "new_evidence_id": "EV-DFM-004B"
        }
      ],
      "ruling": {
        "decision": "upheld",
        "rationale": "The Moderator rules to overrule PI-003 and uphold DFM-004. Moving C1 to the top side blocks critical signal routing. A bottom-side placement is also rejected due to the inductance of the vias and manufacturing costs. C1 will remain in its original position, but a wider trace and dual ground vias will be added to minimize loop inductance.",
        "cited_evidence_ids": ["EV-DFM-004B"]
      }
    }
  ],
  "token_accounting": [
    {
      "agent": "moderator",
      "model": "qwen3-max",
      "prompt_tokens": 12500,
      "completion_tokens": 1820
    },
    {
      "agent": "power_integrity",
      "model": "qwen-flash",
      "prompt_tokens": 8450,
      "completion_tokens": 620
    },
    {
      "agent": "signal_integrity",
      "model": "qwen-flash",
      "prompt_tokens": 9200,
      "completion_tokens": 710
    },
    {
      "agent": "connectivity_erc",
      "model": "qwen-flash",
      "prompt_tokens": 7100,
      "completion_tokens": 490
    },
    {
      "agent": "dfm_layout",
      "model": "qwen3-vl",
      "prompt_tokens": 11300,
      "completion_tokens": 1150
    },
    {
      "agent": "firmware_bringup",
      "model": "qwen3-coder",
      "prompt_tokens": 6200,
      "completion_tokens": 820
    }
  ],
  "coverage_notes": [
    "Connectivity ERC: Verified all schematic net connections, pin types, and bidirectional interfaces. Identified one floating input.",
    "Power Integrity: Completed DC drop analysis for 5.0V, 3.3V, and 1.8V rails. U3 LDO runs excessively hot.",
    "Signal Integrity: Analyzed SPI clock line and USB high-speed lines. USB pair length skew detected.",
    "DFM Layout: Checked spacing rules on components, board dimensions, and thermal relief connections. Identified U4/U5 clearance conflict.",
    "Firmware Bringup: Inspected board pin map and device tree overlay configurations for hardware bring-up compatibility."
  ]
};
