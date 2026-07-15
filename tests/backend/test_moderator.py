"""Moderator: concurrent dispatch, exception isolation, finding validation."""

import asyncio

import pytest

from backend.app.interfaces import AgentConfig
from backend.app.moderator import (
    MAX_DEBATE_ROUNDS,
    Moderator,
    validate_finding,
)
from backend.app.sessions import SessionState, SessionStore
from fakes import (
    TWO_SPECIALISTS,
    FakeManifestBuilder,
    FakeModelClient,
    FakeSpecialistRunner,
    make_finding,
)


@pytest.fixture
def store(tmp_path):
    return SessionStore(tmp_path / "sessions")


def make_moderator(store, runner, configs=TWO_SPECIALISTS):
    return Moderator(
        store=store,
        model_client=FakeModelClient(),
        specialist_runner=runner,
        agent_configs=configs,
        manifest_builder=FakeManifestBuilder(),
    )


def run(coro):
    return asyncio.run(coro)


# -- happy path -------------------------------------------------------------------


def test_review_signs_with_findings_from_both_specialists(store):
    runner = FakeSpecialistRunner(
        findings_by_agent={
            "connectivity_erc": [make_finding("ERC-001", "connectivity_erc")],
            "power_integrity": [make_finding("PI-001", "power_integrity")],
        }
    )
    moderator = make_moderator(store, runner)
    session = store.create("some/project")

    run(moderator.run_review(session.id))

    final = store.get(session.id)
    assert final.state is SessionState.SIGNED
    assert [h["to"] for h in final.history] == [
        "created", "manifest", "reviewing", "negotiating", "signed",
    ]
    review = store.read_review(session.id)
    assert {f["id"] for f in review["findings"]} == {"ERC-001", "PI-001"}
    assert review["coverage_notes"] == []
    assert review["rejected_findings"] == []
    assert review["token_accounting"]  # ledger snapshot present
    assert review["protocol"]["max_debate_rounds"] == MAX_DEBATE_ROUNDS == 2
    assert sorted(runner.ran) == ["connectivity_erc", "power_integrity"]


def test_specialists_run_concurrently(store):
    """Both specialists must be in flight at once (asyncio.gather, not serial)."""
    in_flight = 0
    max_in_flight = 0

    class ConcurrencyProbe:
        async def run(self, *, config, session_id, project_path, manifest):
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1
            return [make_finding(f"{config.name[:2].upper()}-001", config.name)]

    moderator = make_moderator(store, ConcurrencyProbe())
    session = store.create("p")
    run(moderator.run_review(session.id))

    assert max_in_flight == 2
    assert store.get(session.id).state is SessionState.SIGNED


# -- exception isolation ---------------------------------------------------------


def test_crashed_specialist_becomes_coverage_note_not_crashed_session(store):
    runner = FakeSpecialistRunner(
        findings_by_agent={"connectivity_erc": [make_finding("ERC-001", "connectivity_erc")]},
        crash_agents={"power_integrity"},
    )
    moderator = make_moderator(store, runner)
    session = store.create("p")

    run(moderator.run_review(session.id))

    final = store.get(session.id)
    assert final.state is SessionState.SIGNED  # session still signs
    review = store.read_review(session.id)
    assert [f["id"] for f in review["findings"]] == ["ERC-001"]
    assert len(review["coverage_notes"]) == 1
    note = review["coverage_notes"][0]
    assert note["agent"] == "power_integrity"
    assert note["note"] == "scope not covered"
    assert "exploded" in note["reason"]


def test_all_specialists_crashing_still_signs_with_empty_findings(store):
    runner = FakeSpecialistRunner(crash_agents={"connectivity_erc", "power_integrity"})
    moderator = make_moderator(store, runner)
    session = store.create("p")

    run(moderator.run_review(session.id))

    review = store.read_review(session.id)
    assert review["findings"] == []
    assert {n["agent"] for n in review["coverage_notes"]} == {
        "connectivity_erc", "power_integrity",
    }


def test_orchestrator_level_error_fails_session_gracefully(store):
    class BrokenManifestBuilder:
        async def build(self, project_path):
            raise FileNotFoundError("no such project")

    moderator = Moderator(
        store=store,
        model_client=FakeModelClient(),
        specialist_runner=FakeSpecialistRunner(),
        agent_configs=TWO_SPECIALISTS,
        manifest_builder=BrokenManifestBuilder(),
    )
    session = store.create("missing")
    run(moderator.run_review(session.id))  # must not raise

    final = store.get(session.id)
    assert final.state is SessionState.FAILED
    assert "no such project" in final.error


# -- finding validation at the boundary ------------------------------------------


def test_invalid_findings_are_rejected_not_signed_in(store):
    uncited = make_finding("PI-002", "power_integrity", evidence=[])  # minItems: 1
    bad_agent = make_finding("XX-001", "not_a_real_agent")
    valid = make_finding("PI-001", "power_integrity")
    runner = FakeSpecialistRunner(
        findings_by_agent={"power_integrity": [valid, uncited, bad_agent]}
    )
    moderator = make_moderator(
        store, runner, configs=[AgentConfig(name="power_integrity", model="fake")]
    )
    session = store.create("p")

    run(moderator.run_review(session.id))

    review = store.read_review(session.id)
    assert [f["id"] for f in review["findings"]] == ["PI-001"]
    rejected_ids = {r["finding"]["id"] for r in review["rejected_findings"]}
    assert rejected_ids == {"PI-002", "XX-001"}
    for rejected in review["rejected_findings"]:
        assert rejected["errors"]  # each rejection carries validator messages
    final = store.get(session.id)
    assert final.progress["findings_accepted"] == 1
    assert final.progress["findings_rejected"] == 2


def test_validate_finding_direct():
    assert validate_finding(make_finding("PI-001", "power_integrity")) == []
    errors = validate_finding({"id": "X"})
    assert errors  # missing required fields
    assert validate_finding("not even an object")
    # uncited claim: evidence is required non-empty
    assert any("evidence" in e for e in validate_finding(
        make_finding("PI-002", "power_integrity", evidence=[])
    ))


# -- Day 2 seams -----------------------------------------------------------------


def test_day2_seams_are_stubbed_and_bounded(store):
    moderator = make_moderator(store, FakeSpecialistRunner())
    assert moderator.detect_conflicts([make_finding("A-1", "power_integrity")]) == []
    session = store.create("p")
    with pytest.raises(NotImplementedError):
        run(moderator.run_debate(session, ({}, {})))
    assert MAX_DEBATE_ROUNDS == 2  # NEGOTIATION_PROTOCOL.md §3 hard limit
