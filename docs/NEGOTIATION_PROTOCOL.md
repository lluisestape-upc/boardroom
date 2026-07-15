# BoardRoom Negotiation Protocol (v1)

The mechanism that makes this an agent *society* rather than a fan-out pipeline.
FROZEN except by architect sign-off.

## 1. Filing

Specialists review their assigned scope concurrently and file findings conforming to
`schemas/finding.schema.json`. A finding without at least one evidence entry
referencing a cached MCP tool output is rejected at the boundary (one retry, then
dropped and counted as an uncited claim — this feeds the hallucination-rate metric).

## 2. Conflict detection (orchestrator, deterministic — no LLM)

Two findings conflict when they overlap in `affected_nets` or `affected_components`
AND their recommendations are marked incompatible by the Moderator in a single cheap
classification pass. Conflicting findings get `status: contested` and populate
`conflicts_with`.

Canonical demo conflict: Signal Integrity wants a stitched ground pour / rerouted
diff pair; DFM & Layout objects (cost, manufacturability, clearance).

## 3. Bounded debate

For each conflict, the Moderator opens a debate:

- **Max 2 rounds.** Hard limit, enforced in code.
- Each round, each side submits a position (≤ 150 words) and MAY request **exactly
  one** additional MCP tool call to strengthen its evidence. The orchestrator
  executes it and attaches the new evidence id.
- No side may introduce claims outside its scope/allowlist.

## 4. Ruling (evidence weighting)

After round 2 (or earlier if a side concedes), the Moderator rules:
`upheld` / `overruled` / `merged` (a synthesized recommendation both constraints
accept). The ruling MUST cite the specific `evidence_id`s that decided it — a ruling
citing no evidence is invalid and is retried once. Rationale is stored verbatim; the
debate transcript is preserved for the report and the demo video.

## 5. Signed review

The final review = all upheld/merged findings + rulings + per-agent token accounting +
coverage notes for any scope a specialist failed to cover. Written as
`session_<id>/review.json`, consumed by `report/` (Antigravity workstream) and
`benchmark/`.

## Why bounded

The efficiency claim vs. a single-agent baseline depends on specialists being cheap
(qwen-flash) and debates being short. Unbounded argumentation would burn the token
advantage; two evidence-backed rounds is where the value is.
