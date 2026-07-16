"""Fixtures for benchmark tests.

Make the repo root importable (benchmark/ and backend/ are namespace packages)
and provide a clean single-board corpus built from the gitignored stickhub
fixture, so the harness is testable without a fetched corpus.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmark.corpus import BoardSpec, load_manifest  # noqa: E402

FIXTURE_STICKHUB = REPO_ROOT / "fixtures" / "stickhub"


@pytest.fixture(scope="session")
def manifest():
    return load_manifest()


@pytest.fixture
def stickhub_spec(manifest) -> BoardSpec:
    return manifest.board("stickhub")


@pytest.fixture
def clean_dir(tmp_path, stickhub_spec) -> Path:
    """A clean-boards dir containing just stickhub, copied from the fixture."""
    if not FIXTURE_STICKHUB.is_dir():
        pytest.skip("stickhub fixture not present")
    dest = tmp_path / "clean"
    board = dest / stickhub_spec.id
    board.mkdir(parents=True)
    for f in FIXTURE_STICKHUB.iterdir():
        if f.is_file():
            shutil.copy(f, board / f.name)
    return dest


@pytest.fixture
def stickhub_sch_text(clean_dir, stickhub_spec) -> str:
    return stickhub_spec.schematic_path(clean_dir).read_text(encoding="utf-8")
