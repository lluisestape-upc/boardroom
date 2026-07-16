"""Scoring: compare a review.json against a seeded ground-truth manifest.

Metrics (all honest, both wins and losses reported):

* seeded_defect_recall - fraction of seeded defects matched by >=1 finding.
* false_positive_count  - emitted findings matching no seeded defect.
* hallucination_rate    - uncited findings (rejected at the boundary + any
                          emitted finding lacking evidence) over all findings.
* token metrics         - prompt/completion by model tier + a $-weighted total
                          using backend/app/qwen_client.py COST_PER_MTOK.
* wall_time_s           - from review.json if present, else None.

Matcher (seeded_defect_recall / false_positive_count)
-----------------------------------------------------
A finding MATCHES a seeded defect when BOTH hold:

    (1) location overlap: the finding's affected_nets intersect the defect's
        affected_nets, OR its affected_components intersect the defect's
        affected_refs; AND
    (2) attribution: the finding's agent equals the defect's expected_agent,
        OR its severity is within one level of the defect's expected_severity.

i.e.  (nets_overlap OR components_overlap) AND (agent_match OR severity_within_one).
Severity order is critical > major > minor > info; "within one" means adjacent.
A defect is recalled if any finding matches it; a finding is a false positive if
it matches no defect.

review.json shape consumed here (also emitted by benchmark/_execute.py):
    {
      "config": "society" | "baseline",
      "board_id": "...",
      "findings": [ {finding.schema.json shape} ],
      "rejected_findings": <int>  |  [ ... ],   # uncited, rejected at boundary
      "token_accounting": { "<agent>/<model>": {"prompt": int, "completion": int, "calls": int} },
      "wall_time_s": <float>                      # optional
    }
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from backend.app.qwen_client import COST_PER_MTOK

from .seed import GroundTruthDefect

SEVERITY_ORDER = ["critical", "major", "minor", "info"]


# --------------------------------------------------------------------------- #
# matcher                                                                     #
# --------------------------------------------------------------------------- #


def _severity_within_one(a: str, b: str) -> bool:
    if a not in SEVERITY_ORDER or b not in SEVERITY_ORDER:
        return False
    return abs(SEVERITY_ORDER.index(a) - SEVERITY_ORDER.index(b)) <= 1


def match_finding(finding: dict, defect: GroundTruthDefect) -> bool:
    """True if ``finding`` matches ``defect`` per the documented matcher."""
    nets = set(finding.get("affected_nets") or [])
    comps = set(finding.get("affected_components") or [])
    location = bool(nets & set(defect.affected_nets)) or bool(comps & set(defect.affected_refs))
    if not location:
        return False
    agent_match = finding.get("agent") == defect.expected_agent
    severity_match = _severity_within_one(finding.get("severity", ""), defect.expected_severity)
    return agent_match or severity_match


def seeded_defect_recall(review: dict, defects: list[GroundTruthDefect]) -> float:
    """Fraction of seeded defects matched by at least one finding (1.0 if none seeded)."""
    if not defects:
        return 1.0
    findings = review.get("findings") or []
    matched = sum(1 for d in defects if any(match_finding(f, d) for f in findings))
    return matched / len(defects)


def matched_defect_count(review: dict, defects: list[GroundTruthDefect]) -> int:
    findings = review.get("findings") or []
    return sum(1 for d in defects if any(match_finding(f, d) for f in findings))


def false_positive_count(review: dict, defects: list[GroundTruthDefect]) -> int:
    """Emitted findings that match no seeded defect."""
    findings = review.get("findings") or []
    return sum(1 for f in findings if not any(match_finding(f, d) for d in defects))


def _rejected_count(review: dict) -> int:
    rej = review.get("rejected_findings", 0)
    if isinstance(rej, int):
        return rej
    try:
        return len(rej)
    except TypeError:
        return 0


def hallucination_rate(review: dict) -> float:
    """Uncited findings over all findings considered.

    Uncited = findings rejected at the evidence boundary + any emitted finding
    whose ``evidence`` array is empty/missing. Denominator is emitted + rejected.
    """
    findings = review.get("findings") or []
    rejected = _rejected_count(review)
    uncited_emitted = sum(1 for f in findings if not (f.get("evidence") or []))
    total = len(findings) + rejected
    if total == 0:
        return 0.0
    return (uncited_emitted + rejected) / total


def token_metrics(review: dict) -> tuple[dict[str, dict[str, int]], int, int, float]:
    """(tokens_by_tier, total_prompt, total_completion, cost_usd).

    ``token_accounting`` keys are ``"<agent>/<model>"`` (the ledger snapshot
    shape); tokens are aggregated by model tier and $-weighted via COST_PER_MTOK.
    """
    accounting = review.get("token_accounting") or {}
    by_tier: dict[str, dict[str, int]] = {}
    for key, counts in accounting.items():
        model = key.split("/", 1)[1] if "/" in key else key
        tier = by_tier.setdefault(model, {"prompt": 0, "completion": 0})
        tier["prompt"] += int(counts.get("prompt", 0))
        tier["completion"] += int(counts.get("completion", 0))
    total_prompt = sum(t["prompt"] for t in by_tier.values())
    total_completion = sum(t["completion"] for t in by_tier.values())
    cost = 0.0
    for model, t in by_tier.items():
        prompt_rate, completion_rate = COST_PER_MTOK.get(model, (0.0, 0.0))
        cost += t["prompt"] / 1_000_000 * prompt_rate
        cost += t["completion"] / 1_000_000 * completion_rate
    return by_tier, total_prompt, total_completion, cost


# --------------------------------------------------------------------------- #
# aggregate result                                                            #
# --------------------------------------------------------------------------- #


@dataclass
class MetricsResult:
    config: str
    board_id: str
    total_defects: int
    matched_defects: int
    seeded_defect_recall: float
    false_positive_count: int
    total_findings: int
    uncited_findings: int
    rejected_findings: int
    hallucination_rate: float
    tokens_by_tier: dict[str, dict[str, int]] = field(default_factory=dict)
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    cost_usd: float = 0.0
    wall_time_s: float | None = None

    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.total_completion_tokens

    def to_dict(self) -> dict:
        d = asdict(self)
        d["total_tokens"] = self.total_tokens
        return d


def score(
    review: dict,
    defects: list[GroundTruthDefect],
    *,
    config: str | None = None,
    board_id: str | None = None,
) -> MetricsResult:
    """Score one review.json against its ground-truth defects."""
    findings = review.get("findings") or []
    by_tier, total_prompt, total_completion, cost = token_metrics(review)
    return MetricsResult(
        config=config or review.get("config", "unknown"),
        board_id=board_id or review.get("board_id", "unknown"),
        total_defects=len(defects),
        matched_defects=matched_defect_count(review, defects),
        seeded_defect_recall=seeded_defect_recall(review, defects),
        false_positive_count=false_positive_count(review, defects),
        total_findings=len(findings),
        uncited_findings=sum(1 for f in findings if not (f.get("evidence") or [])),
        rejected_findings=_rejected_count(review),
        hallucination_rate=hallucination_rate(review),
        tokens_by_tier=by_tier,
        total_prompt_tokens=total_prompt,
        total_completion_tokens=total_completion,
        cost_usd=cost,
        wall_time_s=review.get("wall_time_s"),
    )


def aggregate(results: list[MetricsResult], *, config: str, board_id: str = "ALL") -> MetricsResult:
    """Combine per-board results for one config into a corpus-level result."""
    if not results:
        return MetricsResult(config, board_id, 0, 0, 1.0, 0, 0, 0, 0, 0.0)
    total_defects = sum(r.total_defects for r in results)
    matched = sum(r.matched_defects for r in results)
    by_tier: dict[str, dict[str, int]] = {}
    for r in results:
        for model, t in r.tokens_by_tier.items():
            agg = by_tier.setdefault(model, {"prompt": 0, "completion": 0})
            agg["prompt"] += t["prompt"]
            agg["completion"] += t["completion"]
    total_prompt = sum(r.total_prompt_tokens for r in results)
    total_completion = sum(r.total_completion_tokens for r in results)
    total_findings = sum(r.total_findings for r in results)
    uncited = sum(r.uncited_findings for r in results)
    rejected = sum(r.rejected_findings for r in results)
    denom = total_findings + rejected
    walls = [r.wall_time_s for r in results if r.wall_time_s is not None]
    return MetricsResult(
        config=config,
        board_id=board_id,
        total_defects=total_defects,
        matched_defects=matched,
        seeded_defect_recall=(matched / total_defects) if total_defects else 1.0,
        false_positive_count=sum(r.false_positive_count for r in results),
        total_findings=total_findings,
        uncited_findings=uncited,
        rejected_findings=rejected,
        hallucination_rate=((uncited + rejected) / denom) if denom else 0.0,
        tokens_by_tier=by_tier,
        total_prompt_tokens=total_prompt,
        total_completion_tokens=total_completion,
        cost_usd=sum(r.cost_usd for r in results),
        wall_time_s=sum(walls) if walls else None,
    )


# --------------------------------------------------------------------------- #
# reporting                                                                   #
# --------------------------------------------------------------------------- #


def to_markdown_table(results: list[MetricsResult]) -> str:
    """Render one or more MetricsResults as a comparison markdown table."""
    header = (
        "| Config | Board | Recall | Defects | False+ | Halluc. | "
        "Prompt tok | Compl. tok | Cost $ | Wall s |"
    )
    sep = "|---|---|---|---|---|---|---|---|---|---|"
    rows = [header, sep]
    for r in results:
        wall = f"{r.wall_time_s:.1f}" if r.wall_time_s is not None else "-"
        rows.append(
            f"| {r.config} | {r.board_id} | {r.seeded_defect_recall:.2f} | "
            f"{r.matched_defects}/{r.total_defects} | {r.false_positive_count} | "
            f"{r.hallucination_rate:.2f} | {r.total_prompt_tokens} | "
            f"{r.total_completion_tokens} | {r.cost_usd:.4f} | {wall} |"
        )
    return "\n".join(rows)


def render_comparison_chart(results: list[MetricsResult], path: str | Path) -> Path:
    """Grouped-bar chart: one group per config, comparing key metrics.

    Two panels: quality (recall, 1-hallucination) on a 0..1 scale, and cost
    (total tokens, USD) on a log-friendly linear scale. Writes a PNG to ``path``.
    """
    import matplotlib

    matplotlib.use("Agg")  # headless; no display needed
    import matplotlib.pyplot as plt

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    configs = [r.config for r in results]
    x = range(len(results))
    width = 0.38

    fig, (ax_q, ax_c) = plt.subplots(1, 2, figsize=(11, 4.5))

    recall = [r.seeded_defect_recall for r in results]
    clean = [1.0 - r.hallucination_rate for r in results]
    ax_q.bar([i - width / 2 for i in x], recall, width, label="recall", color="#2b8cbe")
    ax_q.bar([i + width / 2 for i in x], clean, width, label="1 - halluc.", color="#a6bddb")
    ax_q.set_ylim(0, 1.05)
    ax_q.set_xticks(list(x))
    ax_q.set_xticklabels(configs)
    ax_q.set_title("Quality (higher is better)")
    ax_q.set_ylabel("fraction")
    ax_q.legend()

    tokens = [r.total_tokens for r in results]
    cost = [r.cost_usd for r in results]
    ax_c.bar([i - width / 2 for i in x], tokens, width, label="total tokens", color="#e34a33")
    ax_c.set_xticks(list(x))
    ax_c.set_xticklabels(configs)
    ax_c.set_title("Cost (lower is better)")
    ax_c.set_ylabel("tokens")
    ax_cost = ax_c.twinx()
    ax_cost.plot(list(x), cost, "o-", color="#000000", label="cost $")
    ax_cost.set_ylabel("USD")

    fig.suptitle("BoardRoom: society vs. baseline")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path
