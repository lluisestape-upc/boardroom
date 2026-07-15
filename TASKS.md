# BoardRoom Task Board

Deadline: **Sun Jul 20, 23:00 GMT+2**. Owners are `.claude/agents/*`; `[LLUIS]` =
manual. Mark done with commit hash.

> 2026-07-16: Day 1 fully done (commit d1840d1, 111/111 tests). The external
> Antigravity workstream delivered report/ v1 and is discontinued — remaining
> `[AG]` items are now owned by `frontend-engineer`.

## Day 1 — Wed Jul 16 · skeleton runs end-to-end (mocked)

- [ ] `mcp-engineer` — stdio client to kicad-mcp-server + adapters for ERC/DRC,
      netlist, power-domain tools; evidence cache with ids; fake-server test fixture
- [ ] `society-engineer` — qwen_client.py (OpenAI-compatible endpoint, routing table,
      token counters); registry.yaml; prompts for ERC + Power specialists
- [ ] `orchestrator-engineer` — FastAPI app, session state machine, dispatch of 2
      specialists (mocked models), finding validation at boundary
- [ ] `[LLUIS]` — accounts + API key (see orders); create GitHub repo, first push
- [ ] `[AG]` — start report/ against finding.schema.json + self-generated sample data

## Day 2 — Thu Jul 17 · real reviews on a real board

- [ ] `mcp-engineer` — remaining adapters (SI, pins, firmware, stats) + board
      render.py (kicad-cli → PNG)
- [ ] `society-engineer` — all 6 prompts done; VL layout critic wired with renders;
      live smoke run of one full review on a real KiCad project
- [ ] `orchestrator-engineer` — conflict detection + bounded debate + evidence-cited
      rulings; debate transcript persisted
- [ ] `qa-reviewer` — first full-repo review pass
- [ ] `architect` — sign off protocol implementation matches NEGOTIATION_PROTOCOL.md

## Day 3 — Fri Jul 18 · benchmark + deployment

- [ ] `benchmark-engineer` — corpus (5–10 boards) + seed.py + ground truth manifests;
      baseline config (single qwen3-max, all tools); first full run, both configs
- [ ] `deploy-engineer` — Docker image with KiCad working; deploy/alibaba/ OSS
      integration; deploy runbook
- [ ] `[LLUIS]` — Alibaba Cloud account ready; run deploy; verify smoke.sh against
      the deployed instance
- [ ] `[AG]` — report/ views 1–3 done (blast-radius, debate viewer, board overlay)

## Day 4 — Sat Jul 19 · results + polish

- [ ] `benchmark-engineer` — final runs, metrics.py tables + charts
- [ ] `orchestrator-engineer` — serve report/dist from FastAPI; session list endpoint
- [ ] `docs-producer` — README final, diagram exported PNG, VIDEO_SCRIPT.md,
      DEVPOST.md, BLOG_DRAFT.md
- [ ] `qa-reviewer` — end-to-end verification: fresh clone → quickstart → review →
      report; benchmark integrity check
- [ ] `[AG]` — report/ views 4–5 + polish; QUESTIONS.md resolved

## Day 5 — Sun Jul 20 · submission (finish by 20:00, buffer to 23:00)

- [ ] `[LLUIS]` — record video per script; upload YouTube (public)
- [ ] `[LLUIS]` — GitHub About: set description + license visibility; final push
- [ ] `[LLUIS]` — Devpost submission: repo URL, video URL, description, Track 3,
      optional blog URL
- [ ] `docs-producer` — final pass: every README link works, quickstart re-verified
