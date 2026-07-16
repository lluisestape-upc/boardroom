"""Day 2 negotiation engine — NEGOTIATION_PROTOCOL.md §2–§5.

Covers: deterministic overlap detection, the single batched classification call,
the full 2-round debate with extra tool calls, early concession, ruling
validation retry + deterministic fallback, review-root timestamps / render
pass-through (architect rulings 1A/2B), and transcript persistence.
"""

import asyncio
import json

import pytest

from backend.app.interfaces import AgentConfig
from backend.app.moderator import (
    MAX_DEBATE_ROUNDS,
    POSITION_WORD_CAP,
    Moderator,
    moderator_model,
    validate_finding,
)
from backend.app.qwen_client import MockQwenClient
from backend.app.sessions import SessionState, SessionStore
from fakes import (
    FakeManifestBuilder,
    FakeSpecialistRunner,
    FakeToolLayer,
    make_finding,
)

CONFLICT_SPECIALISTS = [
    AgentConfig(name="signal_integrity", model="qwen-flash"),
    AgentConfig(name="dfm_layout", model="qwen3-vl-plus"),
]


@pytest.fixture
def store(tmp_path):
    return SessionStore(tmp_path / "sessions")


def run(coro):
    return asyncio.run(coro)


def make_moderator(store, runner, client, *, configs=CONFLICT_SPECIALISTS, tool_layer=None, manifest_builder=None):
    return Moderator(
        store=store,
        model_client=client,
        specialist_runner=runner,
        agent_configs=configs,
        manifest_builder=manifest_builder or FakeManifestBuilder(),
        tool_layer=tool_layer,
    )


def si_finding(**overrides):
    return make_finding(
        "SI-001",
        "signal_integrity",
        affected_nets=["USB_DP", "USB_DM"],
        recommendation="Reroute the diff pair over a stitched ground pour",
        **overrides,
    )


def dfm_finding(**overrides):
    return make_finding(
        "DFM-001",
        "dfm_layout",
        affected_nets=["USB_DP"],
        recommendation="Keep the existing pour; clearance and cost forbid restitching",
        **overrides,
    )


def conflict_runner():
    return FakeSpecialistRunner(
        findings_by_agent={
            "signal_integrity": [si_finding()],
            "dfm_layout": [dfm_finding()],
        }
    )


def incompatible_classification(pair_ids=(0,), compatible_ids=()):
    rows = [{"pair_id": i, "compatible": False, "reason": "pull opposite ways"} for i in pair_ids]
    rows += [{"pair_id": i, "compatible": True, "reason": "independent"} for i in compatible_ids]
    return json.dumps({"classifications": rows})


def debate_reply(position="The crosstalk margin is negative; rerouting is mandatory.", concede=False, tool=None):
    return json.dumps(
        {
            "position": position,
            "concede": concede,
            "tool_request": {"tool": tool, "arguments": {"net": "USB_DP"}} if tool else None,
        }
    )


def ruling_reply(winner="SI-001", cited=("ev-SI-001",), decision="upheld", **extra):
    return json.dumps(
        {
            "decision": decision,
            "upheld_finding_id": winner if decision != "merged" else None,
            "rationale": "Measured crosstalk outweighs the manufacturing cost argument.",
            "cited_evidence_ids": list(cited),
            **extra,
        }
    )


# -- §2 deterministic overlap detection --------------------------------------------


def test_overlap_detection_on_nets_and_components(store):
    moderator = make_moderator(store, FakeSpecialistRunner(), MockQwenClient())
    a = make_finding("SI-001", "signal_integrity", affected_nets=["USB_DP"])
    b = make_finding("DFM-001", "dfm_layout", affected_nets=["USB_DP", "GND"])
    c = make_finding("PI-001", "power_integrity", affected_components=["U3"])
    d = make_finding("ERC-001", "connectivity_erc", affected_components=["U3", "C12"])
    e = make_finding("FW-001", "firmware_bringup", affected_nets=["I2C_SDA"])

    pairs = moderator.detect_conflicts([a, b, c, d, e])

    assert [(x["id"], y["id"]) for x, y in pairs] == [
        ("SI-001", "DFM-001"),  # net overlap
        ("PI-001", "ERC-001"),  # component overlap
    ]


def test_same_agent_findings_never_conflict(store):
    moderator = make_moderator(store, FakeSpecialistRunner(), MockQwenClient())
    a = make_finding("SI-001", "signal_integrity", affected_nets=["USB_DP"])
    b = make_finding("SI-002", "signal_integrity", affected_nets=["USB_DP"])
    assert moderator.detect_conflicts([a, b]) == []


