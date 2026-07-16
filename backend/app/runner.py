"""Tool-driven specialist runner + MCP-backed manifest builder.

Replaces the Day-1 single-shot placeholders in moderator.py. A specialist is
handed ONLY the KiCad MCP tools in its allowlist (enforced by mcp/allowlist.py),
exposed to the model as OpenAI function-calling specs generated from each
adapter's pydantic request model. The model calls tools; every result is cached
with a stable evidence id; the specialist then emits a JSON findings array whose
evidence ids must reference real cached results (society/findings.py rejects the
rest — the hallucination guard). The dfm_layout critic additionally receives the
rendered board PNG as a multimodal image part (qwen3-vl).

Import-time must not require the MCP server or an API key: heavy deps are imported
lazily and construction takes already-built collaborators.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from mcp.adapters import get_adapter, registered_tools
from mcp.allowlist import AllowlistRegistry
from mcp.client import SupportsCallTool
from mcp.errors import BoardRoomMcpError
from mcp.evidence import EvidenceCache
from society.findings import parse_and_validate, rejection_report

from .interfaces import AgentConfig
from .qwen_client import AssistantTurn, image_part, text_part

REPO_ROOT = Path(__file__).resolve().parents[2]
MAX_TOOL_ROUNDS = 8
MAX_FINDING_RETRIES = 1
RENDER_TOOL = "render_board"


# --------------------------------------------------------------------------
# Tool-spec generation (adapter pydantic request model -> OpenAI function spec)
# --------------------------------------------------------------------------


def tool_spec(tool: str) -> dict:
    """OpenAI function-calling spec for one KiCad MCP tool."""
    if tool == RENDER_TOOL:
        return {
            "type": "function",
            "function": {
                "name": RENDER_TOOL,
                "description": "Render the board's copper+silk to a PNG image you can see.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "side": {"type": "string", "enum": ["top", "bottom"], "default": "top"}
                    },
                },
            },
        }
    adapter = get_adapter(tool)
    schema = adapter.request_model.model_json_schema()
    schema.pop("title", None)
    return {
        "type": "function",
        "function": {
            "name": tool,
            "description": (adapter.description or f"KiCad MCP tool: {tool}").strip(),
            "parameters": schema,
        },
    }


def specs_for_tools(tools: list[str]) -> list[dict]:
    """Specs for every tool that has an adapter; silently skip those that don't
    (a registry tool whose adapter hasn't landed shouldn't sink the whole
    specialist — it just isn't offered)."""
    specs = []
    for t in tools:
        try:
            specs.append(tool_spec(t))
        except BoardRoomMcpError:
            continue
    return specs


# --------------------------------------------------------------------------
# Specialist runner
# --------------------------------------------------------------------------


class ToolDrivenSpecialistRunner:
    """SpecialistRunner: function-calling loop over an agent's allowed tools.

    Construction is per review (shared evidence cache + live MCP session). The
    Moderator calls ``run`` once per specialist, concurrently.
    """

    def __init__(
        self,
        *,
        session: SupportsCallTool,
        cache: EvidenceCache,
        registry: AllowlistRegistry,
        model_client: Any,
        repo_root: str | Path = REPO_ROOT,
        max_tool_rounds: int = MAX_TOOL_ROUNDS,
    ) -> None:
        self._session = session
        self._cache = cache
        self._registry = registry
        self._model = model_client
        self._repo_root = Path(repo_root)
        self._max_rounds = max_tool_rounds

    def _system_prompt(self, config: AgentConfig, manifest: dict) -> str:
        base = ""
        if config.prompt_path:
            p = self._repo_root / config.prompt_path
            if p.is_file():
                base = p.read_text(encoding="utf-8")
        return (
            base
            + "\n\n## Project under review\n"
            + json.dumps(_manifest_digest(manifest), indent=2)
            + "\n\nCall your tools to gather evidence, then output the findings array."
        )

    async def run(
        self, *, config: AgentConfig, session_id: str, project_path: str, manifest: dict
    ) -> list[dict]:
        toolbox = self._registry.toolbox(config.name, self._session, self._cache)
        allowed = sorted(toolbox.allowed_tools())
        specs = specs_for_tools(allowed)

        messages: list[dict] = [
            {"role": "system", "content": self._system_prompt(config, manifest)},
            {"role": "user", "content": f"Review the project at {project_path}. Begin."},
        ]

        rendered_image_sent = False
        for _ in range(self._max_rounds):
            turn: AssistantTurn = await self._model.chat_with_tools(
                agent=config.name, model=config.model, messages=messages, tools=specs
            )
            if not turn.wants_tools:
                messages.append({"role": "assistant", "content": turn.content or ""})
                break
            messages.append(
                {
                    "role": "assistant",
                    "content": turn.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                        }
                        for tc in turn.tool_calls
                    ],
                }
            )
            for tc in turn.tool_calls:
                tool_msg, image = await self._execute(config, tc, project_path, rendered_image_sent)
                messages.append(tool_msg)
                if image is not None:
                    messages.append(image)
                    rendered_image_sent = True

        # Final: demand the findings array (JSON), then validate against real evidence.
        messages.append(
            {
                "role": "user",
                "content": (
                    "Output ONLY the JSON array of findings now, each citing evidence_id(s) "
                    "you received. Return [] if nothing actionable."
                ),
            }
        )
        return await self._collect_findings(config, messages)

    async def _execute(
        self, config: AgentConfig, tc, project_path: str, image_already_sent: bool
    ) -> tuple[dict, dict | None]:
        """Run one tool call; return (tool-role message, optional image message)."""
        if tc.name == RENDER_TOOL:
            return await self._execute_render(config, tc, project_path, image_already_sent)
        try:
            outcome = await self._registry.toolbox(
                config.name, self._session, self._cache
            ).call(tc.name, tc.arguments)
        except BoardRoomMcpError as exc:
            return self._tool_error(tc, str(exc)), None
        payload = {
            "evidence_id": outcome.evidence.evidence_id,
            "tool": tc.name,
            "summary": outcome.evidence.summary,
            "data": _digest(outcome.data),
        }
        return _tool_message(tc, payload), None

    async def _execute_render(
        self, config: AgentConfig, tc, project_path: str, image_already_sent: bool
    ) -> tuple[dict, dict | None]:
        from mcp.render import render_board  # lazy: pulls kicad-cli discovery

        pcb = _find_pcb(project_path)
        if pcb is None:
            return self._tool_error(tc, "no .kicad_pcb in project; cannot render"), None
        try:
            result = render_board(pcb, Path(project_path) / "_boardroom_renders",
                                  side=tc.arguments.get("side", "top"))
        except BoardRoomMcpError as exc:
            return self._tool_error(tc, f"render unavailable: {exc}"), None
        entry = self._cache.put(
            RENDER_TOOL,
            {"side": tc.arguments.get("side", "top"), "pcb": str(pcb)},
            raw=result.image_path,
            summary=f"board render {result.width_px}x{result.height_px}px @ {result.dpi:.0f}dpi",
        )
        payload = {
            "evidence_id": entry.evidence_id,
            "tool": RENDER_TOOL,
            "summary": entry.summary,
            "data": {"image": Path(result.image_path).name, "width_px": result.width_px,
                     "height_px": result.height_px, "dpi": result.dpi},
        }
        image_msg = None
        if not image_already_sent:  # cap: one image per run
            image_msg = {
                "role": "user",
                "content": [
                    text_part(f"Board render (evidence {entry.evidence_id}); box findings on it:"),
                    image_part(_data_uri(result.image_path)),
                ],
            }
        return _tool_message(tc, payload), image_msg

    async def _collect_findings(self, config: AgentConfig, messages: list[dict]) -> list[dict]:
        known = {e.evidence_id for e in self._cache.entries()}
        raw = await self._model.chat(
            agent=config.name, model=config.model, messages=messages,
            response_format={"type": "json_object"},
        )
        valid, rejected = parse_and_validate(raw, known_evidence_ids=known)
        if rejected and not valid:
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content":
                             "Some findings were rejected:\n" + rejection_report(rejected) +
                             "\nReturn a corrected JSON array using only real evidence ids."})
            raw2 = await self._model.chat(
                agent=config.name, model=config.model, messages=messages,
                response_format={"type": "json_object"},
            )
            valid, _ = parse_and_validate(raw2, known_evidence_ids=known)
        return valid

    @staticmethod
    def _tool_error(tc, message: str) -> dict:
        return _tool_message(tc, {"tool": tc.name, "error": message})


