"""Real-runner implementation of the execute_review seam.

Used only when BOARDROOM_REAL_RUNNER is set (see _execute.py). Requires
DASHSCOPE_API_KEY and a reachable kicad-mcp-server. Kept separate so the
default harness + tests stay fully offline against the mock.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path


def real_execute(board_path: Path, config: str) -> dict:
    """Run the live society/baseline pipeline; return the benchmark review shape."""
    from backend.app.review import run_baseline_review, run_review

    started = time.monotonic()
    if config == "society":
        review = asyncio.run(run_review(str(board_path)))
        rejected = review.get("rejected_findings", [])
        result = {
            "config": "society",
            "board_id": board_path.name,
            "findings": review.get("findings", []),
            "rejected_findings": len(rejected) if isinstance(rejected, list) else int(rejected),
            "token_accounting": review.get("token_accounting", {}),
        }
    else:
        result = asyncio.run(run_baseline_review(str(board_path)))
    result["wall_time_s"] = round(time.monotonic() - started, 2)
    return result
