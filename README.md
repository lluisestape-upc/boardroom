# BoardRoom 🏛️

**A society of AI agents that reviews your PCB — and argues about it.**

Specialist agents (power integrity, signal integrity, connectivity/ERC, DFM/layout,
firmware bring-up) review real KiCad projects through the KiCad MCP server, file
evidence-backed findings, and negotiate conflicting recommendations under a Moderator
before signing off a review — measurably cheaper and more accurate than a single
monolithic agent.

Built for the **Global AI Hackathon Series with Qwen Cloud — Track 3: Agent Society**.

## How it works

A review is a society, not a chatbot:

1. **Five specialists** — power integrity, signal integrity, connectivity/ERC, DFM &
   layout, firmware bring-up — inspect a real KiCad project through the **KiCad MCP
   server**. Each can only touch the tools in its lane, **enforced in code**, not by
   prompting.
2. **Every finding must cite tool evidence.** Uncited claims are rejected at the schema
   boundary — the hallucination guard is architectural, not a polite request.
3. **A Moderator** detects conflicting recommendations and runs a bounded 2-round debate
   (one extra measurement per side), then rules on the **evidence**, citing what decided
   it. See [docs/NEGOTIATION_PROTOCOL.md](docs/NEGOTIATION_PROTOCOL.md).
4. **The report** is a blast-radius graph (findings → nets → components) plus board
   overlays from a multimodal critic (`qwen3-vl`) that actually *sees* the render.

Architecture + diagram: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Does a society actually beat one big agent? We measured it.

6 KiCad boards, 12 reproducibly seeded defects, **two runs per config**. Full method and
limitations: [docs/BENCHMARK.md](docs/BENCHMARK.md).

| | society | baseline (1× qwen3-max, all tools) |
|---|---|---|
| Seeded-defect recall (mean) | **0.29** | 0.21 |
| Cost per corpus | **$0.147** | $0.429 |
| Prompt tokens | 792K | 312K |
| Findings surfaced | 49–56 | 6–10 |
| Hallucination rate | **0.00** | 0.00 |

**~2.9× cheaper while burning 2.5× MORE tokens** — five cheap specialists doing *more*
work cost far less than one expensive generalist doing less. Routing by role beats
routing by model size.

We do **not** claim a detection win: the society led in both runs, but by one defect out
of twelve — that's noise, and we say so. Absolute recall is low for *both* configs
because most seeded defects are invisible to the tools (a missing cap is an *absence*;
a swapped SDA/SCL is electrically valid). We report that rather than hide it.

## Quickstart

```bash
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
export DASHSCOPE_API_KEY=sk-...            # Alibaba Cloud Model Studio
export KICAD_MCP_COMMAND=/path/to/kicad-mcp-server   # optional; auto-probed

# Review a KiCad project (prints findings + per-agent token accounting)
python -m backend.app.review /path/to/kicad_project --out review.json
```

Then open [`report/dist/index.html`](report/dist/) and drag `review.json` onto it — or
just open it to see the bundled real review of the KiCad **StickHub** demo board.

Reproduce the benchmark:
```bash
python -m benchmark.corpus.fetch
BOARDROOM_REAL_RUNNER=1 python -m benchmark.run --config society
BOARDROOM_REAL_RUNNER=1 python -m benchmark.run --config baseline
```

## Alibaba Cloud deployment proof

- [`backend/app/qwen_client.py`](backend/app/qwen_client.py) — all model calls via
  **Alibaba Cloud Model Studio** (DashScope international endpoint), with per-agent
  token accounting.
- [`deploy/alibaba/oss_store.py`](deploy/alibaba/oss_store.py) — **Alibaba Cloud OSS**
  via the official `oss2` SDK.
- [`deploy/Dockerfile`](deploy/Dockerfile) — backend + KiCad container for ECS.

## Tests

```bash
.venv/bin/python -m pytest -q     # 226 tests, no network or KiCad required
```

## License

MIT — see [LICENSE](LICENSE).
