"""ToolDrivenSpecialistRunner + tool-spec generation + McpManifestBuilder."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# mcp test fake lives under tests/mcp
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))
from fake_kicad import FakeKicadSession  # noqa: E402

from backend.app.interfaces import AgentConfig, load_agent_configs  # noqa: E402
from backend.app.qwen_client import AssistantTurn, MockQwenClient, ToolCall  # noqa: E402
from backend.app.runner import (  # noqa: E402
    McpManifestBuilder,
    ToolDrivenSpecialistRunner,
    specs_for_tools,
    tool_spec,
)
from mcp.allowlist import AllowlistRegistry  # noqa: E402
from mcp.evidence import EvidenceCache  # noqa: E402


def test_tool_spec_from_adapter_model():
    spec = tool_spec("run_erc")
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "run_erc"
    assert spec["function"]["parameters"]["type"] == "object"


def test_render_tool_spec_has_side_enum():
    spec = tool_spec("render_board")
    assert spec["function"]["parameters"]["properties"]["side"]["enum"] == ["top", "bottom"]


def test_specs_skip_tools_without_adapters():
    specs = specs_for_tools(["run_erc", "not_a_real_tool", "get_pcb_statistics"])
    names = {s["function"]["name"] for s in specs}
    assert names == {"run_erc", "get_pcb_statistics"}


@pytest.fixture
def registry(tmp_path):
    return AllowlistRegistry(registry_path=tmp_path / "registry.yaml")  # defaults


@pytest.mark.asyncio
async def test_run_calls_tool_then_files_findings(registry):
    session = FakeKicadSession()
    cache = EvidenceCache(session_id="t")
    mock = MockQwenClient()
    # Round 1: call run_erc. Round 2: no tools (loop ends). Then final findings via chat().
    mock.register_tool_turns(
        "connectivity_erc",
        [
            AssistantTurn(content=None, tool_calls=[
                ToolCall(id="c1", name="run_erc",
                         arguments={"schematic_path": "C:/boards/demo/demo.kicad_sch"})]),
            AssistantTurn(content="done", tool_calls=[]),
        ],
    )
    # The final findings array must cite the evidence id the tool produced (EV-0001).
    mock.register("connectivity_erc",
                  '[{"id":"ERC-001","agent":"connectivity_erc","claim":"x","severity":"minor",'
                  '"evidence":[{"evidence_id":"EV-0001","tool":"run_erc","summary":"s"}],'
                  '"recommendation":"do y","status":"open"}]')

    runner = ToolDrivenSpecialistRunner(
        session=session, cache=cache, registry=registry, model_client=mock
    )
    findings = await runner.run(
        config=AgentConfig(name="connectivity_erc", model="qwen-flash",
                           prompt_path="society/prompts/connectivity_erc.md"),
        session_id="t", project_path="C:/boards/demo", manifest={"pcb": None},
    )
    assert len(findings) == 1
    assert findings[0]["evidence"][0]["evidence_id"] == "EV-0001"
    assert session.call_count("run_erc") == 1


@pytest.mark.asyncio
async def test_run_bounded_by_max_rounds(registry):
    session = FakeKicadSession()
    cache = EvidenceCache(session_id="t")
    mock = MockQwenClient()
    # Always request a tool → loop must stop at max_tool_rounds, then file [].
    mock.register_tool_turns("connectivity_erc", [
        AssistantTurn(content=None, tool_calls=[
            ToolCall(id="c", name="run_erc",
                     arguments={"schematic_path": "C:/boards/demo/demo.kicad_sch"})]),
    ])
    mock.register("connectivity_erc", "[]")
    runner = ToolDrivenSpecialistRunner(
        session=session, cache=cache, registry=registry, model_client=mock, max_tool_rounds=3
    )
    findings = await runner.run(
        config=AgentConfig(name="connectivity_erc", model="qwen-flash",
                           prompt_path="society/prompts/connectivity_erc.md"),
        session_id="t", project_path="C:/boards/demo", manifest={},
    )
    assert findings == []
    # Loop ran exactly max_tool_rounds model turns (identical tool calls dedupe at
    # the evidence cache, so the server is only hit once — that's the point).
    tool_turns = [c for c in mock.calls_for("connectivity_erc") if "tools" in c]
    assert len(tool_turns) == 3
    assert session.call_count("run_erc") == 1


@pytest.mark.asyncio
async def test_manifest_builder_without_pcb(registry, tmp_path):
    (tmp_path / "x.kicad_sch").write_text("(kicad_sch)", encoding="utf-8")
    session = FakeKicadSession()
    cache = EvidenceCache(session_id="t")
    builder = McpManifestBuilder(session=session, cache=cache, registry=registry)
    manifest = await builder.build(str(tmp_path))
    assert manifest["pcb"] is None
    assert any("no .kicad_pcb" in n for n in manifest["notes"])


def test_registry_backed_roster_excludes_moderator():
    configs = load_agent_configs()
    names = {c.name for c in configs}
    assert "moderator" not in names
    assert "connectivity_erc" in names and "dfm_layout" in names
    assert len(configs) == 5
