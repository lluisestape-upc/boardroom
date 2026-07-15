"""In-test fakes implementing the backend/app/interfaces.py Protocols.

These stand in for the concurrent workstreams (society-engineer's QwenClient,
mcp-engineer's tool layer) — Day 1 runs entirely against them.
"""

from __future__ import annotations

from backend.app.interfaces import AgentConfig


def make_finding(
    finding_id: str,
    agent: str,
    *,
    severity: str = "major",
    evidence: list[dict] | None = None,
    **overrides,
) -> dict:
    """A finding valid against docs/schemas/finding.schema.json."""
    finding = {
        "id": finding_id,
        "agent": agent,
        "claim": f"{agent} found an issue",
        "severity": severity,
        "evidence": (
            evidence
            if evidence is not None
            else [
                {
                    "evidence_id": f"ev-{finding_id}",
                    "tool": "run_erc",
                    "summary": "tool output supporting the claim",
                }
            ]
        ),
        "recommendation": "change the thing",
        "status": "open",
    }
    finding.update(overrides)
    return finding


class FakeLedger:
    def __init__(self, data: dict | None = None):
        self._data = data or {"connectivity_erc/qwen-flash": {"prompt": 10, "completion": 5, "calls": 1}}

    def snapshot(self) -> dict:
        return dict(self._data)


class FakeModelClient:
    """Matches the ModelClient protocol (and the seed QwenClient shape)."""

    def __init__(self, responses: dict[str, str] | None = None):
        self.ledger = FakeLedger()
        self.calls: list[dict] = []
        self._responses = responses or {}

    async def chat(self, *, agent: str, model: str, messages: list[dict], **kwargs) -> str:
        self.calls.append({"agent": agent, "model": model, "messages": messages})
        return self._responses.get(agent, "[]")


class FakeSpecialistRunner:
    """Returns canned findings per agent name; raises where told to."""

    def __init__(
        self,
        findings_by_agent: dict[str, list[dict]] | None = None,
        crash_agents: set[str] | None = None,
    ):
        self.findings_by_agent = findings_by_agent or {}
        self.crash_agents = crash_agents or set()
        self.ran: list[str] = []

    async def run(
        self,
        *,
        config: AgentConfig,
        session_id: str,
        project_path: str,
        manifest: dict,
    ) -> list[dict]:
        self.ran.append(config.name)
        if config.name in self.crash_agents:
            raise RuntimeError(f"{config.name} exploded mid-review")
        return self.findings_by_agent.get(config.name, [])


class FakeManifestBuilder:
    async def build(self, project_path: str) -> dict:
        return {"project_path": project_path, "kicad_files": ["board.kicad_pcb"], "builder": "fake"}


TWO_SPECIALISTS = [
    AgentConfig(name="connectivity_erc", model="fake-model"),
    AgentConfig(name="power_integrity", model="fake-model"),
]
