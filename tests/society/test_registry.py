"""Registry loading + prompt-file resolution (society/loader.py)."""

from pathlib import Path

import pytest

from society import loader
from society.loader import (
    RegistryError,
    build_agent,
    load_registry,
    validate_prompt_files,
)

EXPECTED_AGENTS = {
    "moderator": "qwen3-max",
    "power_integrity": "qwen-flash",
    "signal_integrity": "qwen-flash",
    "connectivity_erc": "qwen-flash",
    "dfm_layout": "qwen3-vl-plus",
    "firmware_bringup": "qwen3-coder-plus",
}


def test_load_default_registry_has_all_six_agents():
    registry = load_registry()
    assert set(registry.agents) == set(EXPECTED_AGENTS)
    for name, model in EXPECTED_AGENTS.items():
        assert registry.agents[name].model == model, name


def test_every_agent_has_nonempty_tool_allowlist():
    registry = load_registry()
    for name, spec in registry.agents.items():
        assert spec.tools, f"{name} has an empty tool allowlist"
        assert len(spec.tools) == len(set(spec.tools)), f"{name} has duplicate tools"


def test_agent_names_match_finding_schema_enum():
    assert set(load_registry().agents) <= loader.allowed_agent_names()


def test_all_prompt_files_exist():
    validate_prompt_files(load_registry())


@pytest.mark.parametrize("name", ["connectivity_erc", "power_integrity"])
def test_build_agent_resolves_real_prompt(name):
    registry = load_registry()
    cfg = build_agent(registry, name)
    assert cfg.name == name
    assert cfg.model == "qwen-flash"
    assert len(cfg.system_prompt) > 500  # a real prompt, not a stub
    # Prompt must state the output contract and the tool allowlist by name.
    assert "finding.schema.json" in cfg.system_prompt
    assert "empty array" in cfg.system_prompt
    for tool in registry.agents[name].tools:
        assert tool in cfg.system_prompt, f"{tool} not listed in {name} prompt"


def test_build_agent_unknown_name_raises():
    registry = load_registry()
    with pytest.raises(RegistryError, match="unknown agent"):
        build_agent(registry, "thermal_analysis")


def test_registry_with_name_outside_schema_enum_rejected(tmp_path: Path):
    bad = tmp_path / "registry.yaml"
    bad.write_text(
        "version: 1\n"
        "agents:\n"
        "  thermal_analysis:\n"
        "    model: qwen-flash\n"
        "    prompt: society/prompts/thermal.md\n"
        "    tools: [run_erc]\n",
        encoding="utf-8",
    )
    with pytest.raises(RegistryError, match="thermal_analysis"):
        load_registry(bad)


def test_missing_prompt_file_caught(tmp_path: Path):
    reg = tmp_path / "registry.yaml"
    reg.write_text(
        "version: 1\n"
        "agents:\n"
        "  power_integrity:\n"
        "    model: qwen-flash\n"
        "    prompt: society/prompts/does_not_exist.md\n"
        "    tools: [extract_power_domains]\n",
        encoding="utf-8",
    )
    registry = load_registry(reg)
    with pytest.raises(RegistryError, match="missing prompt files"):
        validate_prompt_files(registry)
    with pytest.raises(RegistryError, match="not found"):
        build_agent(registry, "power_integrity")
