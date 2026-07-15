"""BoardRoom orchestrator — FastAPI entrypoint.

Endpoints (docs/ARCHITECTURE.md):
    POST /sessions              — point at a local KiCad project dir, start a review
    GET  /sessions/{id}         — status + progress
    GET  /sessions/{id}/review  — the signed review.json, 409 until signed
    GET  /health

``create_app`` is a factory so tests inject fakes for the concurrent workstreams
(model client, specialist runner, manifest builder) via backend/app/interfaces.py
Protocols. The module-level ``app`` uses production defaults: the real QwenClient
is constructed lazily per review, so importing this module never requires
DASHSCOPE_API_KEY.

Day 1: sessions accept a *local path* to a KiCad project directory; file upload
(OSS bucket) comes later. Day 4: mount report/dist as StaticFiles + session list.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .interfaces import AgentConfig, ManifestBuilder, ModelClient, SpecialistRunner
from .moderator import ModelBackedSpecialistRunner, Moderator
from .sessions import ReviewNotReady, SessionStore, UnknownSession


class CreateSessionRequest(BaseModel):
    project_path: str


def create_app(
    *,
    sessions_dir: str | Path | None = None,
    model_client: ModelClient | None = None,
    specialist_runner: SpecialistRunner | None = None,
    agent_configs: list[AgentConfig] | None = None,
    manifest_builder: ManifestBuilder | None = None,
) -> FastAPI:
    app = FastAPI(
        title="BoardRoom", description="Multi-agent PCB design review society"
    )
    store = SessionStore(sessions_dir)
    app.state.store = store
    #: session id → asyncio.Task; keeps strong refs and lets tests await completion.
    app.state.review_tasks: dict[str, asyncio.Task] = {}

    def _build_moderator() -> Moderator:
        client = model_client
        if client is None:
            # Lazy import + construct: requires DASHSCOPE_API_KEY only when a
            # review actually starts. Failure fails the session, not the app.
            from .qwen_client import QwenClient

            client = QwenClient()
        runner = specialist_runner or ModelBackedSpecialistRunner(client)
        return Moderator(
            store=store,
            model_client=client,
            specialist_runner=runner,
            agent_configs=agent_configs,
            manifest_builder=manifest_builder,
        )

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.post("/sessions", status_code=201)
    async def create_session(req: CreateSessionRequest) -> dict:
        project_dir = Path(req.project_path)
        if not project_dir.is_dir():
            raise HTTPException(
                status_code=400,
                detail=f"project_path is not an existing directory: {req.project_path}",
            )
        session = store.create(str(project_dir))

        async def _run() -> None:
            try:
                moderator = _build_moderator()
            except Exception as exc:  # e.g. DASHSCOPE_API_KEY missing
                store.fail(session.id, f"moderator init failed: {exc}")
                return
            await moderator.run_review(session.id)

        app.state.review_tasks[session.id] = asyncio.create_task(_run())
        return {"id": session.id, "state": session.state.value}

    @app.get("/sessions/{session_id}")
    async def get_session(session_id: str) -> dict:
        try:
            session = store.get(session_id)
        except UnknownSession:
            raise HTTPException(status_code=404, detail=f"unknown session: {session_id}")
        return {
            "id": session.id,
            "state": session.state.value,
            "project_path": session.project_path,
            "progress": session.progress,
            "coverage_notes": session.coverage_notes,
            "error": session.error,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        }

    @app.get("/sessions/{session_id}/review")
    async def get_review(session_id: str) -> dict:
        try:
            return store.read_review(session_id)
        except UnknownSession:
            raise HTTPException(status_code=404, detail=f"unknown session: {session_id}")
        except ReviewNotReady as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    return app


app = create_app()
