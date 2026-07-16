"""The Moderator: drives a review session end to end.

Day 1 (TASKS.md):
    dispatch N specialists CONCURRENTLY with per-specialist exception isolation,
    schema-validate their findings at the boundary, and assemble a draft
    review.json (findings + coverage_notes + token_accounting).

Day 2 (this file, NEGOTIATION_PROTOCOL.md):
    - ``detect_conflicts``   — §2 deterministic overlap on affected_nets /
      affected_components between findings from *different* agents.
    - ``classify_conflicts`` — §2 single batched Moderator model call that marks
      each overlapping pair compatible/incompatible. Incompatible findings get
      ``status: contested`` and populated ``conflicts_with``.
    - ``run_debate``         — §3 bounded debate: MAX_DEBATE_ROUNDS (= 2, hard
      limit); each side per round submits a ≤150-word position (truncated, never
      failed) and MAY request exactly one extra tool call, executed through the
      injected ToolLayer and recorded as ``new_evidence_id``. Early concession
      short-circuits the debate but still yields a standard ruling block
      (architect ruling 2A in report/QUESTIONS.md §3).
    - ``rule_on_conflict``   — §4 evidence-cited ruling with one validation
      retry, then a deterministic "upheld both, flagged unresolved" fallback so
      the session always signs.
    - review root additions  — architect rulings 1A/2B: ``created_at`` /
      ``signed_at`` timestamps and a pass-through ``render`` metadata slot from
      the manifest. Additive only; finding.schema.json is untouched.

Remaining seams: registry swap (interfaces.load_agent_configs) and real MCP
wiring (interfaces.ToolLayer / ManifestBuilder).
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

from .interfaces import (
    AgentConfig,
    ModelClient,
    SpecialistRunner,
    ToolLayer,
    load_agent_configs,
)
from .sessions import Session, SessionState, SessionStore

# --- protocol constants (NEGOTIATION_PROTOCOL.md — FROZEN except by architect) ----

#: §3 "Max 2 rounds. Hard limit, enforced in code."
MAX_DEBATE_ROUNDS = 2
#: §3 "each side ... MAY request exactly one additional MCP tool call" per round.
EXTRA_TOOL_CALLS_PER_SIDE_PER_ROUND = 1
#: §1 / §4 — invalid findings and evidence-free rulings get exactly one retry.
MAX_VALIDATION_RETRIES = 1
#: §3 — each debate position is capped at 150 words (truncated, never failed).
POSITION_WORD_CAP = 150

#: The Moderator's own agent name (a valid ``agent`` enum value in the schema).
MODERATOR_AGENT = "moderator"
#: Fallbacks when society/registry.yaml is unavailable (concurrent workstream).
DEFAULT_MODERATOR_MODEL = "qwen3-max"
DEFAULT_DEBATE_MODEL = "qwen-flash"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _REPO_ROOT / "docs" / "schemas" / "finding.schema.json"
#: society/ files are owned by the society-engineer workstream and may land
#: concurrently — read if present, fall back to built-in defaults, never write.
_MODERATOR_PROMPT_PATH = _REPO_ROOT / "society" / "prompts" / "moderator.md"
_REGISTRY_PATH = _REPO_ROOT / "society" / "registry.yaml"

DEFAULT_MODERATOR_PROMPT = (
    "You are the Moderator of BoardRoom, a multi-agent PCB design review society. "
    "You chair bounded debates between specialist agents and issue impartial, "
    "evidence-weighted rulings per docs/NEGOTIATION_PROTOCOL.md. Be terse and "
    "technical. When asked for JSON, reply with ONLY a JSON object — no prose, "
    "no code fences."
)


@lru_cache(maxsize=1)
def _finding_validator() -> Draft202012Validator:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def validate_finding(finding: object) -> list[str]:
    """Validate one finding against docs/schemas/finding.schema.json (FROZEN v1).

    Returns a list of human-readable error strings; empty means valid.
    """
    errors = sorted(
        _finding_validator().iter_errors(finding), key=lambda e: list(e.path)
    )
    return [
        f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors
    ]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def moderator_prompt() -> str:
    """The Moderator system prompt: society/prompts/moderator.md when present.

    That file is owned by the society-engineer workstream and may not exist yet;
    read fresh on every call (no cache) so it is picked up the moment it lands.
    """
    try:
        text = _MODERATOR_PROMPT_PATH.read_text(encoding="utf-8").strip()
        if text:
            return text
    except OSError:
        pass
    return DEFAULT_MODERATOR_PROMPT


def moderator_model() -> str:
    """The Moderator's model id from society/registry.yaml, with a safe fallback."""
    try:
        import yaml  # backend/requirements.txt ships pyyaml

        data = yaml.safe_load(_REGISTRY_PATH.read_text(encoding="utf-8"))
        model = data["agents"][MODERATOR_AGENT]["model"]
        if isinstance(model, str) and model:
            return model
    except Exception:  # noqa: BLE001 — registry is a concurrent workstream
        pass
    return DEFAULT_MODERATOR_MODEL


