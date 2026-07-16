"""BoardRoom benchmark CLI.

    python -m benchmark.run --config society|baseline [--board <id>]

Pipeline (all wired here except the review execution itself):

    load corpus manifest
      -> for each board: seed applicable defects (deterministic) into a mutated
         copy + write ground truth
      -> execute_review(mutated_board, config)      # the runner seam
      -> score review vs. ground truth (benchmark.metrics)
      -> aggregate + write results.json, a markdown table, and a comparison chart

Review execution goes through the single seam ``benchmark._execute.execute_review``
(a deterministic mock until the real runner is wired -- see that module). Running
each config once (two invocations) yields a full society-vs-baseline comparison;
the report picks up whichever configs have results on disk.

Corpus boards must be fetched first:  python -m benchmark.corpus.fetch
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow "python benchmark/run.py" as well as "-m benchmark.run".
if __package__ in (None, ""):  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark._execute import execute_review
from benchmark.corpus import BOARDS_DIR, GROUND_TRUTH_DIR, BoardSpec, load_manifest
from benchmark.metrics import MetricsResult, aggregate, render_comparison_chart, score, to_markdown_table
from benchmark.seed import seed_board

DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"
CONFIGS = ("society", "baseline")


def seed_and_score_board(
    spec: BoardSpec,
    config: str,
    *,
    clean_dir: Path,
    seeded_dir: Path,
    ground_truth_dir: Path,
) -> MetricsResult:
    """Seed one board, run the review under ``config``, and score it."""
    defects = seed_board(
        spec,
        clean_dir=clean_dir,
        out_dir=seeded_dir,
        ground_truth_dir=ground_truth_dir,
    )
    review = execute_review(spec.board_dir(seeded_dir), config, ground_truth=defects)
    return score(review, defects, config=config, board_id=spec.id)


def run_config(
    config: str,
    board_ids: list[str] | None = None,
    *,
    clean_dir: Path | None = None,
    seeded_dir: Path | None = None,
    ground_truth_dir: Path | None = None,
) -> list[MetricsResult]:
    """Run + score every requested board under one configuration."""
    manifest = load_manifest()
    clean_dir = clean_dir or BOARDS_DIR
    seeded_dir = seeded_dir or (DEFAULT_RESULTS_DIR / "seeded")
    ground_truth_dir = ground_truth_dir or GROUND_TRUTH_DIR

    specs = manifest.boards if not board_ids else [manifest.board(b) for b in board_ids]
    results: list[MetricsResult] = []
    for spec in specs:
        if not spec.is_present(clean_dir):
            print(f"SKIP {spec.id}: not fetched (run: python -m benchmark.corpus.fetch)")
            continue
        results.append(
            seed_and_score_board(
                spec,
                config,
                clean_dir=clean_dir,
                seeded_dir=seeded_dir,
                ground_truth_dir=ground_truth_dir,
            )
        )
    return results


def write_reports(
    results_by_config: dict[str, list[MetricsResult]],
    results_dir: Path,
) -> dict[str, Path]:
    """Write per-config results json, a combined markdown table, and a chart.

    Returns a map of artifact name -> path.
    """
    results_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, Path] = {}

    aggregates: list[MetricsResult] = []
    for config, results in results_by_config.items():
        agg = aggregate(results, config=config)
        aggregates.append(agg)
        payload = {
            "config": config,
            "aggregate": agg.to_dict(),
            "per_board": [r.to_dict() for r in results],
        }
        p = results_dir / f"results_{config}.json"
        p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        artifacts[f"results_{config}"] = p

    # Combined table: one aggregate row per config, then per-board rows.
    all_rows: list[MetricsResult] = list(aggregates)
    for results in results_by_config.values():
        all_rows.extend(results)
    table = to_markdown_table(all_rows)
    table_path = results_dir / "results_table.md"
    table_path.write_text(table + "\n", encoding="utf-8")
    artifacts["table"] = table_path

    chart_path = results_dir / "comparison_chart.png"
    render_comparison_chart(aggregates, chart_path)
    artifacts["chart"] = chart_path

    return artifacts


def _load_existing_results(results_dir: Path, skip_config: str) -> dict[str, list[MetricsResult]]:
    """Load previously-saved results for the *other* config(s), for the combined report."""
    out: dict[str, list[MetricsResult]] = {}
    for config in CONFIGS:
        if config == skip_config:
            continue
        p = results_dir / f"results_{config}.json"
        if not p.is_file():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        out[config] = [_result_from_dict(d) for d in data.get("per_board", [])]
    return out


def _result_from_dict(d: dict) -> MetricsResult:
    return MetricsResult(
        config=d["config"],
        board_id=d["board_id"],
        total_defects=d["total_defects"],
        matched_defects=d["matched_defects"],
        seeded_defect_recall=d["seeded_defect_recall"],
        false_positive_count=d["false_positive_count"],
        total_findings=d["total_findings"],
        uncited_findings=d["uncited_findings"],
        rejected_findings=d["rejected_findings"],
        hallucination_rate=d["hallucination_rate"],
        tokens_by_tier=d.get("tokens_by_tier", {}),
        total_prompt_tokens=d["total_prompt_tokens"],
        total_completion_tokens=d["total_completion_tokens"],
        cost_usd=d["cost_usd"],
        wall_time_s=d.get("wall_time_s"),
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the BoardRoom seeded-defect benchmark.")
    ap.add_argument("--config", required=True, choices=CONFIGS, help="review configuration to run")
    ap.add_argument("--board", help="only run this board id (default: whole corpus)")
    ap.add_argument("--clean-dir", type=Path, help="dir of fetched clean boards (default: corpus/boards)")
    ap.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR, help="where to write reports")
    args = ap.parse_args(argv)

    board_ids = [args.board] if args.board else None
    results = run_config(args.config, board_ids, clean_dir=args.clean_dir)
    if not results:
        print("No boards scored. Fetch the corpus first: python -m benchmark.corpus.fetch")
        return 1

    results_by_config = _load_existing_results(args.results_dir, skip_config=args.config)
    results_by_config[args.config] = results

    artifacts = write_reports(results_by_config, args.results_dir)

    agg = aggregate(results, config=args.config)
    print(to_markdown_table([agg, *results]))
    print()
    for name, path in artifacts.items():
        print(f"wrote {name}: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
