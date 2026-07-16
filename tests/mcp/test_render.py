"""render.py: cli discovery, bbox->size math, PNG header, render_board (mocked
subprocess), plus one skippable live render against the local KiCad install."""

from __future__ import annotations

import struct
import subprocess
from pathlib import Path

import pytest

from mcp.errors import KicadCliMissingError, MissingArtifactError, ToolExecutionError
from mcp.render import (
    FALLBACK_SIZE_PX,
    MAX_EDGE_PX,
    MIN_EDGE_PX,
    RENDER_DPI,
    RenderResult,
    edge_cuts_bbox_mm,
    find_kicad_cli,
    planned_render_size,
    png_dimensions,
    render_board,
)

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def write_png_header(path: Path, width: int, height: int) -> None:
    path.write_bytes(PNG_SIG + b"\x00\x00\x00\x0d" + b"IHDR" + struct.pack(">II", width, height))


def board_text(width_mm: float, height_mm: float) -> str:
    return (
        "(kicad_pcb\n"
        f'  (gr_line (start 0 0) (end {width_mm} 0) (layer "Edge.Cuts"))\n'
        f'  (gr_line (start {width_mm} 0) (end {width_mm} {height_mm}) (layer "Edge.Cuts"))\n'
        f'  (gr_line (start {width_mm} {height_mm}) (end 0 {height_mm}) (layer "Edge.Cuts"))\n'
        f'  (gr_line (start 0 {height_mm}) (end 0 0) (layer "Edge.Cuts"))\n'
        ")\n"
    )


# --- find_kicad_cli ---------------------------------------------------------


def test_env_var_file_path_wins(tmp_path, monkeypatch):
    fake_cli = tmp_path / "kicad-cli.exe"
    fake_cli.write_bytes(b"")
    assert find_kicad_cli(env={"KICAD_CLI": str(fake_cli)}) == str(fake_cli)


def test_env_var_command_resolved_via_which(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: r"C:\somewhere\kicad-cli.exe" if cmd == "kicad-cli" else None)
    assert find_kicad_cli(env={"KICAD_CLI": "kicad-cli"}) == r"C:\somewhere\kicad-cli.exe"


def test_path_fallback(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: r"C:\onpath\kicad-cli.exe")
    assert find_kicad_cli(env={}) == r"C:\onpath\kicad-cli.exe"


