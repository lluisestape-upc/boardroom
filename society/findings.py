"""Finding validation boundary.

Specialists emit raw text that is supposed to be a JSON array of findings conforming
to docs/schemas/finding.schema.json. This module is the only place that turns that
raw text into trusted finding objects:

    valid, rejected = parse_and_validate(raw, known_evidence_ids=cache.ids())

The orchestrator retries an agent once on rejections; whatever is still rejected
after the retry is dropped and counted — that count is the hallucination-rate input
for benchmark/metrics.py (see NEGOTIATION_PROTOCOL.md section 1).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[1]
FINDING_SCHEMA_PATH = REPO_ROOT / "docs" / "schemas" / "finding.schema.json"

# ```json ... ``` or ``` ... ``` — models love fencing even when told not to.
_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n(.*?)\n?```\s*$", re.DOTALL)


@dataclass
class RejectedFinding:
    """One rejected item (or the whole payload, when it wasn't parseable)."""

    item: Any  # the offending finding dict, or the raw text for parse failures
    reasons: list[str] = field(default_factory=list)


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    with FINDING_SCHEMA_PATH.open(encoding="utf-8") as f:
        schema = json.load(f)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def strip_fences(raw: str) -> str:
    """Return the payload inside a markdown code fence, or the input stripped."""
    raw = raw.strip()
    m = _FENCE_RE.match(raw)
    return m.group(1).strip() if m else raw


def parse_and_validate(
    raw: str,
    *,
    known_evidence_ids: set[str] | frozenset[str] | None = None,
) -> tuple[list[dict], list[RejectedFinding]]:
    """Parse model output into (valid_findings, rejected).

    Tolerates markdown fences and a single finding object instead of an array.
    Each item is validated against finding.schema.json. When
    ``known_evidence_ids`` is given (the evidence cache's real ids for this
    session), findings citing any id outside that set are rejected — that is the
    anti-hallucination check: agents may only cite evidence they actually received.

    Never raises on bad model output; failures come back in ``rejected`` with
    human-readable reasons (persisted for the benchmark and the retry prompt).
    """
    text = strip_fences(raw)

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], [RejectedFinding(item=raw, reasons=[f"malformed JSON: {exc}"])]

    if isinstance(payload, dict):
        payload = [payload]  # tolerate a bare finding object
    if not isinstance(payload, list):
        return [], [
            RejectedFinding(
                item=payload,
                reasons=[f"expected a JSON array of findings, got {type(payload).__name__}"],
            )
        ]

    valid: list[dict] = []
    rejected: list[RejectedFinding] = []

    for idx, item in enumerate(payload):
        reasons: list[str] = []

        if not isinstance(item, dict):
            rejected.append(
                RejectedFinding(item=item, reasons=[f"finding #{idx} is not an object"])
            )
            continue

        for error in _validator().iter_errors(item):
            path = ".".join(str(p) for p in error.absolute_path) or "<root>"
            reasons.append(f"schema violation at {path}: {error.message}")

        if known_evidence_ids is not None and not reasons:
            cited = {
                e.get("evidence_id")
                for e in item.get("evidence", [])
                if isinstance(e, dict)
            }
            unknown = sorted(str(i) for i in cited - set(known_evidence_ids))
            if unknown:
                reasons.append(
                    f"cites evidence_id(s) not present in the session evidence cache: {unknown}"
                )

        if reasons:
            rejected.append(RejectedFinding(item=item, reasons=reasons))
        else:
            valid.append(item)

    return valid, rejected


def rejection_report(rejected: list[RejectedFinding]) -> str:
    """Human-readable summary — used verbatim in the one retry prompt to the agent."""
    lines = []
    for r in rejected:
        ident = r.item.get("id", "<no id>") if isinstance(r.item, dict) else "<unparseable output>"
        for reason in r.reasons:
            lines.append(f"- {ident}: {reason}")
    return "\n".join(lines)
