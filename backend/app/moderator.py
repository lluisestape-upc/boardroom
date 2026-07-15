"""The Moderator: drives a review session end to end.

Day 1 scope (TASKS.md):
    dispatch N specialists CONCURRENTLY with per-specialist exception isolation,
    schema-validate their findings at the boundary, and assemble a draft
    review.json (findings + coverage_notes + token_accounting).

Day 2 seams (clearly marked, do not remove):
    - ``detect_conflicts``  — NEGOTIATION_PROTOCOL.md §2 (deterministic, no LLM)
    - ``run_debate``        — NEGOTIATION_PROTOCOL.md §3 (bounded, MAX_DEBATE_ROUNDS)
    - ``rule_on_conflict``  — NEGOTIATION_PROTOCOL.md §4 (evidence-cited ruling)
    - registry swap         — interfaces.load_agent_configs()
    - real MCP wiring       — interfaces.ToolLayer / ManifestBuilder
"""

from __future__ import annotations

import asyncio
import json
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

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "schemas" / "finding.schema.json"
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
    """Assign → collect → (negotiate: Day 2) → sign."""

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
        #: Day 2: debate-round extra tool calls go through this (allowlist-enforced).
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
                    # Day 2 seam: give the specialist MAX_VALIDATION_RETRIES retry.
                    rejected.append(
                        {"agent": config.name, "finding": finding, "errors": errors}
                    )
                else:
                    accepted.append(finding)

        session.coverage_notes = coverage_notes
        session.progress["findings_accepted"] = len(accepted)
        session.progress["findings_rejected"] = len(rejected)
        self._store.save(session)

        # 4. Negotiation — Day 2. Day 1 passes straight through the state.
        self._store.transition(session, SessionState.NEGOTIATING)
        conflicts = self.detect_conflicts(accepted)
        for conflict in conflicts:  # pragma: no cover — Day 1: always empty
            await self.run_debate(session, conflict)

        # 5. Sign-off
        review = self._assemble_review(session, accepted, rejected)
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

    # -- Day 2 seams -------------------------------------------------------------

    def detect_conflicts(self, findings: list[dict]) -> list[tuple[dict, dict]]:
        """Deterministic conflict detection — NEGOTIATION_PROTOCOL.md §2.

        Day 2: two findings conflict when they overlap in ``affected_nets`` or
        ``affected_components`` AND a single cheap Moderator classification pass
        marks their recommendations incompatible. Conflicting findings get
        ``status: contested`` and populate ``conflicts_with``.

        Day 1: no negotiation — returns no conflicts.
        """
        return []

    async def run_debate(self, session: Session, conflict: tuple[dict, dict]) -> dict:
        """Bounded debate — NEGOTIATION_PROTOCOL.md §3.

        Day 2: at most ``MAX_DEBATE_ROUNDS`` (= 2, hard limit) rounds; each round
        each side submits a ≤150-word position and may request exactly
        ``EXTRA_TOOL_CALLS_PER_SIDE_PER_ROUND`` (= 1) additional tool call via
        ``self._tool_layer`` (allowlist-enforced). Every round is logged to the
        session — the transcript is demo material. Ends with
        ``rule_on_conflict``.
        """
        raise NotImplementedError(
            "Day 2: bounded debate per NEGOTIATION_PROTOCOL.md §3 "
            f"(max {MAX_DEBATE_ROUNDS} rounds)"
        )

    async def rule_on_conflict(
        self, session: Session, conflict: tuple[dict, dict], debate: list[dict]
    ) -> dict:
        """Evidence-weighted ruling — NEGOTIATION_PROTOCOL.md §4.

        Day 2: Moderator (qwen3-max via ``self._model_client``) decides
        upheld / overruled / merged and MUST cite the specific ``evidence_id``s
        that decided it; a ruling citing no evidence is invalid and retried
        ``MAX_VALIDATION_RETRIES`` (= 1) time, then the conflict is escalated to
        a coverage note. Rationale stored verbatim.
        """
        raise NotImplementedError(
            "Day 2: evidence-cited ruling per NEGOTIATION_PROTOCOL.md §4"
        )

    # -- review assembly -----------------------------------------------------------

    def _assemble_review(
        self, session: Session, accepted: list[dict], rejected: list[dict]
    ) -> dict:
        """The signed review — NEGOTIATION_PROTOCOL.md §5.

        Consumed by report/ (Antigravity) and benchmark/. ``rulings`` stays empty
        until Day 2 negotiation lands.
        """
        return {
            "session_id": session.id,
            "project_path": session.project_path,
            "finding_schema": "docs/schemas/finding.schema.json",
            "protocol": {
                "version": 1,
                "max_debate_rounds": MAX_DEBATE_ROUNDS,
                "extra_tool_calls_per_side_per_round": EXTRA_TOOL_CALLS_PER_SIDE_PER_ROUND,
            },
            "findings": accepted,
            "rulings": [],  # Day 2: one entry per contested finding
            "rejected_findings": rejected,  # uncited claims → hallucination metric
            "coverage_notes": session.coverage_notes,
            "token_accounting": self._model_client.ledger.snapshot(),
            "signed_at": _utcnow(),
        }
