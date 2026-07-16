# Devpost Submission — BoardRoom

Paste-ready copy for the Devpost form. Fill ⟦placeholders⟧ from the real benchmark
before submitting.

---

## Project name
BoardRoom — a society of AI agents that reviews your PCB, and argues about it

## Elevator pitch (tagline)
Five specialist Qwen agents review a real KiCad board through the KiCad MCP server,
file evidence-backed findings, and negotiate conflicts under a Moderator — measurably
more accurate and cheaper than a single agent.

## Track
**Track 3: Agent Society**

## Inspiration
A missed decoupling cap or an I²C bus with no pull-ups turns into a multi-week board
respin. Single-LLM "PCB reviewers" miss real defects and invent fake ones with equal
confidence. Real design reviews aren't one expert — they're a board of specialists who
disagree and have to justify themselves. We wanted to build that, not another chatbot.

## What it does
BoardRoom runs a review as a society of agents:
- **Five specialists** — power integrity, signal integrity, connectivity/ERC,
  DFM & layout, and firmware bring-up — each inspects a real KiCad project through the
  **KiCad MCP server** and files findings that must cite tool-output evidence.
- **A Moderator** decomposes the review, detects conflicting recommendations, runs a
  bounded two-round debate where each side backs its case with one extra measurement,
  and rules on the evidence — producing a signed review.
- The **report** is a blast-radius graph (findings → nets → components) plus a board
  overlay from a multimodal layout critic that sees the rendered board.

## How we built it
- **Qwen on Alibaba Cloud Model Studio** (OpenAI-compatible endpoint). Model routing
  by role: `qwen3-max` for the Moderator's orchestration and rulings, `qwen-flash` for
  the tool-heavy specialists, `qwen3-vl-plus` for the multimodal layout critic,
  `qwen3-coder-plus` for firmware bring-up artifacts.
- **KiCad MCP server** (24 typed tool adapters) as the specialists' only path to the
  board; per-agent tool allowlists enforced in code.
- **Evidence-first design**: every tool result is cached with a stable evidence ID;
  any finding that doesn't cite real evidence is rejected — an in-architecture
  hallucination guard.
- **FastAPI** orchestrator, async concurrent dispatch with per-specialist crash
  isolation, JSON-persisted sessions. Per-agent token accounting through a single
  model-call gateway.
- **Benchmark harness**: KiCad demo boards with reproducibly seeded defects, scored
  society vs. a single-agent baseline on recall, false positives, hallucination rate,
  tokens, and cost.

## Alibaba Cloud deployment proof
- `backend/app/qwen_client.py` — all model calls via Model Studio (DashScope
  international endpoint).
- `deploy/alibaba/oss_store.py` — OSS object storage via the official `oss2` SDK.
- `deploy/Dockerfile` — backend + KiCad container for ECS.

## Results ⟦fill from benchmark/results⟧
On ⟦N⟧ KiCad boards with ⟦M⟧ seeded defects: the society caught **⟦X%⟧** of seeded
defects vs. **⟦Y%⟧** for a single monolithic agent, with **⟦Z%⟧** fewer false
positives and **⟦W%⟧** lower token cost. Hallucination rate: society **⟦a%⟧** vs.
baseline **⟦b%⟧**.

## Challenges
- Keeping specialists honest: the evidence-citation gate and in-code tool allowlists
  were the fix for LLMs confidently inventing defects.
- Making disagreement productive without runaway cost: bounded rounds + one extra
  measurement per side is where the value is.
- KiCad inside a container for headless board rendering.

## What's next
More board classes, a KiCad plugin front-end, and richer visual evidence
(waveforms, sub-sheet crops) attached to findings.

## Built with
Qwen (Model Studio), Alibaba Cloud OSS, Python, FastAPI, KiCad + KiCad MCP server,
Model Context Protocol, pydantic, Docker.

## Repository
https://github.com/lluisestape-upc/boardroom

## Video
⟦YouTube URL⟧
