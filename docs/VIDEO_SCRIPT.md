# BoardRoom — 3-Minute Demo Video Script

Target ~3:00, uploaded **public** to YouTube. Record 1920×1080, dark theme.

> ## ⚠️ DO NOT RUN A LIVE REVIEW WHILE RECORDING
> The Model Studio free quota is spent. Every artifact you need is already saved in
> the repo — this script films **real saved results**, never a live API call. The two
> terminal commands below (`pytest`, printing a saved review) make **zero** network
> calls.

---

## Before you hit record (10 min)

Open these four things:

1. **The report** — double-click
   `report/dist/index.html`
   It boots with the **real** StickHub review already loaded (shows "6 Filed").
   Hard-refresh once (**Ctrl+Shift+R**) so you get the latest build.
2. **Benchmark chart** — `benchmark/results/comparison_chart.png`
3. **Architecture diagram** — `docs/architecture.png`
4. **Terminal** at the repo root, dark theme, font enlarged (Ctrl+scroll).

Checks: run `cls` first, and **confirm no API key is visible anywhere in the terminal
scrollback**. Recorder: OBS, or `Win+Alt+R`.

Notes on what you'll see (so nothing surprises you on camera):
- The **blast-radius graph** drifts for ~2.5 s then **settles completely**. Let it
  settle before you start narrating that section.
- The **board overlay** has three annotations: two solid yellow boxes (USB4 area and
  lower-right), plus a **dashed outline around the whole board** — that's a finding the
  vision critic applied board-wide. It's drawn unfilled on purpose so it doesn't hide
  the copper.

---

## 0:00–0:20 — Hook

**Screen:** the board render full-frame (`report/dist/board.png`, or the Board Overlay
view before you click anything).

> "Every hardware engineer knows this feeling. You order boards, wait three weeks, and
> then find out you forgot a decoupling capacitor. A single AI reviewer misses real
> defects — and invents fake ones. So I didn't build one reviewer. I built a review
> board."

## 0:20–0:40 — What it is

**Screen:** `docs/architecture.png`.

> "BoardRoom is a society of five specialist agents — power integrity, signal integrity,
> connectivity, DFM and layout, and firmware bring-up — that inspect a real KiCad project
> through the KiCad MCP server. A Moderator makes them defend their findings with
> evidence before signing off. Everything runs on Qwen models on Alibaba Cloud Model
> Studio."

## 0:40–1:05 — It's real (no API needed)

**Screen:** terminal. Run:

```powershell
.venv\Scripts\python -m pytest -q
```

then:

```powershell
type report\sample\review.sample.json | more
```

> "This isn't a mockup. Two hundred and twenty-eight tests, no network required. And this
> is a real signed review of the KiCad StickHub demo board. Every finding cites a real
> tool call — if an agent can't cite evidence, the finding is rejected at the schema
> boundary. Hallucination rate across every run: zero."

## 1:05–1:35 — The report (hero shot)

**Screen:** browser. Click **Blast-Radius Graph**, let it settle, hover a node. Then
click **Board Overlay**.

> "The output isn't a wall of text. It's a blast-radius map — each finding linked to the
> nets and components it touches: the five-volt rail, the USB connectors. And the layout
> critic is a multimodal model that actually sees the board render, so it draws a box
> around each defect right on the copper."

## 1:35–1:55 — The negotiation protocol

> ### ⚠️ HONESTY CONSTRAINT — do not imply this is a live debate.
> The engine is real and unit-tested, but **no board in the benchmark corpus produced a
> conflict**, so there is no authentic transcript. Load the clearly-labeled synthetic
> fixture and say so on camera. The VO below does.

**Screen:** drag `report/sample/review.debate-example.json` onto the dashboard, click
**Debate Viewer**. Leave the "SYNTHETIC EXAMPLE" title visible.

> "When two specialists collide — signal integrity wants a wider trace, DFM says that
> breaks the fab's clearance rule — the Moderator opens a bounded debate: two rounds, one
> extra measurement per side, then it rules on evidence, not eloquence, and records which
> measurement decided it. Full disclosure: this transcript is synthetic. The engine is
> real and tested, but across my whole benchmark corpus the specialists never actually
> disagreed. That's an honest result about the design, and I'd rather show you the
> mechanism than fake a fight."

## 1:55–2:35 — The numbers

**Screen:** `benchmark/results/comparison_chart.png`.

> "So is a society better than one big agent? I measured it — six boards, twelve seeded
> defects, two runs each. Recall is comparable: the society led by one defect out of
> twelve, which is within noise, and I say so. But look at cost. The society burns two
> and a half times **more** tokens — and costs nearly three times **less**. Five cheap
> specialists doing more work beat one expensive generalist doing less. Routing by role
> beats routing by model size."

## 2:35–3:00 — Close

**Screen:** flash `backend/app/qwen_client.py` and `deploy/alibaba/oss_store.py` (~2 s
each), then the GitHub README.

> "Built entirely on Qwen via Alibaba Cloud Model Studio, with OSS for storage. Open
> source, MIT. One last honest note: absolute recall is low for both configurations —
> because most of the defects I seeded are invisible to every tool that exists. No KiCad
> tool reports that a capacitor is *missing*. The reasoning layer is ahead of the
> observability layer. That's the most interesting thing I learned. BoardRoom — a society
> of AI agents that reviews your PCB, and argues about it."

**End card:** repo URL + "Global AI Hackathon Series with Qwen Cloud — Track 3: Agent
Society".

---

## Timing & delivery

- ~430 words of narration ≈ 3:00 at a normal pace. If you run long, trim 0:40–1:05.
- Record screen and voice separately if you fumble — far easier than re-shooting.
- English is fine with an accent; clarity matters more than accent.

## Post-record checklist

- [ ] Video is **public** on YouTube (not unlisted — the rules require public).
- [ ] Paste the URL into `docs/DEVPOST.md` (bottom) and the Devpost form.
- [ ] No API key visible in any frame.
- [ ] Devpost: repo URL + video URL + **Track 3** + description from `docs/DEVPOST.md`.
- [ ] GitHub **About**: description set and **License: MIT** visible.
- [ ] Optional: publish `docs/BLOG_DRAFT.md` and add its URL for the Blog Post Award.
