"""API endpoints via httpx ASGI transport, with fakes injected through create_app."""

import asyncio

import httpx
import pytest

from backend.app.interfaces import AgentConfig
from backend.app.main import create_app
from fakes import (
    TWO_SPECIALISTS,
    FakeManifestBuilder,
    FakeModelClient,
    FakeSpecialistRunner,
    make_finding,
)


def make_client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


def make_app(tmp_path, runner, **overrides):
    return create_app(
        sessions_dir=tmp_path / "sessions",
        model_client=FakeModelClient(),
        specialist_runner=runner,
        agent_configs=TWO_SPECIALISTS,
        manifest_builder=FakeManifestBuilder(),
        **overrides,
    )


@pytest.fixture
def kicad_project(tmp_path):
    project = tmp_path / "board"
    project.mkdir()
    (project / "board.kicad_pro").write_text("{}", encoding="utf-8")
    return project


@pytest.mark.asyncio
async def test_health(tmp_path):
    app = make_app(tmp_path, FakeSpecialistRunner())
    async with make_client(app) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_full_review_flow(tmp_path, kicad_project):
    runner = FakeSpecialistRunner(
        findings_by_agent={
            "connectivity_erc": [make_finding("ERC-001", "connectivity_erc")],
            "power_integrity": [make_finding("PI-001", "power_integrity")],
        },
        crash_agents=set(),
    )
    app = make_app(tmp_path, runner)
    async with make_client(app) as client:
        resp = await client.post("/sessions", json={"project_path": str(kicad_project)})
        assert resp.status_code == 201
        session_id = resp.json()["id"]
        assert resp.json()["state"] == "created"

        await app.state.review_tasks[session_id]  # deterministic: run to completion

        status = (await client.get(f"/sessions/{session_id}")).json()
        assert status["state"] == "signed"
        assert status["progress"]["specialists_total"] == 2
        assert status["progress"]["specialists_completed"] == 2
        assert status["error"] is None

        resp = await client.get(f"/sessions/{session_id}/review")
        assert resp.status_code == 200
        review = resp.json()
        assert {f["id"] for f in review["findings"]} == {"ERC-001", "PI-001"}
        assert review["session_id"] == session_id


@pytest.mark.asyncio
async def test_review_409_until_signed_then_200(tmp_path, kicad_project):
    release = asyncio.Event()

    class BlockingRunner:
        async def run(self, *, config, session_id, project_path, manifest):
            await release.wait()
            return [make_finding(f"{config.name[:2].upper()}-001", config.name)]

    app = make_app(tmp_path, BlockingRunner())
    async with make_client(app) as client:
        session_id = (
            await client.post("/sessions", json={"project_path": str(kicad_project)})
        ).json()["id"]
        await asyncio.sleep(0)  # let the review task reach the specialists

        resp = await client.get(f"/sessions/{session_id}/review")
        assert resp.status_code == 409  # not ready yet
        assert "signed" in resp.json()["detail"]

        release.set()
        await app.state.review_tasks[session_id]

        resp = await client.get(f"/sessions/{session_id}/review")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_crashed_specialist_visible_in_status_and_review(tmp_path, kicad_project):
    runner = FakeSpecialistRunner(
        findings_by_agent={"connectivity_erc": [make_finding("ERC-001", "connectivity_erc")]},
        crash_agents={"power_integrity"},
    )
    app = make_app(tmp_path, runner)
    async with make_client(app) as client:
        session_id = (
            await client.post("/sessions", json={"project_path": str(kicad_project)})
        ).json()["id"]
        await app.state.review_tasks[session_id]

        status = (await client.get(f"/sessions/{session_id}")).json()
        assert status["state"] == "signed"
        assert status["coverage_notes"][0]["agent"] == "power_integrity"

        review = (await client.get(f"/sessions/{session_id}/review")).json()
        assert len(review["coverage_notes"]) == 1


@pytest.mark.asyncio
async def test_post_sessions_rejects_missing_directory(tmp_path):
    app = make_app(tmp_path, FakeSpecialistRunner())
    async with make_client(app) as client:
        resp = await client.post(
            "/sessions", json={"project_path": str(tmp_path / "does-not-exist")}
        )
    assert resp.status_code == 400
    assert "not an existing directory" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_unknown_session_404s(tmp_path):
    app = make_app(tmp_path, FakeSpecialistRunner())
    async with make_client(app) as client:
        assert (await client.get("/sessions/deadbeef")).status_code == 404
        assert (await client.get("/sessions/deadbeef/review")).status_code == 404


@pytest.mark.asyncio
async def test_sessions_survive_restart_via_new_app_over_same_dir(
    tmp_path, kicad_project
):
    runner = FakeSpecialistRunner(
        findings_by_agent={
            "connectivity_erc": [make_finding("ERC-001", "connectivity_erc")]
        }
    )
    configs = [AgentConfig(name="connectivity_erc", model="fake")]
    app1 = create_app(
        sessions_dir=tmp_path / "sessions",
        model_client=FakeModelClient(),
        specialist_runner=runner,
        agent_configs=configs,
        manifest_builder=FakeManifestBuilder(),
    )
    async with make_client(app1) as client:
        session_id = (
            await client.post("/sessions", json={"project_path": str(kicad_project)})
        ).json()["id"]
        await app1.state.review_tasks[session_id]

    # "restart": a brand-new app instance over the same sessions dir
    app2 = create_app(
        sessions_dir=tmp_path / "sessions",
        model_client=FakeModelClient(),
        specialist_runner=runner,
        agent_configs=configs,
        manifest_builder=FakeManifestBuilder(),
    )
    async with make_client(app2) as client:
        status = (await client.get(f"/sessions/{session_id}")).json()
        assert status["state"] == "signed"
        review = (await client.get(f"/sessions/{session_id}/review")).json()
        assert [f["id"] for f in review["findings"]] == ["ERC-001"]
