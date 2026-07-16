"""Copy corpus boards out of a local KiCad install into corpus/boards/.

The KiCad demo projects are GPL/CC licensed; we do not redistribute them in this
repo. This script locates a local KiCad install, copies each board named in
manifest.yaml into ``corpus/boards/<id>/`` (gitignored), and reports what it did.

Idempotent: a board already present with both its .kicad_sch and .kicad_pcb is
left untouched unless ``--force`` is given. Only the files the seeder needs
(the whole demo project directory) are copied.

Usage:
    python -m benchmark.corpus.fetch [--force] [--kicad-share PATH] [--board ID]

``--kicad-share`` points at a ``.../share/kicad/demos`` directory (or any parent
containing the demo folders) and overrides the manifest's install_globs probing.
"""

from __future__ import annotations

import argparse
import glob
import shutil
import sys
from pathlib import Path

# Support both "python -m benchmark.corpus.fetch" and "python fetch.py".
if __package__ in (None, ""):  # pragma: no cover - direct-script convenience
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from benchmark.corpus import BOARDS_DIR, BoardSpec, load_manifest
else:
    from . import BOARDS_DIR, BoardSpec, load_manifest


def find_demos_dir(install_globs: list[str], override: str | None = None) -> Path | None:
    """First existing demos directory: the override, else the manifest globs."""
    candidates: list[str] = []
    if override:
        candidates.append(override)
    candidates.extend(install_globs)
    for pattern in candidates:
        for hit in sorted(glob.glob(pattern)):
            p = Path(hit)
            if p.is_dir():
                return p
    return None


def _copy_board(spec: BoardSpec, demos_dir: Path, boards_dir: Path, *, force: bool) -> str:
    """Copy one board's demo directory. Returns a one-line status string."""
    src = demos_dir / spec.demo
    dst = spec.board_dir(boards_dir)

    if not src.is_dir():
        return f"MISSING  {spec.id}: demo dir not found at {src}"
    if not (src / spec.schematic).is_file() or not (src / spec.pcb).is_file():
        return f"MISSING  {spec.id}: {spec.schematic}/{spec.pcb} not in {src}"

    if spec.is_present(boards_dir) and not force:
        return f"SKIP     {spec.id}: already present ({dst})"

    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return f"COPIED   {spec.id}: {src} -> {dst}"


def fetch(
    *,
    boards_dir: Path | None = None,
    kicad_share: str | None = None,
    only: str | None = None,
    force: bool = False,
) -> list[str]:
    """Copy corpus boards; returns the list of status lines (also printed)."""
    manifest = load_manifest()
    boards_dir = boards_dir or BOARDS_DIR
    boards_dir.mkdir(parents=True, exist_ok=True)

    demos_dir = find_demos_dir(manifest.install_globs, kicad_share)
    lines: list[str] = []
    if demos_dir is None:
        lines.append(
            "ERROR: no KiCad demos directory found. Probed: "
            + ", ".join([kicad_share] if kicad_share else manifest.install_globs)
            + ". Pass --kicad-share <path-to>/share/kicad/demos."
        )
        for line in lines:
            print(line)
        return lines

    lines.append(f"# KiCad demos: {demos_dir}")
    lines.append(f"# boards ->    {boards_dir}")
    for spec in manifest.boards:
        if only and spec.id != only:
            continue
        line = _copy_board(spec, demos_dir, boards_dir, force=force)
        lines.append(line)

    for line in lines:
        print(line)
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fetch benchmark corpus boards from a local KiCad install.")
    ap.add_argument("--force", action="store_true", help="re-copy even if already present")
    ap.add_argument("--kicad-share", help="path to a .../share/kicad/demos directory (overrides probing)")
    ap.add_argument("--board", help="only fetch this board id")
    args = ap.parse_args(argv)

    lines = fetch(kicad_share=args.kicad_share, only=args.board, force=args.force)
    ok = any(line.startswith(("COPIED", "SKIP")) for line in lines)
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
