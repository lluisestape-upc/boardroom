window.BOARDROOM_SAMPLE_REVIEW = {
  "session_id": "dead885162be",
  "project_path": "fixtures/stickhub",
  "finding_schema": "docs/schemas/finding.schema.json",
  "protocol": {
    "version": 1,
    "max_debate_rounds": 2,
    "extra_tool_calls_per_side_per_round": 1
  },
  "findings": [
    {
      "id": "PI-001",
      "agent": "power_integrity",
      "claim": "+5V rail has mixed copper widths (0.2 mm to 0.6 mm) and only 9 vias, risking voltage drop under load.",
      "severity": "major",
      "evidence": [
        {
          "evidence_id": "EV-0013",
          "tool": "find_tracks_by_net",
          "summary": "Net +5V: 120 segments, 87.696 mm on B.Cu, F.Cu, 9 vias, 2 zones, mixed widths"
        }
      ],
      "affected_nets": [
        "+5V"
      ],
      "affected_components": [],
      "recommendation": "Increase minimum copper width to 0.6 mm across all segments and add 3 more vias for better current distribution.",
      "status": "open"
    },
    {
      "id": "PI-002",
      "agent": "power_integrity",
      "claim": "+1V8 rail has mixed copper widths (0.15 mm to 0.3 mm) and only 2 vias, increasing risk of IR drop.",
      "severity": "major",
      "evidence": [
        {
          "evidence_id": "EV-0018",
          "tool": "find_tracks_by_net",
          "summary": "Net +1V8: 41 segments, 20.56 mm on B.Cu, F.Cu, 2 vias, 1 zones, mixed widths"
        }
      ],
      "affected_nets": [
        "+1V8"
      ],
      "affected_components": [],
      "recommendation": "Standardize copper width to 0.3 mm minimum and add 2 additional vias to improve current handling.",
      "status": "open"
    },
    {
      "id": "DFM-001",
      "agent": "dfm_layout",
      "status": "open",
      "severity": "major",
      "title": "Silkscreen text over pads on USB connectors",
      "description": "Silkscreen labels 'USB1' through 'USB7' and 'DP', 'DN', '+' are printed directly over solder pads of J1\u2013J8 and the bottom USB-A footprint. This risks solder mask misregistration, pad coverage loss, and tombstoning during reflow.",
      "claim": "Silkscreen overlaps copper pads on multiple USB footprints",
      "evidence": [
        {
          "evidence_id": "EV-0004",
          "tool": "render_board",
          "summary": "Top-layer render shows silkscreen text overlaid on pads of all USB connectors (J1\u2013J8) and bottom USB-A footprint."
        }
      ],
      "board_region": {
        "x": 0,
        "y": 0,
        "w": 168,
        "h": 448,
        "image": "StickHub_top.png"
      },
      "affected_components": [
        "J1",
        "J2",
        "J5",
        "J7",
        "J8",
        "D15",
        "D16",
        "D19",
        "D20",
        "D21"
      ],
      "recommendation": "Reposition all USB silkscreen labels at least 0.5 mm away from pad edges; use keepout layer or manual offset to ensure no overlap with copper."
    },
    {
      "id": "DFM-002",
      "agent": "dfm_layout",
      "status": "open",
      "severity": "major",
      "title": "No fiducials on SMT board",
      "description": "Board is SMT-assembled (multiple 0402, 2012, and fine-pitch connectors) but contains zero global or local fiducial marks. This will cause placement machine misalignment and yield loss.",
      "claim": "No fiducial markers present on top layer",
      "evidence": [
        {
          "evidence_id": "EV-0004",
          "tool": "render_board",
          "summary": "Render shows no fiducial markers anywhere on top copper/silk layer."
        }
      ],
      "board_region": null,
      "affected_components": [],
      "recommendation": "Add three non-plated circular fiducials (\u22651.0 mm diameter) at board corners, outside component courtyards, per IPC-7351."
    },
    {
      "id": "DFM-003",
      "agent": "dfm_layout",
      "status": "open",
      "severity": "minor",
      "title": "Missing polarity/pin-1 indicators on LEDs",
      "description": "Duo LED footprints (D15, D16, D19, D20, D21) lack pin-1 or cathode markings in silkscreen or copper. Risk of reverse assembly for bi-color LEDs.",
      "claim": "LED footprints have no polarity marking",
      "evidence": [
        {
          "evidence_id": "EV-0004",
          "tool": "render_board",
          "summary": "LED footprints show symmetric silkscreen outlines with no polarity dot or notch."
        }
      ],
      "board_region": {
        "x": 120,
        "y": 320,
        "w": 48,
        "h": 24,
        "image": "StickHub_top.png"
      },
      "affected_components": [
        "D15",
        "D16",
        "D19",
        "D20",
        "D21"
      ],
      "recommendation": "Add a silkscreen triangle or dot near pin 1 (cathode) of each Duo LED footprint; verify against LED datasheet polarity."
    },
    {
      "id": "DFM-004",
      "agent": "dfm_layout",
      "status": "open",
      "severity": "minor",
      "title": "Crowded designator placement near connectors",
      "description": "Designators 'USB1'\u2013'USB7' are placed too close to connector bodies, risking collision with adjacent parts or masking during assembly inspection.",
      "claim": "Designators abut connector outlines, violating minimum clearance",
      "evidence": [
        {
          "evidence_id": "EV-0004",
          "tool": "render_board",
          "summary": "Designators abut connector outlines; e.g., 'USB1' overlaps J1 body edge."
        }
      ],
      "board_region": {
        "x": 80,
        "y": 20,
        "w": 88,
        "h": 40,
        "image": "StickHub_top.png"
      },
      "affected_components": [
        "J1",
        "J2",
        "J5",
        "J7",
        "J8"
      ],
      "recommendation": "Offset all USB designators \u22650.75 mm from connector outlines; rotate or relocate to avoid courtyard intrusion."
    }
  ],
  "rulings": [],
  "debates": [],
  "rejected_findings": [],
  "coverage_notes": [],
  "token_accounting": {
    "connectivity_erc/qwen-flash": {
      "prompt": 25705,
      "completion": 204,
      "calls": 8
    },
    "signal_integrity/qwen-flash": {
      "prompt": 43129,
      "completion": 657,
      "calls": 8
    },
    "power_integrity/qwen-flash": {
      "prompt": 27548,
      "completion": 1014,
      "calls": 7
    },
    "dfm_layout/qwen3-vl-plus": {
      "prompt": 21537,
      "completion": 3472,
      "calls": 5
    },
    "firmware_bringup/qwen3-coder-plus": {
      "prompt": 9362,
      "completion": 182,
      "calls": 3
    }
  },
  "created_at": "2026-07-16T15:15:26.758547+00:00",
  "signed_at": "2026-07-16T15:17:53.717581+00:00",
  "render": {
    "image": "StickHub_top.png",
    "width_px": 168,
    "height_px": 448,
    "dpi": 300.0
  },
  "project_name": "StickHub USB Hub (KiCad demo) \u2014 live BoardRoom review"
};