def test_install_glob_prefers_newest(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    monkeypatch.setattr(
        "glob.glob",
        lambda pattern: [
            r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe",
            r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe",
        ]
        if "Program Files\\KiCad" in pattern
        else [],
    )
    assert find_kicad_cli(env={}) == r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"


def test_not_found_returns_none(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    monkeypatch.setattr("glob.glob", lambda pattern: [])
    assert find_kicad_cli(env={}) is None


# --- edge_cuts_bbox_mm / planned_render_size --------------------------------


def test_bbox_from_edge_cuts():
    assert edge_cuts_bbox_mm(board_text(100, 50)) == (100.0, 50.0)


def test_bbox_ignores_non_edge_layers_and_requires_points():
    text = '(kicad_pcb (gr_line (start 0 0) (end 99 99) (layer "F.SilkS")))'
    assert edge_cuts_bbox_mm(text) is None
    assert edge_cuts_bbox_mm("(kicad_pcb)") is None


def test_planned_size_at_nominal_dpi():
    w, h, dpi = planned_render_size(board_text(100, 100))
    assert dpi == RENDER_DPI
    assert w == h == round(100 / 25.4 * RENDER_DPI)  # ~1181
    assert w < MAX_EDGE_PX


def test_planned_size_clamps_large_board_and_scales_dpi():
    w, h, dpi = planned_render_size(board_text(400, 200))
    assert max(w, h) == MAX_EDGE_PX
    assert dpi < RENDER_DPI
    # metadata consistency: px / dpi * 25.4 ≈ mm
    assert w / dpi * 25.4 == pytest.approx(400, rel=0.01)


def test_planned_size_scales_up_tiny_board():
    w, h, dpi = planned_render_size(board_text(10, 5))
    assert max(w, h) == MIN_EDGE_PX
    assert dpi > RENDER_DPI


def test_planned_size_fallback_without_outline():
    w, h, dpi = planned_render_size("(kicad_pcb)")
    assert (w, h) == FALLBACK_SIZE_PX
    assert dpi == RENDER_DPI


# --- png_dimensions ----------------------------------------------------------


def test_png_dimensions_reads_ihdr(tmp_path):
    p = tmp_path / "x.png"
    write_png_header(p, 1600, 1200)
    assert png_dimensions(p) == (1600, 1200)


def test_png_dimensions_rejects_non_png(tmp_path):
    p = tmp_path / "x.png"
    p.write_bytes(b"definitely not a png, not even close")
    with pytest.raises(ToolExecutionError):
        png_dimensions(p)


# --- render_board (mocked subprocess) ----------------------------------------


@pytest.fixture
def pcb_file(tmp_path):
    p = tmp_path / "demo.kicad_pcb"
    p.write_text(board_text(100, 50), encoding="utf-8")
    return p


def test_missing_pcb_raises(tmp_path):
    with pytest.raises(MissingArtifactError):
        render_board(tmp_path / "nope.kicad_pcb", tmp_path)


def test_missing_cli_degrades_typed(pcb_file, tmp_path, monkeypatch):
    monkeypatch.setattr("mcp.render.find_kicad_cli", lambda env=None: None)
    with pytest.raises(KicadCliMissingError):
        render_board(pcb_file, tmp_path / "out")


def test_render_success(pcb_file, tmp_path, monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output, timeout):
        captured["cmd"] = cmd
        out = Path(cmd[cmd.index("--output") + 1])
        w = int(cmd[cmd.index("--width") + 1])
        h = int(cmd[cmd.index("--height") + 1])
        write_png_header(out, w, h)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr("mcp.render.subprocess.run", fake_run)
    result = render_board(pcb_file, tmp_path / "out", kicad_cli="kicad-cli-fake")

    assert isinstance(result, RenderResult)
    assert result.dpi == RENDER_DPI
    assert result.width_px == round(100 / 25.4 * RENDER_DPI)
    assert result.height_px == round(50 / 25.4 * RENDER_DPI)
    assert Path(result.image_path).name == "demo_top.png"
    assert "--side" in captured["cmd"] and "top" in captured["cmd"]


def test_render_nonzero_exit_raises(pcb_file, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "mcp.render.subprocess.run",
        lambda cmd, capture_output, timeout: subprocess.CompletedProcess(cmd, 3, b"", b"boom"),
    )
    with pytest.raises(ToolExecutionError, match="exit 3"):
        render_board(pcb_file, tmp_path / "out", kicad_cli="kicad-cli-fake")


def test_render_timeout_raises(pcb_file, tmp_path, monkeypatch):
    def fake_run(cmd, capture_output, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr("mcp.render.subprocess.run", fake_run)
    with pytest.raises(ToolExecutionError, match="timed out"):
        render_board(pcb_file, tmp_path / "out", kicad_cli="kicad-cli-fake")


# --- live integration (skipped without local KiCad + fixture) ----------------


STICKHUB = Path(__file__).resolve().parents[2] / "fixtures" / "stickhub" / "StickHub.kicad_pcb"


@pytest.mark.skipif(
    find_kicad_cli() is None or not STICKHUB.is_file(),
    reason="requires local kicad-cli and fixtures/stickhub",
)
def test_live_render_stickhub(tmp_path):
    result = render_board(STICKHUB, tmp_path)
    assert Path(result.image_path).is_file()
    assert (result.width_px, result.height_px) == png_dimensions(result.image_path)
    assert 0 < result.dpi <= RENDER_DPI + 1e-6
    assert max(result.width_px, result.height_px) <= MAX_EDGE_PX
