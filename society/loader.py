"""Load and validate society/registry.yaml — the single source of truth.

Registry -> pydantic models, plus helpers to build a ready-to-dispatch agent
config (system prompt text + model id + tool allowlist). Agent names are
validated against the ``agent`` enum in docs/schemas/finding.schema.json so the
registry can never drift from the frozen finding contract.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = REPO_ROOT / "society" / "registry.yaml"
FINDING_SCHEMA_PATH = REPO_ROOT / "docs" / "schemas" / "finding.schema.json"


@lru_cache(maxsize=1)
def allowed_agent_names() -> frozenset[str]:
    """The ``agent`` enum from the frozen finding schema."""
    with FINDING_SCHEMA_PATH.open(encoding="utf-8") as f:
        schema = json.load(f)
    return frozenset(schema["properties"]["agent"]["enum"])


class AgentSpec(BaseModel):
    """One agent's row in the registry: pure data, no behavior."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    model: str
    prompt: str = Field(description="Prompt file path relative to the repo root")
    tools: list[str] = Field(default_factory=list)


class Registry(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    version: int
    agents: dict[str, AgentSpec]


class AgentConfig(BaseModel):
    """Everything the orchestrator needs to dispatch one agent."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    name: str
    model: str
    system_prompt: str
    tools: list[str]


class RegistryError(ValueError):
    """Registry content is invalid (unknown agent names, missing prompt files...)."""


def load_registry(path: str | Path = DEFAULT_REGISTRY_PATH) -> Registry:
    """Parse registry.yaml and validate agent names against the finding schema enum.

    Prompt-file existence is NOT checked here (prompts land incrementally during
    the hackathon); use ``validate_prompt_files`` or ``build_agent`` for that.
    """
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    registry = Registry.model_validate(data)

    unknown = sorted(set(registry.agents) - allowed_agent_names())
    if unknown:
        raise RegistryError(
            f"registry agent names not in finding.schema.json agent enum: {unknown} "
            f"(allowed: {sorted(allowed_agent_names())})"
        )
    return registry


def validate_prompt_files(registry: Registry, repo_root: str | Path = REPO_ROOT) -> None:
    """Raise RegistryError if any agent's prompt file is missing."""
    repo_root = Path(repo_root)
    missing = {
        name: spec.prompt
        for name, spec in registry.agents.items()
        if not (repo_root / spec.prompt).is_file()
    }
    if missing:
        raise RegistryError(f"missing prompt files: {missing}")


def build_agent(
    registry: Registry, name: str, repo_root: str | Path = REPO_ROOT
) -> AgentConfig:
    """Resolve one agent into a dispatchable config (loads its system prompt)."""
    if name not in registry.agents:
        raise RegistryError(f"unknown agent {name!r} (registry has: {sorted(registry.agents)})")
    spec = registry.agents[name]
    prompt_path = Path(repo_root) / spec.prompt
    if not prompt_path.is_file():
        raise RegistryError(f"prompt file for agent {name!r} not found: {prompt_path}")
    system_prompt = prompt_path.read_text(encoding="utf-8")
    return AgentConfig(name=name, model=spec.model, system_prompt=system_prompt, tools=list(spec.tools))
