# Antigravity Feedback & Schema Questions (`report/QUESTIONS.md`)

This document records architectural feedback, edge cases, and suggestions for future iterations (v2) of the `finding.schema.json` contract and `review.json` session file format.

---

## 1. Schema Contract Questions & Ambiguities

### A. Coordinate System & DPI Standardization for `board_region`
- **Issue**: The schema description states: `"Optional bounding box on the rendered board image (px)"`. In PCB design systems (KiCad), layout coordinates are defined in millimeters (mm) or mils. Mapping relative pixels to an image depends heavily on the CLI render resolution (DPI).
- **Question**: Is there a standard DPI that `kicad-cli` uses for this project (e.g., 300 DPI)? If the render resolution changes, the coordinates (`x, y, w, h`) filed by the VL layout critic will skew.
- **Suggestion**: Add a `dpi` property to the `board_region` object or define the coordinates in physical board units (mm) relative to the PCB auxiliary origin, along with the image physical size in millimeters.

### B. Rich/Visual Tool Evidence
- **Issue**: Currently, `evidence` objects contain only a string `summary`. Some KiCad MCP tools (such as transient or signal integrity simulators) generate rich outputs: charts, simulation tables, or localized ERC warning files.
- **Question**: How can specialist agents attach secondary visual artifacts to their findings?
- **Suggestion**: Add an optional `artifacts` array of strings (filepaths or URLs) to the `evidence` schema, allowing the report to render waveform plots or schematic sub-sheets alongside the text summary.

### C. Display Labels for Agents
- **Issue**: Agent names in the schema are enum strings (e.g., `power_integrity`, `dfm_layout`). The frontend must parse and convert these to clean typography (e.g., "Power Integrity").
- **Suggestion**: Add a mapping catalog at the root of `review.json` or allow an optional `agent_label` field to decouple frontend rendering from enum database keys.

---

## 2. Protocol Questions

### A. Non-Contested Rulings & Concessions
- **Issue**: If an agent files a finding that is contested, but the opponent concedes in Round 1, how is the ruling structured? The protocol mentions "earlier if a side concedes".
- **Question**: Does a concession bypass Round 2 and jump straight to the moderator's `ruling` block, or does the conceding agent modify its status to `overruled`/`merged` without a moderator ruling?
- **Suggestion**: Ensure the orchestrator writes a standard `ruling` with `decision: "overruled"` (if PI concedes) and rationale `"Specialist conceded to DFM space arguments in round 1."` to preserve history.

### B. Session Timestamp Metadata
- **Issue**: The root `review.json` object contains `session_id` and `project_name` but lacks timestamps.
- **Suggestion**: Add `created_at` and `completed_at` (ISO 8601 strings) to the root session structure to allow chronological session listing in server dashboards.
