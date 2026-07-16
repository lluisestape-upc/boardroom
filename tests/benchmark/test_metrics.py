"""Matcher, recall/FP/hallucination, and token/cost scoring."""

from __future__ import annotations

from benchmark.metrics import (
    MetricsResult,
    aggregate,
    false_positive_count,
    hallucination_rate,
    match_finding,
    score,
    seeded_defect_recall,
    to_markdown_table,
    token_metrics,
)
from benchmark.seed import GroundTruthDefect


def _defect(**kw) -> GroundTruthDefect:
    base = dict(
        defect_id="b:remove_decoupling_cap",
        type="remove_decoupling_cap",
        board_id="b",
        expected_agent="power_integrity",
        expected_severity="major",
        affected_refs=["C2"],
        affected_nets=["+3V3"],
        description="x",
    )
    base.update(kw)
    return GroundTruthDefect(**base)


def _finding(**kw) -> dict:
    base = dict(
        id="PI-001",
        agent="power_integrity",
        severity="major",
        affected_nets=["+3V3"],
        affected_components=["C2"],
        evidence=[{"evidence_id": "EV-0001", "tool": "run_erc", "summary": "s"}],
    )
    base.update(kw)
    return base


# --------------------------------------------------------------------------- #
# matcher                                                                     #
# --------------------------------------------------------------------------- #


def test_match_on_component_and_agent():
    assert match_finding(_finding(affected_nets=[]), _defect())


def test_match_on_net_and_severity_within_one():
    # wrong agent, but severity critical is one level from major -> still matches
    f = _finding(agent="signal_integrity", severity="critical", affected_components=[])
    assert match_finding(f, _defect())


def test_no_match_without_location_overlap():
    f = _finding(affected_nets=["OTHER"], affected_components=["R9"])
    assert not match_finding(f, _defect())


def test_no_match_when_attribution_fails():
    # correct location, but wrong agent AND severity two levels away (info vs major)
    f = _finding(agent="dfm_layout", severity="info")
    assert not match_finding(f, _defect())


# --------------------------------------------------------------------------- #
# recall / false positives                                                    #
# --------------------------------------------------------------------------- #


def test_perfect_review_recall_is_one():
    defects = [_defect(), _defect(defect_id="b:x", affected_refs=["C7"], affected_nets=["+5V"])]
    review = {
        "findings": [
            _finding(),
            _finding(id="PI-002", affected_nets=["+5V"], affected_components=["C7"]),
        ]
    }
    assert seeded_defect_recall(review, defects) == 1.0
    assert false_positive_count(review, defects) == 0


def test_empty_review_recall_zero_and_no_false_positives():
    defects = [_defect()]
    review = {"findings": []}
    assert seeded_defect_recall(review, defects) == 0.0
    assert false_positive_count(review, defects) == 0


def test_false_positive_counted_for_nonmatching_finding():
    defects = [_defect()]
    review = {
        "findings": [
            _finding(),  # matches
            _finding(id="X-1", affected_nets=["NOPE"], affected_components=["NOPE"]),  # FP
        ]
    }
    assert seeded_defect_recall(review, defects) == 1.0
    assert false_positive_count(review, defects) == 1


def test_recall_is_one_when_nothing_seeded():
    assert seeded_defect_recall({"findings": []}, []) == 1.0


# --------------------------------------------------------------------------- #
# hallucination rate                                                          #
# --------------------------------------------------------------------------- #


def test_hallucination_rate_from_rejected_and_uncited():
    review = {
        "findings": [
            _finding(),  # cited
            _finding(id="U-1", evidence=[]),  # uncited emitted
        ],
        "rejected_findings": 2,  # rejected at boundary
    }
    # uncited(1) + rejected(2) = 3 over total emitted(2)+rejected(2) = 4
    assert hallucination_rate(review) == 0.75


def test_hallucination_rate_zero_when_all_cited_and_none_rejected():
    review = {"findings": [_finding()], "rejected_findings": 0}
    assert hallucination_rate(review) == 0.0


def test_hallucination_rate_accepts_rejected_as_list():
    review = {"findings": [_finding()], "rejected_findings": [{"id": "r1"}, {"id": "r2"}]}
    # 0 uncited emitted + 2 rejected over 1 + 2
    assert hallucination_rate(review) == 2 / 3


def test_hallucination_rate_empty_is_zero():
    assert hallucination_rate({"findings": [], "rejected_findings": 0}) == 0.0


# --------------------------------------------------------------------------- #
# tokens / cost                                                               #
# --------------------------------------------------------------------------- #


def test_token_metrics_aggregate_by_tier_and_cost():
    review = {
        "token_accounting": {
            "moderator/qwen3-max": {"prompt": 1_000_000, "completion": 0, "calls": 1},
            "power_integrity/qwen-flash": {"prompt": 1_000_000, "completion": 1_000_000, "calls": 1},
        }
    }
    by_tier, prompt, completion, cost = token_metrics(review)
    assert prompt == 2_000_000
    assert completion == 1_000_000
    # qwen3-max: 1M prompt * $1.20 ; qwen-flash: 1M*$0.05 + 1M*$0.40
    assert round(cost, 4) == round(1.20 + 0.05 + 0.40, 4)
    assert set(by_tier) == {"qwen3-max", "qwen-flash"}


def test_token_metrics_empty():
    by_tier, prompt, completion, cost = token_metrics({})
    assert (by_tier, prompt, completion, cost) == ({}, 0, 0, 0.0)


# --------------------------------------------------------------------------- #
# score() + aggregate() + table                                              #
# --------------------------------------------------------------------------- #


def test_score_builds_metrics_result_and_reads_wall_time():
    defects = [_defect()]
    review = {
        "config": "society",
        "board_id": "b",
        "findings": [_finding()],
        "rejected_findings": 0,
        "token_accounting": {"power_integrity/qwen-flash": {"prompt": 100, "completion": 50, "calls": 1}},
        "wall_time_s": 12.5,
    }
    r = score(review, defects)
    assert isinstance(r, MetricsResult)
    assert r.config == "society" and r.board_id == "b"
    assert r.seeded_defect_recall == 1.0
    assert r.wall_time_s == 12.5
    assert r.total_tokens == 150


def test_aggregate_sums_across_boards():
    r1 = MetricsResult("society", "a", 2, 2, 1.0, 0, 2, 0, 0, 0.0, {}, 100, 20, 0.1, 10.0)
    r2 = MetricsResult("society", "b", 3, 1, 1 / 3, 1, 4, 1, 1, 0.4, {}, 200, 40, 0.2, 5.0)
    agg = aggregate([r1, r2], config="society")
    assert agg.total_defects == 5
    assert agg.matched_defects == 3
    assert agg.seeded_defect_recall == 3 / 5
    assert agg.total_prompt_tokens == 300
    assert agg.wall_time_s == 15.0


def test_markdown_table_has_row_per_result():
    r = MetricsResult("society", "ALL", 1, 1, 1.0, 0, 1, 0, 0, 0.0, {}, 10, 5, 0.01, None)
    table = to_markdown_table([r])
    assert "| Config |" in table
    assert "| society | ALL |" in table
    assert table.count("\n") >= 2  # header + sep + 1 row
