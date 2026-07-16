# BoardRoom — 3-Minute Demo Video Script

Target: ~3:00, public on YouTube. Dark theme everywhere (terminal + report UI).
Record at 1920×1080. Placeholders in ⟦brackets⟧ get filled from the real review +
benchmark before recording.

Tools to have open before recording:
- Terminal (dark) at the repo root, venv active, `DASHSCOPE_API_KEY` set.
- Browser with `report/dist/index.html` loaded showing the **real** StickHub review.
- The architecture diagram (docs/ARCHITECTURE.md rendered) in a tab.
- `docs/BENCHMARK.md` results table + the comparison chart PNG in a tab.

Record the terminal actions once as a clean take; do voiceover separately and lay it
over the screen capture so the pacing is tight.

---

## 0:00–0:20 — Hook (the problem)

**On screen:** the StickHub board render (`fixtures/stickhub` top view), zoom on a
region with a seeded/real defect.

**VO:** "Every hardware engineer knows this fear: you send a PCB to fab, and a
decoupling cap you forgot, or an I²C bus with no pull-ups, costs you a three-week
respin. A single AI reviewer misses things and hallucinates others. So we didn't
build one reviewer — we built a *review board*."

## 0:20–0:35 — What it is (one sentence + diagram)

**On screen:** the architecture diagram — KiCad project → MCP tool layer → five
specialists → Moderator → signed review.

**VO:** "BoardRoom is a society of five specialist agents — power integrity, signal
integrity, connectivity, DFM, and firmware bring-up — that inspect a real KiCad
project through the KiCad MCP server, and a Moderator that makes them defend their
findings with evidence before signing off."

## 0:35–1:10 — The society working live (the technical spine)

**On screen:** terminal. Run the review against StickHub:
```
python -m boardroom.review fixtures/stickhub   ⟦exact command from runner⟧
```
Show the specialists dispatching concurrently, each logging the KiCad tools it calls
(run_erc, extract_power_domains, render_board…) and the evidence IDs it gets back.

**VO:** "Each specialist runs on a cheap, fast Qwen model and can only touch the
tools in its lane — enforced in code, not by prompting. Every tool result becomes a
cited piece of evidence. A finding with no evidence is rejected automatically — that's
how we keep hallucinations out." ⟦state real accepted/rejected count⟧

## 1:10–1:50 — The negotiation (the money shot)

**On screen:** the report UI **Debate viewer** for a contested finding — Signal
Integrity vs. DFM/Layout on the same net. Show the two rounds, the extra evidence
each pulls, then the Moderator's ruling with cited evidence highlighted.

**VO:** "Here's what makes it a society. Signal Integrity wants a wider trace and a
ground pour. DFM objects — that violates the fab's clearance rule. They each get two
rounds and one extra measurement to back their case. Then the Moderator rules on
*evidence*, not eloquence — and records exactly which measurement decided it." ⟦read
the real ruling rationale⟧

## 1:50–2:20 — The blast-radius report

**On screen:** the report UI **blast-radius graph** — findings → nets → components,
colored by severity — then the board overlay with bounding boxes from the VL layout
critic.

**VO:** "The output isn't a wall of text. It's a blast-radius map: every finding
linked to the nets and parts it touches, and the layout critic — a multimodal Qwen
model that actually *sees* the board render — boxes each defect right on the copper."

## 2:20–2:45 — The benchmark (the proof)

**On screen:** the comparison chart — society vs. single-agent baseline.

**VO:** "And it's measurably better than a single big agent. On a corpus of KiCad
boards with known seeded defects, the society caught ⟦X%⟧ of them versus ⟦Y%⟧ for one
monolithic agent, with ⟦Z%⟧ fewer false positives — and ⟦N%⟧ lower token cost, because
five cheap specialists beat one expensive generalist." ⟦fill from benchmark/results⟧

## 2:45–3:00 — Close (Alibaba Cloud + wrap)

**On screen:** quick cut — `qwen_client.py` (Model Studio endpoint) and
`deploy/alibaba/oss_store.py`, then the repo's README hero.

**VO:** "Built entirely on Qwen models on Alibaba Cloud Model Studio, open source,
Track 3. BoardRoom — a society of AI agents that reviews your PCB, and argues about
it."

**End card:** repo URL + "Global AI Hackathon Series with Qwen Cloud — Track 3: Agent
Society".

---

### Recording checklist
- [ ] Real StickHub review produces a contested finding with a full debate (if the
      real board doesn't naturally conflict, run against `cm5_minima` which seeds all
      5 defect types, or use a seeded StickHub copy — say so honestly in the VO).
- [ ] Numbers in 2:20–2:45 match `docs/BENCHMARK.md` exactly.
- [ ] No API key visible on screen at any point (check the terminal scrollback).
- [ ] Video is public, not unlisted.