# --------------------------------------------------------------------------
# MCP-backed manifest builder
# --------------------------------------------------------------------------


class McpManifestBuilder:
    """ManifestBuilder: schematic/PCB overview via MCP + optional board render (ruling 1A)."""

    def __init__(
        self,
        *,
        session: SupportsCallTool,
        cache: EvidenceCache,
        registry: AllowlistRegistry,
        repo_root: str | Path = REPO_ROOT,
    ) -> None:
        self._session = session
        self._cache = cache
        self._registry = registry
        self._repo_root = Path(repo_root)

    async def build(self, project_path: str) -> dict:
        root = Path(project_path)
        if not root.is_dir():
            raise FileNotFoundError(f"not a directory: {project_path}")
        sch = _find_first(root, ".kicad_sch")
        pcb = _find_first(root, ".kicad_pcb")
        box = self._registry.toolbox("moderator", self._session, self._cache)

        manifest: dict[str, Any] = {
            "project_path": str(root),
            "schematic": str(sch.relative_to(root)) if sch else None,
            "pcb": str(pcb.relative_to(root)) if pcb else None,
            "builder": "mcp",
            "notes": [],
        }
        if sch:
            manifest["schematic_info"] = await _safe_tool(box, "get_schematic_info",
                                                          {"schematic_path": str(sch)}, manifest)
        if pcb:
            manifest["pcb_statistics"] = await _safe_tool(box, "get_pcb_statistics",
                                                          {"pcb_path": str(pcb)}, manifest)
            self._maybe_render(pcb, root, manifest)
        else:
            manifest["notes"].append("no .kicad_pcb — dfm_layout / signal_integrity limited")
        return manifest

    def _maybe_render(self, pcb: Path, root: Path, manifest: dict) -> None:
        from mcp.render import find_kicad_cli, render_board

        if find_kicad_cli() is None:
            manifest["notes"].append("kicad-cli unavailable — no board render")
            return
        try:
            result = render_board(pcb, root / "_boardroom_renders")
        except BoardRoomMcpError as exc:
            manifest["notes"].append(f"render failed: {exc}")
            return
        manifest["render"] = {
            "image": Path(result.image_path).name,
            "width_px": result.width_px,
            "height_px": result.height_px,
            "dpi": result.dpi,
        }


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _manifest_digest(manifest: dict) -> dict:
    keep = ("schematic", "pcb", "schematic_info", "pcb_statistics", "notes", "render")
    return {k: manifest[k] for k in keep if k in manifest}


def _digest(data: Any, limit: int = 4000) -> Any:
    """Compact, JSON-safe view of an adapter's typed output for a tool message."""
    try:
        dumped = data.model_dump() if hasattr(data, "model_dump") else data
    except Exception:
        dumped = str(data)
    s = json.dumps(dumped, default=str)
    if len(s) <= limit:
        return dumped
    return {"_truncated": s[:limit]}


def _tool_message(tc, payload: dict) -> dict:
    return {"role": "tool", "tool_call_id": tc.id, "content": json.dumps(payload, default=str)}


def _data_uri(image_path: str) -> str:
    raw = Path(image_path).read_bytes()
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def _find_first(root: Path, suffix: str) -> Path | None:
    matches = sorted(root.rglob(f"*{suffix}"))
    return matches[0] if matches else None


def _find_pcb(project_path: str) -> Path | None:
    return _find_first(Path(project_path), ".kicad_pcb")


async def _safe_tool(box, tool: str, args: dict, manifest: dict) -> dict | None:
    try:
        outcome = await box.call(tool, args)
        return _digest(outcome.data)
    except BoardRoomMcpError as exc:
        manifest["notes"].append(f"{tool} failed: {exc}")
        return None
