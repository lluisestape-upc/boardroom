# Antigravity Workstream Brief — `report/` (BoardRoom review frontend)

You are building the **entire `report/` directory** of BoardRoom, a multi-agent PCB
design review system for the Qwen Cloud hackathon (Track 3). You own this directory
exclusively; the rest of the repo is built by a separate team. **Do not modify any
file outside `report/`.**

## What to build

A self-contained, static, interactive review viewer: given a `review.json` produced by
the backend, render the review a human engineer would actually want to read.

**Input contract (FROZEN — do not change, do not extend):**
- `review.json`: an object with `session_id`, `project_name`, `findings` (array of
  Finding objects per `docs/schemas/finding.schema.json` — read that file, it is the
  single source of truth), `token_accounting` (per-agent
  `{agent, model, prompt_tokens, completion_tokens}`), and `coverage_notes` (strings).
- Board render PNGs referenced by findings' `board_region.image`, in the same folder.
- If you need a field that doesn't exist, note it in report/QUESTIONS.md — do not
  invent fields or edit the schema.

**Views (priority order):**
1. **Blast-radius graph** — force-directed or radial graph: findings → affected nets →
   affected components. Node color by severity (critical red → info gray), edge hover
   highlights the finding. This is the hero visual of the demo video; it should look
   striking within 2 seconds of loading.
2. **Debate viewer** — for contested findings: the two agents' positions per round,
   the extra evidence each pulled, and the Moderator's ruling with its cited evidence
   highlighted. Chat-transcript style, clearly labeled rounds (max 2).
3. **Board overlay** — the board render PNG with `board_region` bounding boxes drawn
   for findings that have one; click a box → jump to the finding.
4. **Findings table** — sortable by severity/agent/status; expandable rows showing
   evidence entries and recommendation.
5. **Token panel** — small stacked bar of tokens per agent/model (the efficiency
   story at a glance).

## Constraints

- **Static only**: plain HTML/CSS/JS or a Vite+React app that builds to static files
  (`report/dist/`). It will be served by FastAPI StaticFiles and must also work when
  opened via `file://` with a bundled sample review.
- No backend calls, no external CDNs at runtime (judges may be offline) — bundle
  everything. D3 or vis-network bundled locally is fine.
- Ship with `report/sample/review.sample.json` + a sample board PNG so the UI is
  developable and demoable standalone. Generate realistic sample data yourself from
  the schema (e.g., 12 findings across 5 agents, 2 contested with full debates, one
  merged ruling).
- Dark theme default (demo video is dark-themed), light theme optional.
- Keep it dependency-light and readable; this repo goes public and gets judged on
  code quality.

## Deliverables checklist

- [ ] report/ app with the 5 views above
- [ ] report/sample/ with realistic sample data (works standalone)
- [ ] report/README.md — how to build/run, and how the backend serves it
- [ ] report/QUESTIONS.md — anything unclear or any field you wished existed

Definition of done: opening the sample review shows the blast-radius graph, a full
debate transcript, and the board overlay without any backend running.
