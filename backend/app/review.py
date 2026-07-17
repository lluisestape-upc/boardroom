"""Live review entrypoint: run the full BoardRoom society over a KiCad project.

    python -m backend.app.review <project_dir> [--out review.json]

Wires a live KiCad MCP session + the tool-driven runner + MCP manifest builder
into the Moderator, then writes the signed review.json. Requires DASHSCOPE_API_KEY
and a reachable kicad-mcp-server (KICAD_MCP_COMMAND). This is also the single place
the benchmark's execute_review seam calls into.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from mcp.allowlist import AllowlistRegistry
from mcp.client import KicadMCPClient
from mcp.evidence import EvidenceCache

from .interfaces import AgentConfig, load_agent_configs
from .moderator import Moderator
from .qwen_client import QwenClient
from .runner import McpManifestBuilder, ToolDrivenSpecialistRunner
from .sessions import SessionStore


class _ToolLayerAdapter:
    """Bridges the mcp toolbox to the Moderator's ToolLayer protocol (debate calls)."""

    def __init__(self, session, cache, registry: AllowlistRegistry):
        self._session, self._cache, self._registry = session, cache, registry

    async def call_tool(self, *, agent: str, tool: str, arguments: dict):
        outcome = await self._registry.toolbox(agent, self._session, self._cache).call(tool, arguments)
        from .interfaces import EvidenceRecord

        return EvidenceRecord(evidence_id=outcome.evidence.evidence_id, tool=tool,
                              output=outcome.evidence.summary)


async def run_review(project_dir: str, *, sessions_dir: str | None = None) -> dict:
    """Run one full live review; return the signed review dict."""
    registry = AllowlistRegistry()
    cache = EvidenceCache(session_id=Path(project_dir).name)
    client = QwenClient()
    store = SessionStore(sessions_dir)

    async with KicadMCPClient() as mcp_session:
        runner = ToolDrivenSpecialistRunner(
            session=mcp_session, cache=cache, registry=registry, model_client=client
        )
        manifest_builder = McpManifestBuilder(
            session=mcp_session, cache=cache, registry=registry
        )
        moderator = Moderator(
            store=store,
            model_client=client,
            specialist_runner=runner,
            agent_configs=load_agent_configs(),
            manifest_builder=manifest_builder,
            tool_layer=_ToolLayerAdapter(mcp_session, cache, registry),
        )
        session = store.create(str(project_dir))
        await moderator.run_review(session.id)

    return store.read_review(session.id)


async def run_baseline_review(project_dir: str, *, sessions_dir: str | None = None) -> dict:
    """Single-agent baseline: one qwen3-max agent with ALL tools reviews the whole
    board. Same review.json shape as run_review, for the benchmark comparison.
    """
    # Fair baseline: it must genuinely get EVERY tool. society/registry.yaml scopes
    # "moderator" down to 3 overview tools, so point the registry at a nonexistent
    # file to fall back on DEFAULT_ALLOWLIST, where moderator is a wildcard (= all
    # registered adapters). A tool-starved baseline would be a strawman.
    registry = AllowlistRegistry(registry_path=Path(project_dir) / "__no_registry__.yaml")
    cache = EvidenceCache(session_id=Path(project_dir).name + "-baseline")
    client = QwenClient()

    async with KicadMCPClient() as mcp_session:
        runner = ToolDrivenSpecialistRunner(
            session=mcp_session, cache=cache, registry=registry, model_client=client,
            max_tool_rounds=16,  # one agent covers everything, so allow more tool calls
        )
        cfg = AgentConfig(name="moderator", model="qwen3-max",
                          prompt_path="society/prompts/_baseline.md")
        manifest_builder = McpManifestBuilder(session=mcp_session, cache=cache, registry=registry)
        manifest = await manifest_builder.build(project_dir)
        findings = await runner.run(config=cfg, session_id="baseline",
                                    project_path=project_dir, manifest=manifest)

    return {
        "config": "baseline",
        "board_id": Path(project_dir).name,
        "findings": findings,
        "rejected_findings": 0,
        "token_accounting": client.ledger.snapshot(),
        "render": manifest.get("render"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run a BoardRoom review over a KiCad project")
    ap.add_argument("project_dir")
    ap.add_argument("--out", default=None, help="write review.json here (default: stdout summary)")
    ap.add_argument("--sessions-dir", default=None)
    args = ap.parse_args(argv)

    review = asyncio.run(run_review(args.project_dir, sessions_dir=args.sessions_dir))

    findings = review.get("findings", [])
    print(f"state: signed | findings: {len(findings)} | "
          f"rejected: {len(review.get('rejected_findings', []))} | "
          f"debates: {len(review.get('debates', []))}")
    for f in findings:
        print(f"  [{f.get('severity','?'):8}] {f.get('agent','?'):16} {f.get('claim','')[:80]}")
    tokens = review.get("token_accounting", {})
    if tokens:
        print("tokens:", json.dumps(tokens))
    if args.out:
        Path(args.out).write_text(json.dumps(review, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
