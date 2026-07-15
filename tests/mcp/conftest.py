"""Fixtures for the mcp package tests: an in-process fake KiCad MCP session
(no real KiCad or server process needed). The fake itself lives in
``fake_kicad.py`` — import it from there, never from ``conftest``."""

from __future__ import annotations

import pytest

from fake_kicad import FakeKicadSession
from mcp.evidence import EvidenceCache


@pytest.fixture
def fake_session() -> FakeKicadSession:
    return FakeKicadSession()


@pytest.fixture
def cache() -> EvidenceCache:
    return EvidenceCache(session_id="test-session")
