# BoardRoom — 3-Minute Demo Video Script

Target ~3:00, uploaded **public** to YouTube. Record 1920×1080, dark theme.

> ## ⚠️ DO NOT RUN A LIVE REVIEW WHILE RECORDING
> The Model Studio free quota is spent. Every artifact you need is already saved in
> the repo — this script films **real saved results**, never a live API call. The two
> terminal commands below (`pytest`, printing a saved review) make **zero** network
> calls.

**Narrative rule:** who I am → what it does → what it found → *only then* how it works
→ proof → close. Never show the architecture before the viewer knows what the thing
does; nobody can follow a diagram for a tool they haven't seen yet.

---

## Before you hit record (10 min)

Open these in separate tabs/windows so you can cut between them without fumbling:

1. **Title card** — `docs/title-card.html` → **F11** fullscreen, press **C** to hide the
   hint. (→ / Space switches to the end card; ← goes back. Start on screen 1.)
2. **The report** — `report/dist/index.html`, hard-refresh (**Ctrl+Shift+R**).
   It boots with the **real** StickHub review loaded ("6 Filed").
3. **Architecture diagram** — `docs/architecture.png`
4. **Benchmark chart** — `benchmark/results/comparison_chart.png`
5. **Terminal** at the repo root, dark theme, font enlarged (Ctrl+scroll), `cls` run.
   **Confirm no API key is visible in the scrollback.**

Heads-up so nothing surprises you on camera:
- The **blast-radius graph** drifts ~2.5 s then settles. Let it settle before narrating.
- The **board overlay** shows two solid yellow boxes plus a **dashed outline around the
  whole board** — intentional: that finding applies board-wide, drawn unfilled so it
  doesn't hide the copper.

---

# THE SCRIPT

## 1 · 0:00–0:18 — Who + what (title card)

**Screen:** `title-card.html`, screen 1, fullscreen. Stay on it the whole time.

> "Hi, I'm Lluís. For the Qwen Cloud hackathon I built **BoardRoom** — a tool that
> reviews printed circuit board designs using a team of AI agents that actually argue
> with each other.
> Let me show you the problem it solves first."

*(Don't rush. Let the title breathe for a beat before you switch away.)*

## 2 · 0:18–0:40 — The problem, then one concrete result

**Screen:** switch to the report → **Findings Table**. Scroll slowly through the rows.

> "If you send a board to fab with a missing decoupling capacitor or a silkscreen label
> printed over a pad, you find out three weeks and a few hundred euros later. So I
> pointed BoardRoom at a real KiCad board — the StickHub USB hub demo — and this is what
> it came back with. Six findings. Power rails with mixed copper widths. Silkscreen
> overlapping pads on the USB footprints. Missing fiducials."

## 3 · 0:40–1:05 — Proof each finding is real, not invented

**Screen:** expand one row in the Findings Table so its **evidence** block is visible.
Point at the `evidence_id` and the tool name.

> "And here's the part I care about most. Every single finding has to cite a real tool
> call — this ID comes from an actual query against the board file. If an agent makes a
> claim it can't back with evidence, the finding is rejected automatically before it ever
> reaches you. Across every benchmark run, both configurations, the hallucination rate
> was exactly zero."

## 4 · 1:05–1:30 — *Now* explain how it works

**Screen:** `docs/architecture.png`. Trace it with the cursor as you talk — left to
right, one box at a time.

> "So how does it work? The board goes in here. Five specialist agents inspect it —
> power integrity, signal integrity, connectivity, DFM and layout, and firmware bring-up.
> Each one talks to KiCad through the Model Context Protocol, and each one can only touch
> the tools in its own lane — that's enforced in code, not by asking the model nicely.
> They file findings; a Moderator collects them and signs off the review. All of it runs
> on Qwen models on Alibaba Cloud Model Studio."

## 5 · 1:30–1:55 — The visual payoff

**Screen:** report → **Blast-Radius Graph** (let it settle, hover a node), then
**Board Overlay**.

> "The output isn't a wall of text. It's a map: every finding linked to the nets and
> components it actually touches — the five-volt rail, the USB connectors. And because
> the layout critic is a multimodal model, it genuinely looks at the rendered board and
> draws a box around each defect, right on the copper."

## 6 · 1:55–2:15 — The argument (honest disclosure)

> ### ⚠️ Do NOT imply this is a live debate.
> The engine is real and unit-tested, but no board in the corpus produced a conflict, so
> there is no authentic transcript. Load the labeled synthetic fixture and say so.

**Screen:** drag `report/sample/review.debate-example.json` onto the dashboard →
**Debate Viewer**. Leave the "SYNTHETIC EXAMPLE" label visible.

> "And when two specialists disagree, a Moderator runs a bounded debate — two rounds, one
> extra measurement each — then rules based on the evidence, not on who argued harder.
> Full disclosure: this transcript is synthetic. The engine works and is tested, but
> across my whole benchmark the specialists never actually disagreed. I'd rather show you
> the mechanism than fake an argument."

## 7 · 2:15–2:45 — Is it actually better? (the numbers)

**Screen:** `benchmark/results/comparison_chart.png`.

> "Last question: is a team of agents actually better than one big one? I measured it.
> Six boards, twelve planted defects, two runs each. On finding defects, it's a tie —
> the team led by one defect out of twelve, which is noise, and I'm not going to claim
> otherwise. But look at the cost. The team burns two and a half times **more** tokens,
> and costs nearly three times **less** — because five small models doing more work are
> far cheaper than one big model doing less. Routing by role beats routing by model size."

## 8 · 2:45–3:00 — Close (end card)

**Screen:** press **→** on the title card to reveal the end card.

> "One honest note to finish: absolute detection rates are low for both setups, because
> most of the defects I planted are invisible to every tool that exists — no KiCad tool
> reports that a capacitor is *missing*. The reasoning is ahead of the instruments.
> That's the most interesting thing I learned building this.
> BoardRoom. Open source, MIT. Thanks for watching."

---

## Timing & delivery

- ~470 words ≈ 3:00 at a natural pace. Running long? Trim section 3 to two sentences.
- **Record screen and voice separately** if you fumble — far easier than re-shooting.
- English with an accent is completely fine; clarity beats accent.
- Cut between windows with Alt+Tab **while silent**, not mid-sentence.

## Post-record checklist

- [ ] Video is **public** on YouTube (not unlisted — the rules require public).
- [ ] Paste the URL into `docs/DEVPOST.md` (bottom) and the Devpost form.
- [ ] No API key visible in any frame.
- [ ] Devpost: repo URL + video URL + **Track 3** + description from `docs/DEVPOST.md`.
- [ ] GitHub **About**: description set and **License: MIT** visible.
- [ ] Optional: publish `docs/BLOG_DRAFT.md` and add its URL for the Blog Post Award.
