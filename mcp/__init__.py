"""BoardRoom KiCad MCP tool layer.

This package is the typed client layer between the agent society and the
Seeed-Studio kicad-mcp-server:

- ``mcp.client``    — async stdio MCP client (spawns/talks to the server)
- ``mcp.adapters``  — typed (pydantic v2) adapters over the server's tools
- ``mcp.evidence``  — per-session tool-output cache with stable evidence ids
- ``mcp.allowlist`` — per-agent tool allowlists, enforced in code
- ``mcp.render``    — .kicad_pcb -> PNG renders for the qwen3-vl layout critic
- ``mcp.errors``    — typed errors the orchestrator can turn into
                      "scope not covered" notes

Name-collision note (important)
-------------------------------
This package is imported as top-level ``mcp`` (the repo layout is frozen in
docs/ARCHITECTURE.md), which shadows the ``mcp`` Python SDK installed from
PyPI whenever the repo root is on ``sys.path``. To keep the SDK usable we
merge namespaces: the SDK's on-disk ``mcp/`` directory is appended to this
package's ``__path__``, so non-colliding SDK submodules (``mcp.types``,
``mcp.shared``, ``mcp.server``, ``mcp.os`` ...) import normally. The single
colliding name — ``mcp.client`` (our module vs. the SDK's subpackage) — is
handled inside ``mcp/client.py``, which mounts the SDK's ``client/`` directory
as its own module ``__path__`` so ``mcp.client.session`` and
``mcp.client.stdio`` keep resolving to the SDK.

If the SDK is not installed, ``MCP_SDK_DIR`` is ``None`` and everything except
a live server connection still works (tests use a fake session).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent


def _locate_sdk_dir() -> Path | None:
    """Find the installed `mcp` SDK package directory on sys.path.

    Skips this package's own directory. Identified by the SDK's signature
    layout (``__init__.py`` + ``types.py`` + ``client/``).
    """
    for entry in sys.path:
        if not entry:
            entry = "."
        try:
            cand = (Path(entry) / "mcp").resolve()
        except OSError:  # pragma: no cover - malformed sys.path entry
            continue
        if cand == _PKG_DIR or not cand.is_dir():
            continue
        if (
            (cand / "__init__.py").is_file()
            and (cand / "types.py").is_file()
            and (cand / "client").is_dir()
        ):
            return cand
    return None


MCP_SDK_DIR: Path | None = _locate_sdk_dir()

if MCP_SDK_DIR is not None and str(MCP_SDK_DIR) not in __path__:
    # Merge the SDK's namespace into ours (see module docstring).
    __path__.append(str(MCP_SDK_DIR))

__all__ = ["MCP_SDK_DIR"]
