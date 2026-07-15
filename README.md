# BoardRoom 🏛️

**A society of AI agents that reviews your PCB — and argues about it.**

Specialist agents (power integrity, signal integrity, connectivity/ERC, DFM/layout,
firmware bring-up) review real KiCad projects through the KiCad MCP server, file
evidence-backed findings, and negotiate conflicting recommendations under a Moderator
before signing off a review — measurably cheaper and more accurate than a single
monolithic agent.

Built for the **Global AI Hackathon Series with Qwen Cloud — Track 3: Agent Society**.

> 🚧 Under construction until Jul 20, 2026. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
> and [docs/NEGOTIATION_PROTOCOL.md](docs/NEGOTIATION_PROTOCOL.md).

## Quickstart

```bash
pip install -r backend/requirements.txt
export DASHSCOPE_API_KEY=sk-...
uvicorn backend.app.main:app --reload
```

<!-- docs-producer: full quickstart, benchmark results table, architecture diagram
     PNG, and the "Alibaba Cloud Deployment Proof" section (linking deploy/alibaba/
     and backend/app/qwen_client.py) land on Day 4. -->

## License

MIT — see [LICENSE](LICENSE).