def test_no_overlap_means_no_model_call(store):
    client = MockQwenClient()  # raises if any un-registered agent is called
    runner = FakeSpecialistRunner(
        findings_by_agent={
            "signal_integrity": [make_finding("SI-001", "signal_integrity", affected_nets=["A"])],
            "dfm_layout": [make_finding("DFM-001", "dfm_layout", affected_nets=["B"])],
        }
    )
    moderator = make_moderator(store, runner, client)
    session = store.create("p")
    run(moderator.run_review(session.id))
    assert store.get(session.id).state is SessionState.SIGNED
    assert client.calls == []


# -- §2 classification: one batched call -------------------------------------------


def test_classification_is_one_batched_call_for_all_pairs(store):
    a = make_finding("SI-001", "signal_integrity", affected_nets=["N1"])
    b = make_finding("DFM-001", "dfm_layout", affected_nets=["N1"])
    c = make_finding("PI-001", "power_integrity", affected_nets=["N1"])
    runner = FakeSpecialistRunner(
        findings_by_agent={
            "signal_integrity": [a],
            "dfm_layout": [b],
            "power_integrity": [c],
        }
    )
    client = MockQwenClient().register(
        "moderator", incompatible_classification(pair_ids=(), compatible_ids=(0, 1, 2))
    )
    configs = CONFLICT_SPECIALISTS + [AgentConfig(name="power_integrity", model="qwen-flash")]
    moderator = make_moderator(store, runner, client, configs=configs)
    session = store.create("p")

    run(moderator.run_review(session.id))

    # Three overlapping pairs, exactly ONE classification call.
    moderator_calls = client.calls_for("moderator")
    assert len(moderator_calls) == 1
    assert moderator_calls[0]["model"] == moderator_model()
    user_content = moderator_calls[0]["messages"][1]["content"]
    for pair_id in (0, 1, 2):
        assert f'"pair_id": {pair_id}' in user_content

    # All compatible → nothing contested, no debates, no rulings.
    review = store.read_review(session.id)
    assert {f["status"] for f in review["findings"]} == {"open"}
    assert review["rulings"] == []
    assert review["debates"] == []
    final = store.get(session.id)
    assert final.progress["overlapping_pairs"] == 3
    assert final.progress["conflicts_detected"] == 0


def test_malformed_classification_degrades_to_no_conflicts(store):
    client = MockQwenClient().register("moderator", "not json at all")
    moderator = make_moderator(store, conflict_runner(), client)
    session = store.create("p")
    run(moderator.run_review(session.id))

    final = store.get(session.id)
    assert final.state is SessionState.SIGNED
    review = store.read_review(session.id)
    assert review["debates"] == []
    assert any(
        n["note"] == "conflict classification failed" for n in review["coverage_notes"]
    )


# -- §3 full bounded debate with extra tool calls -----------------------------------


def test_full_two_round_debate_with_extra_tool_calls(store):
    client = (
        MockQwenClient()
        .register(
            "moderator",
            [
                incompatible_classification(pair_ids=(0,)),
                ruling_reply(winner="SI-001", cited=("ev-SI-001", "ev-debate-1")),
            ],
        )
        .register(
            "signal_integrity",
            [
                debate_reply(tool="analyze_pcb_signal_integrity"),
                debate_reply(position="Round-2 measurements confirm the violation.", tool="find_tracks_by_net"),
            ],
        )
        .register(
            "dfm_layout",
            [
                debate_reply(position="Restitching violates clearance.", tool="run_drc"),
                debate_reply(position="DRC confirms clearance risk.", tool="get_drc_violations"),
            ],
        )
    )
    tool_layer = FakeToolLayer()
    moderator = make_moderator(store, conflict_runner(), client, tool_layer=tool_layer)
    session = store.create("p")

    run(moderator.run_review(session.id))

    final = store.get(session.id)
    assert final.state is SessionState.SIGNED

    # Exactly one extra tool call per side per round: 2 rounds x 2 sides = 4.
    assert len(tool_layer.calls) == 4
    assert [c["agent"] for c in tool_layer.calls] == [
        "signal_integrity", "dfm_layout", "signal_integrity", "dfm_layout",
    ]

    # Two debate turns per side (bounded at MAX_DEBATE_ROUNDS).
    assert len(client.calls_for("signal_integrity")) == MAX_DEBATE_ROUNDS
    assert len(client.calls_for("dfm_layout")) == MAX_DEBATE_ROUNDS
    # Moderator: 1 classification + 1 ruling.
    assert len(client.calls_for("moderator")) == 2

    review = store.read_review(session.id)
    by_id = {f["id"]: f for f in review["findings"]}
    si, dfm = by_id["SI-001"], by_id["DFM-001"]

    # §2 outcome recorded on both findings.
    assert si["conflicts_with"] == ["DFM-001"]
    assert dfm["conflicts_with"] == ["SI-001"]

    # Transcript on both findings: rounds 1,1,2,2 with attached evidence ids.
    for finding in (si, dfm):
        assert [e["round"] for e in finding["debate"]] == [1, 1, 2, 2]
        assert [e["new_evidence_id"] for e in finding["debate"]] == [
            "ev-debate-1", "ev-debate-2", "ev-debate-3", "ev-debate-4",
        ]

    # §4 ruling applied: SI upheld, DFM overruled, evidence cited.
    assert si["status"] == "upheld" and si["ruling"]["decision"] == "upheld"
    assert dfm["status"] == "overruled" and dfm["ruling"]["decision"] == "overruled"
    assert si["ruling"]["cited_evidence_ids"] == ["ev-SI-001", "ev-debate-1"]

    # Everything still validates against the frozen schema.
    for finding in review["findings"]:
        assert validate_finding(finding) == []

    # §5: transcript persisted in review.json (demo material) + rulings summary.
    assert len(review["debates"]) == 1
    debate = review["debates"][0]
    assert debate["conflict"] == ["SI-001", "DFM-001"]
    assert len(debate["transcript"]) == 4
    assert debate["ruling"]["upheld_finding_id"] == "SI-001"
    assert {r["finding_id"] for r in review["rulings"]} == {"SI-001", "DFM-001"}

    # Progress counters surfaced for GET /sessions/{id}.
    assert final.progress["overlapping_pairs"] == 1
    assert final.progress["conflicts_detected"] == 1
    assert final.progress["findings_contested"] == 2
    assert final.progress["debates_total"] == 1
    assert final.progress["debates_completed"] == 1
    assert final.progress["debate_turns_completed"] == 4