# --- model-output helpers ----------------------------------------------------------

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _parse_json_object(raw: str) -> dict:
    """Parse a model reply as a JSON object, tolerating markdown code fences."""
    text = (raw or "").strip()
    match = _FENCE_RE.match(text)
    if match:
        text = match.group(1)
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError(f"expected a JSON object, got {type(obj).__name__}")
    return obj


def _truncate_words(text: str, cap: int = POSITION_WORD_CAP) -> str:
    """§3 word cap: truncate, don't fail."""
    words = text.split()
    if len(words) <= cap:
        return text
    return " ".join(words[:cap])


def _finding_digest(finding: dict) -> dict:
    """The trimmed finding view sent to classification (keeps the batch cheap)."""
    return {
        "id": finding.get("id"),
        "agent": finding.get("agent"),
        "claim": finding.get("claim"),
        "severity": finding.get("severity"),
        "recommendation": finding.get("recommendation"),
        "affected_nets": finding.get("affected_nets", []),
        "affected_components": finding.get("affected_components", []),
    }


def _evidence_ids(finding: dict) -> list[str]:
    return [
        e["evidence_id"]
        for e in finding.get("evidence", [])
        if isinstance(e, dict) and "evidence_id" in e
    ]


def _overlap(a: dict, b: dict) -> dict:
    nets = sorted(set(a.get("affected_nets") or []) & set(b.get("affected_nets") or []))
    components = sorted(
        set(a.get("affected_components") or [])
        & set(b.get("affected_components") or [])
    )
    return {"nets": nets, "components": components}


# --- prompt templates (keep in sync with society/prompts/moderator.md) --------------

_CLASSIFICATION_INSTRUCTIONS = (
    "TASK: conflict classification (NEGOTIATION_PROTOCOL.md §2).\n"
    "You are given pairs of review findings that overlap in affected nets or "
    "components. For each pair, decide whether the two recommendations are "
    "compatible (both can be applied to the board as-is) or incompatible (they "
    "pull the design in conflicting directions and must be debated).\n"
    "Reply with ONLY a JSON object of the shape:\n"
    '{"classifications": [{"pair_id": <int>, "compatible": <true|false>, '
    '"reason": "<one short sentence>"}]}\n'
    "Include every pair_id you were given exactly once."
)

_DEBATE_SYSTEM_TEMPLATE = (
    "You are the {agent} specialist in a PCB design review, in a bounded debate "
    "chaired by the Moderator (NEGOTIATION_PROTOCOL.md §3). Defend your finding "
    "with evidence, stay strictly within your scope and tool allowlist, and "
    "concede if the opposing evidence is stronger.\n"
    "Reply with ONLY a JSON object of the shape:\n"
    '{{"position": "<your argument, {cap} words max>", "concede": <true|false>, '
    '"tool_request": {{"tool": "<tool name>", "arguments": {{}}}} or null}}\n'
    "You may request at most ONE extra tool call this round via tool_request; "
    "use null if you do not need one."
)

