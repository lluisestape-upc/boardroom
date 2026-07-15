"""Finding validation boundary (society/findings.py)."""

import json

from society.findings import RejectedFinding, parse_and_validate, rejection_report


def make_finding(**overrides) -> dict:
    finding = {
        "id": "ERC-001",
        "agent": "connectivity_erc",
        "claim": "I2C bus I2C0 has no pull-up resistors on SDA or SCL.",
        "severity": "critical",
        "evidence": [
            {
                "evidence_id": "ev-042",
                "tool": "trace_netlist_connection",
                "summary": "SDA/SCL connect U1 to U3 with no resistor to 3V3",
            }
        ],
        "affected_nets": ["I2C0_SDA", "I2C0_SCL"],
        "affected_components": ["U1", "U3"],
        "recommendation": "Add 4.7k pull-ups from SDA/SCL to 3V3 near U1.",
        "status": "open",
    }
    finding.update(overrides)
    return finding


def test_valid_finding_array_passes():
    raw = json.dumps([make_finding()])
    valid, rejected = parse_and_validate(raw)
    assert rejected == []
    assert len(valid) == 1
    assert valid[0]["id"] == "ERC-001"


def test_fenced_json_is_tolerated():
    raw = "```json\n" + json.dumps([make_finding()]) + "\n```"
    valid, rejected = parse_and_validate(raw)
    assert rejected == []
    assert len(valid) == 1


def test_bare_fence_without_language_tag_is_tolerated():
    raw = "```\n" + json.dumps([make_finding()]) + "\n```"
    valid, rejected = parse_and_validate(raw)
    assert rejected == []
    assert len(valid) == 1


def test_single_object_instead_of_array_is_tolerated():
    valid, rejected = parse_and_validate(json.dumps(make_finding()))
    assert rejected == []
    assert len(valid) == 1


def test_malformed_json_rejected_with_reason():
    valid, rejected = parse_and_validate("here are my findings: [{oops")
    assert valid == []
    assert len(rejected) == 1
    assert isinstance(rejected[0], RejectedFinding)
    assert "malformed JSON" in rejected[0].reasons[0]


def test_missing_evidence_rejected():
    raw = json.dumps([make_finding(evidence=[])])
    valid, rejected = parse_and_validate(raw)
    assert valid == []
    assert len(rejected) == 1
    assert any("evidence" in r for r in rejected[0].reasons)


def test_missing_required_field_rejected():
    finding = make_finding()
    del finding["recommendation"]
    valid, rejected = parse_and_validate(json.dumps([finding]))
    assert valid == []
    assert any("recommendation" in r for r in rejected[0].reasons)


def test_bad_severity_and_agent_enum_rejected():
    raw = json.dumps([make_finding(severity="catastrophic", agent="thermal")])
    valid, rejected = parse_and_validate(raw)
    assert valid == []
    reasons = " | ".join(rejected[0].reasons)
    assert "severity" in reasons
    assert "agent" in reasons


def test_unknown_evidence_id_rejected_when_cache_ids_given():
    raw = json.dumps([make_finding()])
    valid, rejected = parse_and_validate(raw, known_evidence_ids={"ev-001", "ev-002"})
    assert valid == []
    assert len(rejected) == 1
    assert "ev-042" in rejected[0].reasons[0]


def test_known_evidence_id_accepted_when_cache_ids_given():
    raw = json.dumps([make_finding()])
    valid, rejected = parse_and_validate(raw, known_evidence_ids={"ev-042"})
    assert rejected == []
    assert len(valid) == 1


def test_mixed_batch_partitions_valid_and_rejected():
    good = make_finding()
    bad = make_finding(id="ERC-002", evidence=[])
    valid, rejected = parse_and_validate(json.dumps([good, bad, "not-an-object"]))
    assert [f["id"] for f in valid] == ["ERC-001"]
    assert len(rejected) == 2


def test_non_array_scalar_payload_rejected():
    valid, rejected = parse_and_validate('"just a string"')
    assert valid == []
    assert "expected a JSON array" in rejected[0].reasons[0]


def test_rejection_report_is_readable():
    _, rejected = parse_and_validate(json.dumps([make_finding(evidence=[])]))
    report = rejection_report(rejected)
    assert "ERC-001" in report
    assert report.startswith("- ")
