"""Board rendering for the qwen3-vl layout critic (architect ruling 1A).

Renders a ``.kicad_pcb`` to PNG via ``kicad-cli pcb render`` at a **fixed
DPI** (:data:`RENDER_DPI`). Ruling 1A (report/QUESTIONS.md §3): the review
root carries render metadata ``{image, width_px, height_px, dpi}`` and every
``board_region`` a finding files stays in pixels of that render — the
frontend scales overlays from the image's natural size.

Mechanics:

- Pixel dimensions are computed from the board's Edge.Cuts bounding box at
  ``RENDER_DPI`` (kicad-cli's render command takes ``--width/--height`` in
  pixels, not DPI). Oversized boards are clamped to :data:`MAX_EDGE_PX` per
  edge and the *effective* dpi in the result is scaled accordingly, so the
  metadata always tells the truth. A 100x100 mm board renders at
  ~1181x1181 px — comfortably under the ~2000 px ruling budget.
- ``kicad-cli`` is resolved from the ``KICAD_CLI`` env var, then PATH, then
  the standard Windows install locations (``C:\\Program Files\\KiCad\\<ver>\\bin``).
  When it cannot be found, :class:`~mcp.errors.KicadCliMissingError` is
  raised so the orchestrator degrades the layout critic to a
  "visual critique not covered" note instead of failing the review.
- The returned :class:`RenderResult` reads ``width_px``/``height_px`` back
  from the PNG header (pure stdlib ``struct``), never trusting the request.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import struct
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .errors import KicadCliMissingError, MissingArtifactError, ToolExecutionError

#: Fixed render DPI per architect ruling 1A. 300 dpi => 100 mm ≈ 1181 px.
RENDER_DPI = 300.0

#: Longest allowed image edge; larger boards are scaled down (dpi drops with them).
MAX_EDGE_PX = 2000

#: Shortest allowed longest-edge; tiny boards are scaled up to stay legible.
MIN_EDGE_PX = 320

#: Minimum for the SHORT edge. Narrow boards otherwise render too coarse for the
#: qwen3-vl layout critic (and for the board-overlay view) even when their long
#: edge is comfortably above MIN_EDGE_PX.
MIN_SHORT_EDGE_PX = 700

#: Used when the Edge.Cuts bounding box cannot be determined from the file.
FALLBACK_SIZE_PX = (1600, 1200)

MM_PER_INCH = 25.4

#: Environment variable overriding kicad-cli discovery (full path or command).
ENV_VAR = "KICAD_CLI"

#: Tool name used on typed errors / coverage notes for render failures.
TOOL_NAME = "render_board"

RENDER_TIMEOUT_S = 180.0

_WINDOWS_INSTALL_GLOBS = (
    r"C:\Program Files\KiCad\*\bin\kicad-cli.exe",
    r"C:\Program Files (x86)\KiCad\*\bin\kicad-cli.exe",
)

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class RenderResult(BaseModel):
    """Render metadata for the review root (ruling 1A shape)."""

    model_config = ConfigDict(frozen=True)

    image_path: str
    width_px: int
    height_px: int
    dpi: float


# ---------------------------------------------------------------------------
# kicad-cli discovery
# ---------------------------------------------------------------------------


def _version_key(cli_path: str) -> tuple[int, ...]:
    """Sort key preferring the newest installed KiCad (…\\KiCad\\10.0\\bin\\…)."""
    version_dir = Path(cli_path).parent.parent.name
    return tuple(int(part) for part in re.findall(r"\d+", version_dir)) or (0,)


def find_kicad_cli(env: dict[str, str] | None = None) -> str | None:
    """Resolve the kicad-cli executable, or None when unavailable.

    Precedence: ``KICAD_CLI`` env var > ``kicad-cli`` on PATH > standard
    Windows install locations (newest version wins).
    """
    environ = os.environ if env is None else env
    raw = (environ.get(ENV_VAR) or "").strip()
    if raw:
        if Path(raw).is_file():
            return raw
        return shutil.which(raw)
    on_path = shutil.which("kicad-cli")
    if on_path:
        return on_path
    candidates: list[str] = []
    for pattern in _WINDOWS_INSTALL_GLOBS:
        candidates.extend(glob.glob(pattern))
    if candidates:
        return max(candidates, key=_version_key)
    return None


# ---------------------------------------------------------------------------
# Board size (Edge.Cuts bounding box) -> pixel dimensions at fixed DPI
# ---------------------------------------------------------------------------

_GRAPHIC_NODE_RE = re.compile(
    r"\((?:gr_line|gr_arc|gr_rect|gr_circle|gr_curve|gr_poly)\b"
)
_COORD_RE = re.compile(
    r"\((?:start|end|mid|center|xy)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)"
)
_NODE_CAP = 20_000  # graphic items are small; cap the balanced scan defensively


def _balanced_node(text: str, start: int) -> str:
    """The s-expression node starting at ``text[start] == '('`` (capped)."""
    depth = 0
    end = min(len(text), start + _NODE_CAP)
    for i in range(start, end):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:end]


def edge_cuts_bbox_mm(pcb_text: str) -> tuple[float, float] | None:
    """(width_mm, height_mm) of the board outline, or None if undeterminable.

    Scans board-level graphic items on the Edge.Cuts layer and collects their
    coordinate pairs. Footprint-local shapes (``fp_*``, coordinates relative
    to the footprint) are deliberately ignored.
    """
    xs: list[float] = []
    ys: list[float] = []
    for m in _GRAPHIC_NODE_RE.finditer(pcb_text):
        node = _balanced_node(pcb_text, m.start())
        if '"Edge.Cuts"' not in node and "(layer Edge.Cuts)" not in node:
            continue
        for cm in _COORD_RE.finditer(node):
            xs.append(float(cm.group(1)))
            ys.append(float(cm.group(2)))
    if len(xs) < 2:
        return None
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    if width <= 0 or height <= 0:
        return None
    return width, height


def planned_render_size(pcb_text: str) -> tuple[int, int, float]:
    """(width_px, height_px, effective_dpi) for a board file's render.

    The nominal scale is :data:`RENDER_DPI`; clamping to
    [:data:`MIN_EDGE_PX`, :data:`MAX_EDGE_PX`] rescales both edges *and* the
    reported dpi so the metadata stays consistent with the image.
    """
    bbox = edge_cuts_bbox_mm(pcb_text)
    if bbox is None:
        return FALLBACK_SIZE_PX[0], FALLBACK_SIZE_PX[1], RENDER_DPI
    width_mm, height_mm = bbox
    width = width_mm / MM_PER_INCH * RENDER_DPI
    height = height_mm / MM_PER_INCH * RENDER_DPI
    longest = max(width, height)
    shortest = min(width, height)
    scale = 1.0
    if longest > MAX_EDGE_PX:
        scale = MAX_EDGE_PX / longest
    elif shortest < MIN_SHORT_EDGE_PX:
        # A long, narrow board (e.g. a USB stick) can clear the long-edge minimum
        # while its short edge is only ~150 px — far too coarse for the vision
        # critic to see silkscreen or pad detail. Scale up on the SHORT edge,
        # then back off if that would blow past the long-edge ceiling.
        scale = MIN_SHORT_EDGE_PX / shortest
        if longest * scale > MAX_EDGE_PX:
            scale = MAX_EDGE_PX / longest
    elif longest < MIN_EDGE_PX:
        scale = MIN_EDGE_PX / longest
    return (
        max(1, round(width * scale)),
        max(1, round(height * scale)),
        RENDER_DPI * scale,
    )


# ---------------------------------------------------------------------------
# PNG header
# ---------------------------------------------------------------------------


def png_dimensions(path: str | Path) -> tuple[int, int]:
    """(width, height) from a PNG file's IHDR chunk (stdlib only)."""
    with open(path, "rb") as fh:
        header = fh.read(24)
    if len(header) < 24 or not header.startswith(_PNG_SIGNATURE) or header[12:16] != b"IHDR":
        raise ToolExecutionError(
            f"not a valid PNG file: {path}", tool=TOOL_NAME, detail=repr(header[:24])
        )
    width, height = struct.unpack(">II", header[16:24])
    return width, height


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_board(
    pcb_path: str | Path,
    session_dir: str | Path,
    *,
    side: str = "top",
    kicad_cli: str | None = None,
    timeout_s: float = RENDER_TIMEOUT_S,
) -> RenderResult:
    """Render ``pcb_path`` to ``<session_dir>/<stem>_<side>.png``.

    Raises typed errors the orchestrator can turn into coverage notes:

    - :class:`MissingArtifactError` — the project has no such .kicad_pcb.
    - :class:`KicadCliMissingError` — kicad-cli unavailable; the layout
      critic degrades to "visual critique not covered".
    - :class:`ToolExecutionError` — kicad-cli failed or produced no/invalid PNG.
    """
    pcb = Path(pcb_path)
    if not pcb.is_file():
        raise MissingArtifactError(f"PCB file not found: {pcb_path}", tool=TOOL_NAME)

    cli = kicad_cli or find_kicad_cli()
    if cli is None:
        raise KicadCliMissingError(
            "kicad-cli not found (checked KICAD_CLI env var, PATH, and standard "
            "install locations); board rendering unavailable — visual critique "
            "not covered",
            tool=TOOL_NAME,
        )

    width, height, dpi = planned_render_size(
        pcb.read_text(encoding="utf-8", errors="ignore")
    )

    out_dir = Path(session_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{pcb.stem}_{side}.png"

    cmd = [
        cli,
        "pcb",
        "render",
        "--output",
        str(out_path),
        "--width",
        str(width),
        "--height",
        str(height),
        "--side",
        side,
        "--background",
        "opaque",
        "--quality",
        "basic",
        str(pcb),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout_s)
    except FileNotFoundError as exc:
        raise KicadCliMissingError(
            f"kicad-cli vanished or is not executable: {cli}", tool=TOOL_NAME
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolExecutionError(
            f"kicad-cli render timed out after {timeout_s:.0f}s for {pcb.name}",
            tool=TOOL_NAME,
        ) from exc

    if proc.returncode != 0 or not out_path.is_file():
        stderr = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        stdout = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
        raise ToolExecutionError(
            f"kicad-cli render failed for {pcb.name} (exit {proc.returncode})",
            tool=TOOL_NAME,
            detail=stderr or stdout or None,
        )

    width_px, height_px = png_dimensions(out_path)
    return RenderResult(
        image_path=str(out_path), width_px=width_px, height_px=height_px, dpi=dpi
    )