_RULING_INSTRUCTIONS = (
    "TASK: rule on a contested conflict (NEGOTIATION_PROTOCOL.md §4). Weigh the "
    "cited evidence on both sides and the debate transcript, then decide.\n"
    "Reply with ONLY a JSON object of the shape:\n"
    '{"decision": "upheld" | "merged", '
    '"upheld_finding_id": "<id of the winning finding; null when decision is merged>", '
    '"rationale": "<why, referencing the evidence>", '
    '"cited_evidence_ids": ["<evidence_id>", ...], '
    '"merged_recommendation": "<only when decision is merged>"}\n'
    "Rules: cited_evidence_ids must be non-empty and every id must come from the "
    "provided valid_evidence_ids. When decision is 'upheld', the losing finding is "
    "recorded as overruled. 'merged' means you synthesize one recommendation both "
    "constraints accept."
)


class LocalManifestBuilder:
    """Day 1 manifest: enumerate KiCad files on the local filesystem.

    Day 2 seam: replace with an mcp/-backed builder (get_schematic_info,
    get_pcb_statistics, netlist — ARCHITECTURE.md lifecycle step 1). Same
    ``ManifestBuilder`` protocol, so the Moderator is untouched.
    """

    KICAD_EXTENSIONS = (".kicad_pro", ".kicad_sch", ".kicad_pcb")

    async def build(self, project_path: str) -> dict:
        root = Path(project_path)
        if not root.is_dir():
            raise FileNotFoundError(f"not a directory: {project_path}")
        files = sorted(
            str(p.relative_to(root))
            for p in root.rglob("*")
            if p.suffix in self.KICAD_EXTENSIONS
        )
        return {
            "project_path": str(root),
            "kicad_files": files,
            "file_count": len(files),
            "builder": "local-day1",
            "built_at": _utcnow(),
        }


class ModelBackedSpecialistRunner:
    """Day 1 default runner: one chat call, findings as a JSON array.

    Day 2 seam: replaced by the tool-driven specialist loop (per-agent allowlists
    and evidence cache from mcp/, prompts from society/). Tests inject fakes
    implementing ``SpecialistRunner`` instead.
    """

    def __init__(self, model_client: ModelClient):
        self._model_client = model_client

    async def run(
        self,
        *,
        config: AgentConfig,
        session_id: str,
        project_path: str,
        manifest: dict,
    ) -> list[dict]:
        messages = [
            {
                "role": "system",
                "content": (
                    f"You are the {config.name} specialist in a PCB design review. "
                    "Reply with ONLY a JSON array of findings conforming to "
                    "finding.schema.json (id, agent, claim, severity, evidence, "
                    "recommendation, status)."
                ),
            },
            {
                "role": "user",
                "content": "Project manifest:\n" + json.dumps(manifest, indent=2),
            },
        ]
        raw = await self._model_client.chat(
            agent=config.name, model=config.model, messages=messages
        )
        findings = json.loads(raw)
        if not isinstance(findings, list):
            raise ValueError(f"{config.name} returned non-array findings payload")
        return findings


