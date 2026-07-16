"""Corpus manifest + on-disk layout for the benchmark.

The boards themselves are NOT redistributed (GPL/CC KiCad demos); `fetch.py`
copies them from a local KiCad install into ``boards/`` (gitignored). This module
only knows the manifest and where things live on disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

CORPUS_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = CORPUS_DIR / "manifest.yaml"
BOARDS_DIR = CORPUS_DIR / "boards"
GROUND_TRUTH_DIR = CORPUS_DIR / "ground_truth"


@dataclass(frozen=True)
class BoardSpec:
    """One corpus entry (see manifest.yaml)."""

    id: str
    demo: str
    schematic: str
    pcb: str
    complexity: str
    note: str

    def board_dir(self, boards_dir: Path | None = None) -> Path:
        """Where fetch.py places this board's copied files."""
        return (boards_dir or BOARDS_DIR) / self.id

    def schematic_path(self, boards_dir: Path | None = None) -> Path:
        return self.board_dir(boards_dir) / self.schematic

    def pcb_path(self, boards_dir: Path | None = None) -> Path:
        return self.board_dir(boards_dir) / self.pcb

    def is_present(self, boards_dir: Path | None = None) -> bool:
        return self.schematic_path(boards_dir).is_file() and self.pcb_path(boards_dir).is_file()


@dataclass(frozen=True)
class Manifest:
    version: int
    install_globs: list[str]
    boards: list[BoardSpec]

    def board(self, board_id: str) -> BoardSpec:
        for b in self.boards:
            if b.id == board_id:
                return b
        raise KeyError(f"unknown board id {board_id!r}; known: {[b.id for b in self.boards]}")

    @property
    def board_ids(self) -> list[str]:
        return [b.id for b in self.boards]


def load_manifest(path: Path | None = None) -> Manifest:
    """Parse manifest.yaml into a typed Manifest."""
    path = path or MANIFEST_PATH
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    boards = [
        BoardSpec(
            id=b["id"],
            demo=b["demo"],
            schematic=b["schematic"],
            pcb=b["pcb"],
            complexity=b.get("complexity", "unknown"),
            note=b.get("note", "").strip(),
        )
        for b in data["boards"]
    ]
    return Manifest(
        version=int(data.get("version", 1)),
        install_globs=list(data.get("install_globs", [])),
        boards=boards,
    )
