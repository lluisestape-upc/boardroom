"""End-to-end harness run against the mock reviewer (no live runner)."""

from __future__ import annotations

from benchmark._execute import execute_review
from benchmark.metrics import aggregate
from benchmark.run import run_config, write_reports


def _run_both(clean_dir, tmp_path):
    seeded = tmp_path / "seeded"
    gt = tmp_path / "gt"
    society = run_config("society", ["stickhub"], clean_dir=clean_dir, seeded_dir=seeded, ground_truth_dir=gt)
    baseline = run_config("baseline", ["stickhub"], clean_dir=clean_dir, seeded_dir=seeded, ground_truth_dir=gt)
    return society, baseline


def test_run_config_scores_stickhub(clean_dir, tmp_path):
    results = run_config(
        "society",
        ["stickhub"],
        clean_dir=clean_dir,
        seeded_dir=tmp_path / "seeded",
        ground_truth_dir=tmp_path / "gt",
    )
    assert len(results) == 1
    r = results[0]
    assert r.board_id == "stickhub"
    assert r.config == "society"
    assert r.total_defects >= 1
    # society mock catches every seeded defect
    assert r.seeded_defect_recall == 1.0


def test_run_config_skips_unfetched_board(manifest, tmp_path):
    # empty clean dir -> nothing present -> no results, no crash
    results = run_config("baseline", ["stickhub"], clean_dir=tmp_path / "empty", seeded_dir=tmp_path / "s",
                         ground_truth_dir=tmp_path / "g")
    assert results == []


def test_end_to_end_writes_table_and_chart(clean_dir, tmp_path):
    society, baseline = _run_both(clean_dir, tmp_path)
    results_dir = tmp_path / "results"
    artifacts = write_reports({"society": society, "baseline": baseline}, results_dir)

    # markdown table exists and lists both configs
    table_text = artifacts["table"].read_text(encoding="utf-8")
    assert "| society |" in table_text
    assert "| baseline |" in table_text

    # chart PNG exists and is a real PNG
    chart = artifacts["chart"]
    assert chart.is_file()
    assert chart.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    # per-config results json written
    assert artifacts["results_society"].is_file()
    assert artifacts["results_baseline"].is_file()


def test_society_is_cheaper_than_baseline_in_mock(clean_dir, tmp_path):
    society, baseline = _run_both(clean_dir, tmp_path)
    soc = aggregate(society, config="society")
    base = aggregate(baseline, config="baseline")
    # The whole point of the benchmark: the society's cheap-specialist profile
    # costs less than the single expensive-model baseline.
    assert soc.cost_usd < base.cost_usd
    assert soc.hallucination_rate <= base.hallucination_rate


def test_execute_review_rejects_unknown_config(clean_dir, stickhub_spec):
    import pytest

    with pytest.raises(ValueError):
        execute_review(stickhub_spec.board_dir(clean_dir), "nonsense")