class Moderator:
    """Assign → collect → negotiate (detect → debate → rule) → sign."""

    def __init__(
        self,
        *,
        store: SessionStore,
        model_client: ModelClient,
        specialist_runner: SpecialistRunner,
        agent_configs: list[AgentConfig] | None = None,
        manifest_builder=None,
        tool_layer: ToolLayer | None = None,
    ):
        self._store = store
        self._model_client = model_client
        self._runner = specialist_runner
        self._configs = agent_configs if agent_configs is not None else load_agent_configs()
        self._manifest_builder = manifest_builder or LocalManifestBuilder()
        #: Debate-round extra tool calls go through this (allowlist-enforced).
        #: None (mcp/ workstream not wired yet) → tool requests are recorded as
        #: unfulfilled (new_evidence_id stays null), never a crash.
        self._tool_layer = tool_layer

    # -- public entrypoint -------------------------------------------------------

    async def run_review(self, session_id: str) -> None:
        """Drive one session to ``signed`` or ``failed``. Never raises.

        Specialist crashes are isolated per specialist (coverage note); only an
        orchestrator-level error (manifest, persistence, ...) fails the session.
        """
        try:
            session = self._store.get(session_id)
            await self._run(session)
        except Exception as exc:  # noqa: BLE001 — the session absorbs the error
            self._store.fail(session_id, f"{type(exc).__name__}: {exc}")

    # -- lifecycle -----------------------------------------------------------

    async def _run(self, session: Session) -> None:
        # 1. Intake / manifest
        self._store.transition(session, SessionState.MANIFEST)
        session.manifest = await self._manifest_builder.build(session.project_path)
        self._store.save(session)

        # 2–3. Assignment + filing: concurrent, exception-isolated dispatch
        self._store.transition(session, SessionState.REVIEWING)
        session.progress = {
            "specialists_total": len(self._configs),
            "specialists_completed": 0,
            "findings_accepted": 0,
            "findings_rejected": 0,
        }
        self._store.save(session)

        results = await asyncio.gather(
            *(self._run_specialist(config, session) for config in self._configs)
        )

        accepted: list[dict] = []
        rejected: list[dict] = []
        coverage_notes: list[dict] = []
        for config, findings, error in results:
            if error is not None:
                # A crashed specialist is a coverage gap, never a crashed session.
                coverage_notes.append(
                    {
                        "agent": config.name,
                        "note": "scope not covered",
                        "reason": error,
                    }
                )
                continue
            for finding in findings:
                errors = validate_finding(finding)
                if errors:
                    # NEGOTIATION_PROTOCOL.md §1: rejected at the boundary; counted
                    # as an uncited claim (feeds the hallucination-rate metric).
                    rejected.append(
                        {"agent": config.name, "finding": finding, "errors": errors}
                    )
                else:
                    accepted.append(finding)

        session.coverage_notes = coverage_notes
        session.progress["findings_accepted"] = len(accepted)
        session.progress["findings_rejected"] = len(rejected)
        self._store.save(session)

        # 4. Negotiation — NEGOTIATION_PROTOCOL.md §2–§4
        self._store.transition(session, SessionState.NEGOTIATING)
        debates = await self._negotiate(session, accepted)

        # 5. Sign-off
        review = self._assemble_review(session, accepted, rejected, debates)
        self._store.write_review(session.id, review)
        self._store.transition(session, SessionState.SIGNED)

    async def _run_specialist(
        self, config: AgentConfig, session: Session
    ) -> tuple[AgentConfig, list[dict] | None, str | None]:
        """Run one specialist; exceptions become data, never propagate."""
        try:
            findings = await self._runner.run(
                config=config,
                session_id=session.id,
                project_path=session.project_path,
                manifest=session.manifest or {},
            )
            return config, findings, None
        except Exception as exc:  # noqa: BLE001 — isolation is the point
            return config, None, f"{type(exc).__name__}: {exc}"
        finally:
            session.progress["specialists_completed"] = (
                session.progress.get("specialists_completed", 0) + 1
            )
            self._store.save(session)

    # -- negotiation: §2 conflict detection ---------------------------------------

    def detect_conflicts(self, findings: list[dict]) -> list[tuple[dict, dict]]:
        """Deterministic overlap detection — NEGOTIATION_PROTOCOL.md §2, no LLM.

        Two findings *potentially* conflict when they come from different agents
        and overlap in ``affected_nets`` or ``affected_components``. Whether their
        recommendations are actually incompatible is decided by the single
        batched Moderator classification pass (``classify_conflicts``).
        """
        pairs: list[tuple[dict, dict]] = []
        for i, a in enumerate(findings):
            for b in findings[i + 1 :]:
                if a.get("agent") == b.get("agent"):
                    continue
                overlap = _overlap(a, b)
                if overlap["nets"] or overlap["components"]:
                    pairs.append((a, b))
        return pairs

    async def classify_conflicts(
        self, session: Session, pairs: list[tuple[dict, dict]]
    ) -> list[tuple[dict, dict]]:
        """§2 classification: ONE batched Moderator model call for all pairs.

        Returns the subset of ``pairs`` whose recommendations are incompatible.
        A malformed classification reply degrades to "no conflicts" with a
        coverage note — the session still signs.
        """
        if not pairs:
            return []
        payload = [
            {
                "pair_id": idx,
                "overlap": _overlap(a, b),
                "finding_a": _finding_digest(a),
                "finding_b": _finding_digest(b),
            }
            for idx, (a, b) in enumerate(pairs)
        ]
        messages = [
            {
                "role": "system",
                "content": moderator_prompt() + "\n\n" + _CLASSIFICATION_INSTRUCTIONS,
            },
            {
                "role": "user",
                "content": "Overlapping finding pairs:\n"
                + json.dumps(payload, indent=2),
            },
        ]
        raw = await self._model_client.chat(
            agent=MODERATOR_AGENT,
            model=moderator_model(),
            messages=messages,
            response_format={"type": "json_object"},
        )
        try:
            rows = _parse_json_object(raw)["classifications"]
            if not isinstance(rows, list):
                raise ValueError("classifications is not an array")
        except Exception as exc:  # noqa: BLE001 — degrade, never crash the session
            session.coverage_notes.append(
                {
                    "agent": MODERATOR_AGENT,
                    "note": "conflict classification failed",
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )
            self._store.save(session)
            return []
        verdicts: dict[int, bool] = {}
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("pair_id"), int):
                verdicts[row["pair_id"]] = bool(row.get("compatible", True))
        # Unclassified pairs default to compatible (no debate on missing data).
        return [pair for idx, pair in enumerate(pairs) if verdicts.get(idx) is False]

    async def _negotiate(self, session: Session, accepted: list[dict]) -> list[dict]:
        """§2–§4 for the whole session; returns the debate records for review.json."""
        overlaps = self.detect_conflicts(accepted)
        session.progress.update(
            {
                "overlapping_pairs": len(overlaps),
                "conflicts_detected": 0,
                "debates_total": 0,
                "debates_completed": 0,
                "debate_turns_completed": 0,
            }
        )
        self._store.save(session)

        conflicts = await self.classify_conflicts(session, overlaps)

        # §2: contested status + conflicts_with on both sides of every conflict.
        for a, b in conflicts:
            for finding, other in ((a, b), (b, a)):
                finding["status"] = "contested"
                conflicts_with = finding.setdefault("conflicts_with", [])
                if other["id"] not in conflicts_with:
                    conflicts_with.append(other["id"])
        session.progress["conflicts_detected"] = len(conflicts)
        session.progress["debates_total"] = len(conflicts)
        session.progress["findings_contested"] = len(
            {f["id"] for pair in conflicts for f in pair}
        )
        self._store.save(session)

        debates: list[dict] = []
        for a, b in conflicts:
            if a.get("ruling") or b.get("ruling"):
                # A finding can sit in several overlapping conflicts; once ruled,
                # it is not re-litigated. The pair is noted and skipped.
                session.coverage_notes.append(
                    {
                        "agent": MODERATOR_AGENT,
                        "note": "conflict skipped",
                        "reason": (
                            f"{a['id']} vs {b['id']}: one side already ruled "
                            "in an earlier debate this session"
                        ),
                    }
                )
            else:
                debates.append(await self.run_debate(session, (a, b)))
            session.progress["debates_completed"] += 1
            self._store.save(session)
        return debates

    # -- negotiation: §3 bounded debate --------------------------------------------

    async def run_debate(self, session: Session, conflict: tuple[dict, dict]) -> dict:
        """Bounded debate — NEGOTIATION_PROTOCOL.md §3, ends with a §4 ruling.

        At most ``MAX_DEBATE_ROUNDS`` (= 2, hard limit) rounds. Each round, each
        side submits a ≤150-word position (truncated) and may request exactly
        ``EXTRA_TOOL_CALLS_PER_SIDE_PER_ROUND`` (= 1) extra tool call, executed
        via the injected ToolLayer and recorded as ``new_evidence_id``. A side
        may concede early; per architect ruling 2A a concession still produces a
        standard ruling block. The transcript lands on both findings' ``debate``
        arrays and in review.json (demo material).
        """
        a, b = conflict
        transcript: list[dict] = []
        valid_evidence_ids: set[str] = set(_evidence_ids(a)) | set(_evidence_ids(b))
        conceded_by: dict | None = None
        conceded_round = 0

        for round_no in range(1, MAX_DEBATE_ROUNDS + 1):
            for finding, opponent in ((a, b), (b, a)):
                entry = await self._debate_turn(
                    finding, opponent, round_no, transcript
                )
                transcript.append(entry)
                if entry.get("new_evidence_id"):
                    valid_evidence_ids.add(entry["new_evidence_id"])
                session.progress["debate_turns_completed"] = (
                    session.progress.get("debate_turns_completed", 0) + 1
                )
                self._store.save(session)
                if entry.get("conceded"):
                    conceded_by = finding
                    conceded_round = round_no
                    break
            if conceded_by is not None:
                break

        a["debate"] = list(transcript)
        b["debate"] = list(transcript)

        if conceded_by is not None:
            # Architect ruling 2A: a concession still gets a standard ruling
            # block (decision + rationale + cited evidence), written
            # deterministically by the orchestrator to preserve history.
            winner = b if conceded_by is a else a
            loser = conceded_by
            cited = _evidence_ids(winner)
            rationale = (
                f"{loser['agent']} conceded in round {conceded_round}; "
                f"{winner['id']} is upheld on its cited evidence."
            )
            winner["ruling"] = {
                "decision": "upheld",
                "rationale": rationale,
                "cited_evidence_ids": cited,
            }
            winner["status"] = "upheld"
            loser["ruling"] = {
                "decision": "overruled",
                "rationale": rationale,
                "cited_evidence_ids": cited,
            }
            loser["status"] = "overruled"
            ruling_summary = {
                "decision": "upheld",
                "upheld_finding_id": winner["id"],
                "rationale": rationale,
                "cited_evidence_ids": cited,
                "by_concession": True,
            }
        else:
            ruling_summary = await self.rule_on_conflict(
                session, conflict, transcript, valid_evidence_ids=valid_evidence_ids
            )
            self._apply_ruling(a, b, ruling_summary)

        self._store.save(session)
        return {
            "conflict": [a["id"], b["id"]],
            "transcript": transcript,
            "ruling": ruling_summary,
        }

    async def _debate_turn(
        self, finding: dict, opponent: dict, round_no: int, transcript: list[dict]
    ) -> dict:
        """One side's turn: position (word-capped) + optional single tool call."""
        agent = finding["agent"]
        messages = [
            {
                "role": "system",
                "content": _DEBATE_SYSTEM_TEMPLATE.format(
                    agent=agent, cap=POSITION_WORD_CAP
                ),
            },
            {
                "role": "user",
                "content": "Debate state:\n"
                + json.dumps(
                    {
                        "debate_round": round_no,
                        "max_rounds": MAX_DEBATE_ROUNDS,
                        "your_finding": finding,
                        "opposing_finding": opponent,
                        "transcript_so_far": transcript,
                    },
                    indent=2,
                ),
            },
        ]
        raw = await self._model_client.chat(
            agent=agent,
            model=self._model_for(agent),
            messages=messages,
            response_format={"type": "json_object"},
        )
        try:
            reply = _parse_json_object(raw)
        except Exception:  # noqa: BLE001 — a non-JSON reply becomes the position
            reply = {"position": raw, "concede": False, "tool_request": None}

        position = _truncate_words(
            str(reply.get("position") or "").strip() or "(no position submitted)"
        )
        entry: dict = {
            "round": round_no,
            "agent": agent,
            "position": position,
            "new_evidence_id": None,
        }
        if reply.get("concede"):
            entry["conceded"] = True
            return entry

        tool_request = reply.get("tool_request")
        if isinstance(tool_request, dict) and tool_request.get("tool"):
            # §3: exactly one extra tool call per side per round — enforced by
            # construction (one turn, one optional request).
            if self._tool_layer is None:
                entry["tool_error"] = "tool layer not wired; request not executed"
            else:
                try:
                    record = await self._tool_layer.call_tool(
                        agent=agent,
                        tool=str(tool_request["tool"]),
                        arguments=dict(tool_request.get("arguments") or {}),
                    )
                    entry["new_evidence_id"] = record.evidence_id
                    entry["tool"] = record.tool
                except Exception as exc:  # noqa: BLE001 — a failed call is data
                    entry["tool_error"] = f"{type(exc).__name__}: {exc}"
        return entry

    def _model_for(self, agent: str) -> str:
        for config in self._configs:
            if config.name == agent:
                return config.model
        return DEFAULT_DEBATE_MODEL

    # -- negotiation: §4 ruling ------------------------------------------------------

    async def rule_on_conflict(
        self,
        session: Session,
        conflict: tuple[dict, dict],
        debate: list[dict],
        *,
        valid_evidence_ids: set[str] | None = None,
    ) -> dict:
        """Evidence-weighted ruling — NEGOTIATION_PROTOCOL.md §4.

        The Moderator model decides upheld/merged and MUST cite evidence ids that
        exist in the session (finding evidence + debate tool-call evidence). An
        invalid ruling is retried once with the validation errors; a second
        failure falls back to a deterministic "upheld both, flagged unresolved"
        outcome (coverage note) so the session still signs.
        """
        a, b = conflict
        if valid_evidence_ids is None:
            valid_evidence_ids = set(_evidence_ids(a)) | set(_evidence_ids(b))
            valid_evidence_ids.update(
                e["new_evidence_id"] for e in debate if e.get("new_evidence_id")
            )
        valid = set(valid_evidence_ids)

        messages = [
            {
                "role": "system",
                "content": moderator_prompt() + "\n\n" + _RULING_INSTRUCTIONS,
            },
            {
                "role": "user",
                "content": "Contested conflict:\n"
                + json.dumps(
                    {
                        "finding_a": a,
                        "finding_b": b,
                        "debate_transcript": debate,
                        "valid_evidence_ids": sorted(valid),
                    },
                    indent=2,
                ),
            },
        ]

        errors: list[str] = []
        for _attempt in range(1 + MAX_VALIDATION_RETRIES):
            raw = await self._model_client.chat(
                agent=MODERATOR_AGENT,
                model=moderator_model(),
                messages=messages,
                response_format={"type": "json_object"},
            )
            ruling, errors = self._validate_ruling(raw, a, b, valid)
            if ruling is not None:
                return ruling
            messages = messages + [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": "Your ruling was invalid: "
                    + "; ".join(errors)
                    + ". Reply again with ONLY a corrected JSON object of the "
                    "required shape.",
                },
            ]

        # Deterministic fallback: upheld both, flagged unresolved (session signs).
        session.coverage_notes.append(
            {
                "agent": MODERATOR_AGENT,
                "note": "conflict unresolved — both findings upheld",
                "reason": f"{a['id']} vs {b['id']}: ruling invalid after retry: "
                + "; ".join(errors),
            }
        )
        self._store.save(session)
        return {
            "decision": "upheld",
            "upheld_finding_id": None,
            "rationale": (
                "Moderator ruling was invalid after one retry; both findings are "
                "upheld and the conflict is flagged unresolved."
            ),
            "cited_evidence_ids": sorted(valid),
            "unresolved": True,
        }

    def _validate_ruling(
        self, raw: str, a: dict, b: dict, valid: set[str]
    ) -> tuple[dict | None, list[str]]:
        """Validate one ruling reply. Returns (ruling, []) or (None, errors)."""
        try:
            obj = _parse_json_object(raw)
        except Exception as exc:  # noqa: BLE001
            return None, [f"reply is not a JSON object: {exc}"]

        errors: list[str] = []
        decision = obj.get("decision")
        if decision not in ("upheld", "overruled", "merged"):
            errors.append(
                "decision must be one of 'upheld', 'overruled', 'merged' "
                f"(got {decision!r})"
            )
        rationale = obj.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            errors.append("rationale must be a non-empty string")
        cited = obj.get("cited_evidence_ids")
        if not isinstance(cited, list) or not cited:
            errors.append(
                "cited_evidence_ids must be a non-empty array — a ruling citing "
                "no evidence is invalid (NEGOTIATION_PROTOCOL.md §4)"
            )
        else:
            unknown = sorted(str(e) for e in cited if e not in valid)
            if unknown:
                errors.append(
                    f"cited_evidence_ids reference unknown evidence {unknown}; "
                    f"valid ids in this session: {sorted(valid)}"
                )
        winner_id = obj.get("upheld_finding_id")
        if decision in ("upheld", "overruled") and winner_id not in (a["id"], b["id"]):
            errors.append(
                "upheld_finding_id must be one of "
                f"{[a['id'], b['id']]} when decision is not 'merged' "
                f"(got {winner_id!r})"
            )
        if errors:
            return None, errors

        ruling = {
            # 'overruled' from the model is normalized: it names a winner either way.
            "decision": "merged" if decision == "merged" else "upheld",
            "upheld_finding_id": winner_id if decision != "merged" else None,
            "rationale": rationale.strip(),
            "cited_evidence_ids": [str(e) for e in cited],
        }
        merged_rec = obj.get("merged_recommendation")
        if decision == "merged" and isinstance(merged_rec, str) and merged_rec.strip():
            ruling["merged_recommendation"] = merged_rec.strip()
        return ruling, []

    def _apply_ruling(self, a: dict, b: dict, summary: dict) -> None:
        """Write per-finding ruling blocks + statuses from a ruling summary."""
        rationale = summary["rationale"]
        cited = summary["cited_evidence_ids"]
        if summary.get("unresolved"):
            # Fallback: upheld both, flagged unresolved. Each finding cites its
            # own evidence so the ruling block stays schema-valid and grounded.
            for finding in (a, b):
                finding["ruling"] = {
                    "decision": "upheld",
                    "rationale": rationale,
                    "cited_evidence_ids": _evidence_ids(finding),
                    "unresolved": True,
                }
                finding["status"] = "upheld"
            return
        if summary["decision"] == "merged":
            for finding in (a, b):
                finding["ruling"] = {
                    "decision": "merged",
                    "rationale": rationale,
                    "cited_evidence_ids": list(cited),
                    **(
                        {"merged_recommendation": summary["merged_recommendation"]}
                        if "merged_recommendation" in summary
                        else {}
                    ),
                }
                finding["status"] = "merged"
            return
        winner = a if summary["upheld_finding_id"] == a["id"] else b
        loser = b if winner is a else a
        winner["ruling"] = {
            "decision": "upheld",
            "rationale": rationale,
            "cited_evidence_ids": list(cited),
        }
        winner["status"] = "upheld"
        loser["ruling"] = {
            "decision": "overruled",
            "rationale": rationale,
            "cited_evidence_ids": list(cited),
        }
        loser["status"] = "overruled"

    # -- review assembly -----------------------------------------------------------

    def _assemble_review(
        self,
        session: Session,
        accepted: list[dict],
        rejected: list[dict],
        debates: list[dict] | None = None,
    ) -> dict:
        """The signed review — NEGOTIATION_PROTOCOL.md §5.

        Consumed by report/ (Antigravity) and benchmark/. Root additions per
        architect rulings (report/QUESTIONS.md §3): ``created_at`` / ``signed_at``
        (2B) and the pass-through ``render`` metadata slot (1A) when the manifest
        provides it. The per-finding shape stays frozen finding.schema.json v1.
        """
        review = {
            "session_id": session.id,
            "project_path": session.project_path,
            "finding_schema": "docs/schemas/finding.schema.json",
            "protocol": {
                "version": 1,
                "max_debate_rounds": MAX_DEBATE_ROUNDS,
                "extra_tool_calls_per_side_per_round": EXTRA_TOOL_CALLS_PER_SIDE_PER_ROUND,
            },
            "findings": accepted,
            "rulings": [
                {
                    "finding_id": finding["id"],
                    "conflicts_with": finding.get("conflicts_with", []),
                    **finding["ruling"],
                }
                for finding in accepted
                if finding.get("ruling")
            ],
            #: §4 "the debate transcript is preserved for the report and the demo
            #: video" — one record per conflict: transcript + ruling summary.
            "debates": debates or [],
            "rejected_findings": rejected,  # uncited claims → hallucination metric
            "coverage_notes": session.coverage_notes,
            "token_accounting": self._model_client.ledger.snapshot(),
            "created_at": session.created_at,  # architect ruling 2B
            "signed_at": _utcnow(),  # architect ruling 2B
        }
        render = (session.manifest or {}).get("render")
        if render is not None:
            review["render"] = render  # architect ruling 1A pass-through
        return review
