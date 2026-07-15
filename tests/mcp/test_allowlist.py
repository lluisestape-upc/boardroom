"""Allowlist enforcement: the check happens in code, before cache or server."""

from __future__ import annotations

import pytest

from mcp.allowlist import (
    DEFAULT_ALLOWLIST,
    KNOWN_AGENTS,
    AllowlistRegistry,
    WILDCARD,
)
from mcp.adapters import registered_tools
from mcp.errors import ToolNotAllowedError, UnknownAgentError


@pytest.fixture
def registry(tmp_path):
    # Point at a nonexistent registry.yaml so defaults apply deterministically.
    return AllowlistRegistry(registry_path=tmp_path / "registry.yaml")


def test_known_agents_match_schema_enum(registry):
    assert set(registry.agents()) == set(KNOWN_AGENTS)


def test_specialist_allowed_and_denied(registry):
    assert registry.is_allowed("power_integrity", "extract_power_domains")
    assert not registry.is_allowed("power_integrity", "run_drc")
    with pytest.raises(ToolNotAllowedError):
        registry.check("power_integrity", "run_drc")


def test_moderator_wildcard(registry):
    assert WILDCARD in registry.allowed_tools("moderator")
    for tool in registered_tools():
        assert registry.is_allowed("moderator", tool)


def test_unknown_agent_raises(registry):
    with pytest.raises(UnknownAgentError):
        registry.allowed_tools("marketing")


def test_registry_yaml_overrides_defaults(tmp_path):
    path = tmp_path / "registry.yaml"
    reg = AllowlistRegistry(registry_path=path)
    assert reg.allowed_tools("power_integrity") == DEFAULT_ALLOWLIST["power_integrity"]

    path.write_text(
        "agents:\n  power_integrity:\n    model: qwen-flash\n    tools: [run_erc]\n",
        encoding="utf-8",
    )
    assert reg.allowed_tools("power_integrity") == frozenset({"run_erc"})
    # Non-overridden agents keep their defaults.
    assert reg.allowed_tools("connectivity_erc") == DEFAULT_ALLOWLIST["connectivity_erc"]


def test_invalid_registry_yaml_keeps_defaults(tmp_path):
    path = tmp_path / "registry.yaml"
    path.write_text("agents: [unclosed", encoding="utf-8")
    reg = AllowlistRegistry(registry_path=path)
    assert reg.allowed_tools("power_integrity") == DEFAULT_ALLOWLIST["power_integrity"]


@pytest.mark.asyncio
async def test_toolbox_denies_before_any_server_or_cache_access(registry, fake_session, cache):
    box = registry.toolbox("power_integrity", fake_session, cache)
    with pytest.raises(ToolNotAllowedError):
        await box.call("run_drc", {"pcb_path": "C:/boards/demo/demo.kicad_pcb"})
    assert fake_session.calls == []  # never reached the server
    assert len(cache) == 0  # never touched the cache


@pytest.mark.asyncio
async def test_toolbox_allows_and_returns_evidence(registry, fake_session, cache):
    box = registry.toolbox("power_integrity", fake_session, cache)
    outcome = await box.call(
        "extract_power_domains", {"schematic_path": "C:/boards/demo/demo.kicad_sch"}
    )
    assert outcome.evidence.evidence_id == "EV-0001"
    assert outcome.evidence.tool == "extract_power_domains"


def test_toolbox_unknown_agent_fails_fast(registry, fake_session, cache):
    with pytest.raises(UnknownAgentError):
        registry.toolbox("intern", fake_session, cache)


def test_real_registry_yaml_is_compatible():
    """The actual society/registry.yaml (society-engineer's file) must parse and
    only reference agents from the schema enum."""
    reg = AllowlistRegistry()  # default path: society/registry.yaml
    if not reg.registry_path.exists():
        pytest.skip("society/registry.yaml not present")
    for agent in KNOWN_AGENTS:
        tools = reg.allowed_tools(agent)
        assert tools, f"{agent} has an empty allowlist"
