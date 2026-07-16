# BoardRoom — Multi-Agent PCB Design Review Society

Entry for the **Global AI Hackathon Series with Qwen Cloud**, Track 3 (Agent Society).
Deadline: **July 20, 2026 @ 23:00 GMT+2**. Devpost submission requires: public repo with
visible OSS license, proof of Alibaba Cloud deployment (code file using Alibaba Cloud
APIs), architecture diagram, ~3-minute public video.

## What this is

A society of specialist AI agents (power integrity, signal integrity, connectivity/ERC,
DFM/layout, firmware bring-up) that reviews real KiCad projects through the KiCad MCP
server, files evidence-backed findings, and **negotiates conflicting recommendations**
under a Moderator before issuing a signed-off review. Judged against a single-agent
baseline on a seeded-defect benchmark (recall, false positives, tokens, wall time).

## Architecture (short version)

- `backend/` — FastAPI orchestrator on Alibaba Cloud. The Moderator (qwen3-max) assigns
  scopes, runs the bounded negotiation protocol, and rules on conflicts by evidence
  weighting. Specialists run on cheap models (qwen-flash); bring-up agent uses
  qwen3-coder; layout critic uses qwen3-vl with rendered board PNGs.
- `society/` — specialist agent definitions: system prompts, tool allowlists, model
  routing table.
- `mcp/` — client adapters for the KiCad MCP server (runs alongside the backend against
  uploaded project files).
- `benchmark/` — seeded-defect corpus of open-source KiCad boards + eval harness
  (society vs. single monolithic agent).
- `report/` — interactive HTML findings report (blast-radius graph of findings →
  nets → components). Zero-dependency vanilla JS, works offline from `file://`.
  Originally built externally against ANTIGRAVITY_BRIEF.md (now the de-facto
  frontend spec); owned by the `frontend-engineer` agent since 2026-07-16. The
  JSON contract in docs/schemas/finding.schema.json remains frozen.
- `docs/` — architecture doc, negotiation protocol spec, schemas.

## Conventions

- Python 3.11+, FastAPI, httpx, pydantic v2. `pip install -r backend/requirements.txt`.
- Qwen access via Model Studio **OpenAI-compatible endpoint**:
  `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`, key in env `DASHSCOPE_API_KEY`.
  Never hardcode keys; never commit `.env`.
- Every model call goes through `backend/app/qwen_client.py` so token usage is counted
  per agent (this feeds the efficiency benchmark — do not bypass it).
- Findings must validate against `docs/schemas/finding.schema.json`. A finding without
  at least one tool-output evidence entry is invalid by construction.
- Tests: pytest, live under `tests/` mirroring package paths. Run `pytest -q` before
  claiming a task done.
- Commits: conventional style (`feat:`, `fix:`, `bench:`, `docs:`). **Never add any
  Co-Authored-By / AI attribution trailers.**

## Working model

Development is delegated to the subagent team in `.Codex/agents/`. TASKS.md is the
task board — pick up tasks by workstream, mark them done with the commit hash. The
`architect` agent owns interface contracts; changes to `finding.schema.json` or the
negotiation protocol require its sign-off. The `qa-reviewer` agent reviews every
workstream merge.
