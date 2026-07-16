"""The single seam between the benchmark harness and the review runner.

`execute_review(board_path, config)` is the ONE function the harness calls to
produce a ``review.json``-shaped dict for a (possibly seeded) board under a given
configuration ("society" or "baseline"). Everything else in benchmark/ (corpus,
seeding, metrics, aggregation, charts) is wired end-to-end around this function
and is fully testable today via the deterministic MOCK below.

=============================== WIRING THE REAL RUNNER ========================
The real runner is being built concurrently. To integrate it, implement the body
marked ``TODO(real-runner)`` so that `execute_review` runs the actual
society/baseline pipeline (through backend/app/qwen_client.py so token accounting
is comparable) and returns the same dict shape documented below. Do NOT change
this function's signature or return contract -- the harness depends only on:

    execute_review(board_path: Path, config: str, *, ground_truth=None) -> dict

Returned dict (see benchmark/metrics.py for how each field is scored):
    {
      "config": str, "board_id": str,
      "findings": [ finding.schema.json objects ],
      "rejected_findings": int,          # uncited findings rejected at boundary
      "token_accounting": { "<agent>/<model>": {"prompt", "completion", "calls"} },
      "wall_time_s": float,
    }

Until the real runner lands, `execute_review` dispatches to `mock_review`, which
fabricates a plausible, deterministic review FROM the ground truth so the whole
pipeline + metrics + charts run now. ``ground_truth`` is a mock-only convenience;
the real runner ignores it (it must never see the answer key).
=============================================================================
"""

from __future__ import annotations

import os
from pathlib import Path

from .seed import GroundTruthDefect

# Per-config model routing used to shape mock token accounting so the society's
# cheap-specialist / one-expensive-chair asymmetry shows up in the cost metric.
# Mirrors docs/ARCHITECTURE.md model routing (kept local to the mock).
_AGENT_MODEL = {
    "power_integrity": "qwen-flash",
    "signal_integrity": "qwen-flash",
    "connectivity_erc": "qwen-flash",
    "dfm_layout": "qwen3-vl-plus",
    "firmware_bringup": "qwen3-coder-plus",
    "moderator": "qwen3-max",
}


def execute_review(
    board_path: Path,
    config: str,
    *,
    ground_truth: list[GroundTruthDefect] | None = None,
) -> dict:
    """Produce a review.json-shaped dict for ``board_path`` under ``config``.

    SEAM: currently returns a deterministic mock. See the module docstring for
    how to wire the real society/baseline runner here.
    """
    if config not in ("society", "baseline"):
        raise ValueError(f"unknown config {config!r}; expected 'society' or 'baseline'")

    # Real pipeline when explicitly enabled (needs DASHSCOPE_API_KEY + kicad-mcp-server);
    # otherwise the deterministic offline mock, which keeps the harness + tests runnable
    # anywhere. The real path ignores ground_truth (it must never see the answer key).
    if os.environ.get("BOARDROOM_REAL_RUNNER"):
        from ._real import real_execute

        return real_execute(board_path, config)
    return mock_review(board_path, config, ground_truth or [])


def mock_review(board_path: Path, config: str, ground_truth: list[GroundTruthDefect]) -> dict:
    """Deterministic, offline stand-in for a real review.

    Fabricates findings from the ground truth so the harness is exercisable:

    * society  -- higher recall (catches all seeded defects), fewer hallucinations,
      one extra false positive; cheap-specialist token profile.
    * baseline -- lower recall (misses the last seeded defect), more uncited
      findings; single expensive-model token profile.

    These are ILLUSTRATIVE numbers for pipeline testing, not measured results.
    The real runner replaces this entirely (see module docstring).
    """
    board_id = board_path.name
    findings: list[dict] = []
    ev_counter = 0

    if config == "society":
        catch = ground_truth  # society catches every seeded defect
        rejected = 0
        extra_false_positives = 1
        uncited = 0
    else:
        catch = ground_truth[:-1] if len(ground_truth) > 1 else ground_truth
        rejected = 3  # baseline files more uncited claims that get rejected
        extra_false_positives = 2
        uncited = 1

    for i, d in enumerate(catch):
        ev_counter += 1
        findings.append(
            {
                "id": f"{d.expected_agent[:2].upper()}-{i + 1:03d}",
                "agent": d.expected_agent,
                "claim": d.description or f"Seeded defect {d.type}",
                "severity": d.expected_severity,
                "evidence": [
                    {
                        "evidence_id": f"EV-{ev_counter:04d}",
                        "tool": "get_netlist_nets",
                        "summary": f"net/ref evidence for {d.type}",
                    }
                ],
                "affected_nets": list(d.affected_nets),
                "affected_components": list(d.affected_refs),
                "recommendation": f"Address seeded {d.type}",
                "status": "upheld",
            }
        )

    # Non-matching (false-positive) findings: cite evidence but point at a net that
    # is not in any ground-truth defect, so they never match the matcher.
    for j in range(extra_false_positives):
        ev_counter += 1
        findings.append(
            {
                "id": f"FP-{j + 1:03d}",
                "agent": "dfm_layout",
                "claim": "Silkscreen overlap near mounting hole",
                "severity": "minor",
                "evidence": [
                    {"evidence_id": f"EV-{ev_counter:04d}", "tool": "get_pcb_statistics", "summary": "cosmetic"}
                ],
                "affected_nets": [f"__NO_SUCH_NET_{j}__"],
                "affected_components": [f"__NO_SUCH_REF_{j}__"],
                "recommendation": "Nudge silkscreen",
                "status": "upheld",
            }
        )

    # Emitted-but-uncited findings (baseline): counted by the hallucination metric.
    for k in range(uncited):
        findings.append(
            {
                "id": f"HL-{k + 1:03d}",
                "agent": "signal_integrity",
                "claim": "Suspected impedance mismatch (no tool evidence)",
                "severity": "major",
                "evidence": [],
                "affected_nets": [],
                "affected_components": [],
                "recommendation": "Review stackup",
                "status": "open",
            }
        )

    token_accounting = _mock_token_accounting(config, defect_count=len(ground_truth))
    wall = 42.0 if config == "society" else 71.0  # illustrative

    return {
        "config": config,
        "board_id": board_id,
        "findings": findings,
        "rejected_findings": rejected,
        "token_accounting": token_accounting,
        "wall_time_s": wall,
    }


def _mock_token_accounting(config: str, defect_count: int) -> dict[str, dict[str, int]]:
    """Deterministic token profile per config.

    society  -- one qwen3-max moderator (small) + several cheap qwen-flash
                specialists; the cost asymmetry is the point of the benchmark.
    baseline -- a single qwen3-max agent doing everything (large prompt+completion).
    """
    base = max(1, defect_count)
    if config == "society":
        return {
            "moderator/qwen3-max": {"prompt": 4000, "completion": 800, "calls": 2},
            "power_integrity/qwen-flash": {"prompt": 3000 * base, "completion": 600 * base, "calls": base},
            "signal_integrity/qwen-flash": {"prompt": 2500 * base, "completion": 500 * base, "calls": base},
            "connectivity_erc/qwen-flash": {"prompt": 2500 * base, "completion": 500 * base, "calls": base},
            "firmware_bringup/qwen3-coder-plus": {"prompt": 1800, "completion": 400, "calls": 1},
            "dfm_layout/qwen3-vl-plus": {"prompt": 1500, "completion": 300, "calls": 1},
        }
    return {
        "baseline/qwen3-max": {"prompt": 16000 * base, "completion": 3000 * base, "calls": base + 1},
    }