def test_tool_requests_without_tool_layer_are_recorded_not_fatal(store):
    client = (
        MockQwenClient()
        .register(
            "moderator",
            [incompatible_classification(pair_ids=(0,)), ruling_reply(winner="SI-001")],
        )
        .register("signal_integrity", debate_reply(tool="analyze_pcb_signal_integrity"))
        .register("dfm_layout", debate_reply(position="Objection stands.", tool="run_drc"))
    )
    moderator = make_moderator(store, conflict_runner(), client, tool_layer=None)
    session = store.create("p")
    run(moderator.run_review(session.id))

    review = store.read_review(session.id)
    transcript = review["debates"][0]["transcript"]
    assert all(e["new_evidence_id"] is None for e in transcript)
    assert all("not wired" in e["tool_error"] for e in transcript)
    assert store.get(session.id).state is SessionState.SIGNED


# -- §3 early concession -------------------------------------------------------------


def test_early_concession_short_circuits_and_still_gets_a_standard_ruling(store):
    long_position = " ".join(f"w{i}" for i in range(POSITION_WORD_CAP + 50))
    client = (
        MockQwenClient()
        .register("moderator", incompatible_classification(pair_ids=(0,)))
        .register("signal_integrity", debate_reply(position=long_position))
        .register("dfm_layout", debate_reply(position="Conceding: SI evidence is stronger.", concede=True))
    )
    tool_layer = FakeToolLayer()
    moderator = make_moderator(store, conflict_runner(), client, tool_layer=tool_layer)
    session = store.create("p")

    run(moderator.run_review(session.id))

    # Concession in round 1 → no round 2, no ruling model call (architect 2A:
    # the orchestrator writes the standard ruling block deterministically).
    assert len(client.calls_for("moderator")) == 1  # classification only
    assert len(client.calls_for("signal_integrity")) == 1
    assert len(client.calls_for("dfm_layout")) == 1

    review = store.read_review(session.id)
    by_id = {f["id"]: f for f in review["findings"]}
    si, dfm = by_id["SI-001"], by_id["DFM-001"]

    transcript = review["debates"][0]["transcript"]
    assert len(transcript) == 2
    assert transcript[1]["conceded"] is True
    # §3 word cap: truncated, not failed.
    assert len(transcript[0]["position"].split()) == POSITION_WORD_CAP

    assert si["status"] == "upheld"
    assert dfm["status"] == "overruled"
    for finding in (si, dfm):
        assert "conceded in round 1" in finding["ruling"]["rationale"]
        assert finding["ruling"]["cited_evidence_ids"] == ["ev-SI-001"]
        assert validate_finding(finding) == []
    assert review["debates"][0]["ruling"]["by_concession"] is True


# -- §4 ruling validation retry + fallback -------------------------------------------


def bare_debate_client():
    """Both sides argue, never concede, never request tools."""
    return (
        MockQwenClient()
        .register("signal_integrity", debate_reply())
        .register("dfm_layout", debate_reply(position="Cost and clearance forbid it."))
    )


