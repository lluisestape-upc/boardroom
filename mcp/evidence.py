"""Per-session evidence cache for MCP tool outputs.

Every successful tool call gets a stable evidence id (``EV-0001``, ...).
Identical calls (same tool + same normalized args) within a session return the
cached entry — no duplicate id, no duplicate server round-trip. Findings cite
these ids per ``docs/schemas/finding.schema.json``; a finding referencing an
id that is not in the cache is invalid by construction.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from .errors import EvidenceNotFoundError


def canonical_key(tool: str, args: dict[str, Any]) -> str:
    """Deterministic cache key for a tool call (order-insensitive args)."""
    return json.dumps([tool, args], sort_keys=True, separators=(",", ":"), default=str)


class EvidenceEntry(BaseModel):
    """One cached tool output. ``{evidence_id, tool, summary}`` is exactly the
    evidence-item shape of finding.schema.json; ``args`` and ``raw`` are kept
    for the report frontend and debate transcript."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str
    tool: str
    args: dict[str, Any]
    summary: str
    raw: str

    def as_finding_evidence(self, summary: str | None = None) -> dict[str, str]:
        """Evidence item ready to embed in a finding. A specialist may pass a
        claim-specific ``summary`` ("what in the output supports the claim");
        defaults to the adapter's neutral summary."""
        return {
            "evidence_id": self.evidence_id,
            "tool": self.tool,
            "summary": summary or self.summary,
        }


class EvidenceCache:
    """Session-scoped cache mapping (tool, args) -> :class:`EvidenceEntry`."""

    def __init__(self, session_id: str | None = None, *, prefix: str = "EV") -> None:
        self.session_id = session_id
        self._prefix = prefix
        self._by_id: dict[str, EvidenceEntry] = {}
        self._id_by_key: dict[str, str] = {}
        self.hits = 0
        self.misses = 0

    def _next_id(self) -> str:
        return f"{self._prefix}-{len(self._by_id) + 1:04d}"

    def get(self, tool: str, args: dict[str, Any]) -> EvidenceEntry | None:
        """Cached entry for this exact call, or None. Counts hit/miss stats
        (the dedup rate feeds the token/efficiency benchmark)."""
        entry_id = self._id_by_key.get(canonical_key(tool, args))
        if entry_id is None:
            self.misses += 1
            return None
        self.hits += 1
        return self._by_id[entry_id]

    def put(
        self, tool: str, args: dict[str, Any], *, raw: str, summary: str
    ) -> EvidenceEntry:
        """Store a successful tool output. Idempotent: an existing entry for
        the same (tool, args) is returned unchanged — evidence ids are stable
        within a session."""
        key = canonical_key(tool, args)
        existing_id = self._id_by_key.get(key)
        if existing_id is not None:
            return self._by_id[existing_id]
        entry = EvidenceEntry(
            evidence_id=self._next_id(),
            tool=tool,
            args=dict(args),
            summary=summary,
            raw=raw,
        )
        self._by_id[entry.evidence_id] = entry
        self._id_by_key[key] = entry.evidence_id
        return entry

    def lookup(self, evidence_id: str) -> EvidenceEntry:
        """Entry by id — used to validate findings' evidence references."""
        try:
            return self._by_id[evidence_id]
        except KeyError:
            raise EvidenceNotFoundError(
                f"evidence id {evidence_id!r} is not in the session cache"
            ) from None

    def __contains__(self, evidence_id: str) -> bool:
        return evidence_id in self._by_id

    def __len__(self) -> int:
        return len(self._by_id)

    def entries(self) -> list[EvidenceEntry]:
        """All entries in creation order."""
        return list(self._by_id.values())

    def stats(self) -> dict[str, int]:
        return {"entries": len(self._by_id), "hits": self.hits, "misses": self.misses}