def test_invalid_ruling_is_retried_with_validation_errors_then_succeeds(store):
    client = bare_debate_client().register(
        "moderator",
        [
            incompatible_classification(pair_ids=(0,)),
            json.dumps({"decision": "upheld", "rationale": "gut feeling", "cited_evidence_ids": []}),
            ruling_reply(winner="DFM-001", cited=("ev-DFM-001",)),
        ],
    )
    moderator = make_moderator(store, conflict_runner(), client)
    session = store.create("p")
    run(moderator.run_review(session.id))

    calls = client.calls_for("moderator")
    assert len(calls) == 3  # classification + invalid ruling + retry
    retry_messages = calls[2]["messages"]
    assert retry_messages[-1]["role"] == "user"
    assert "cited_evidence_ids must be a non-empty array" in retry_messages[-1]["content"]

    review = store.read_review(session.id)
    by_id = {f["id"]: f for f in review["findings"]}
    assert by_id["DFM-001"]["status"] == "upheld"
    assert by_id["SI-001"]["status"] == "overruled"
    assert store.get(session.id).state is SessionState.SIGNED


def test_ruling_invalid_twice_falls_back_to_upheld_both_unresolved(store):
    client = bare_debate_client().register(
        "moderator",
        [
            incompatible_classification(pair_ids=(0,)),
            json.dumps({"decision": "sideways", "rationale": "", "cited_evidence_ids": []}),
            ruling_reply(winner="SI-001", cited=("ev-does-not-exist",)),
        ],
    )
    moderator = make_moderator(store, conflict_runner(), client)
    session = store.create("p")
    run(moderator.run_review(session.id))

    final = store.get(session.id)
    assert final.state is SessionState.SIGNED  # the session still signs

    review = store.read_review(session.id)
    by_id = {f["id"]: f for f in review["findings"]}
    for fid in ("SI-001", "DFM-001"):
        finding = by_id[fid]
        assert finding["status"] == "upheld"
        assert finding["ruling"]["decision"] == "upheld"
        assert finding["ruling"]["unresolved"] is True
        assert finding["ruling"]["cited_evidence_ids"] == [f"ev-{fid}"]
        assert validate_finding(finding) == []
    assert review["debates"][0]["ruling"]["unresolved"] is True
    assert any(
        "unresolved" in n["note"] and "SI-001" in n["reason"]
        for n in review["coverage_notes"]
    )


def test_merged_ruling_marks_both_findings_merged(store):
    client = bare_debate_client().register(
        "moderator",
        [
            incompatible_classification(pair_ids=(0,)),
            ruling_reply(
                decision="merged",
                cited=("ev-SI-001", "ev-DFM-001"),
                merged_recommendation="Stitch the pour only under the diff pair.",
            ),
        ],
    )
    moderator = make_moderator(store, conflict_runner(), client)
    session = store.create("p")
    run(moderator.run_review(session.id))

    review = store.read_review(session.id)
    for finding in review["findings"]:
        assert finding["status"] == "merged"
        assert finding["ruling"]["decision"] == "merged"
        assert finding["ruling"]["merged_recommendation"].startswith("Stitch the pour")
        assert validate_finding(finding) == []


# -- review root additions (architect rulings 1A / 2B) --------------------------------


class RenderManifestBuilder:
    RENDER = {"image": "board_top.png", "width_px": 2400, "height_px": 1800, "dpi": 300}

    async def build(self, project_path: str) -> dict:
        return {"project_path": project_path, "kicad_files": [], "render": dict(self.RENDER)}


def test_review_root_timestamps_and_render_passthrough(store):
    runner = FakeSpecialistRunner(
        findings_by_agent={"signal_integrity": [make_finding("SI-001", "signal_integrity")]}
    )
    moderator = make_moderator(
        store, runner, MockQwenClient(), manifest_builder=RenderManifestBuilder()
    )
    session = store.create("p")
    run(moderator.run_review(session.id))

    review = store.read_review(session.id)
    assert review["created_at"] == store.get(session.id).created_at  # 2B
    assert review["signed_at"] >= review["created_at"]  # ISO 8601 sorts
    assert review["render"] == RenderManifestBuilder.RENDER  # 1A pass-through


def test_review_omits_render_when_manifest_has_none(store):
    runner = FakeSpecialistRunner(
        findings_by_agent={"signal_integrity": [make_finding("SI-001", "signal_integrity")]}
    )
    moderator = make_moderator(store, runner, MockQwenClient())
    session = store.create("p")
    run(moderator.run_review(session.id))
    review = store.read_review(session.id)
    assert "render" not in review
    assert review["created_at"] and review["signed_at"]
