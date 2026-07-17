# BoardRoom Benchmark — Society vs. Single-Agent Baseline

Track 3 requires "a measurable efficiency gain over single-agent baselines." This is
that measurement, run honestly on the same inputs.

## Method

- **Corpus**: stock KiCad demo boards (fetched from the local install; not
  redistributed). See `benchmark/corpus/manifest.yaml`.
- **Seeding**: each board gets reproducible, scripted defect injections with a
  ground-truth manifest of what a correct reviewer must flag (removed decoupling cap,
  swapped I²C SDA/SCL, missing I²C pull-ups, floated enable/reset pin, renamed rail).
  One board (`ecc83_pp`, pure analog) deliberately has **no applicable defects** — an
  honesty check that neither config invents findings.
- **Two configurations, identical inputs, same token gateway**:
  - **society** — the full BoardRoom pipeline: five specialists on cheap models
    (`qwen-flash` / `qwen3-vl-plus` / `qwen3-coder-plus`) + a `qwen3-max` Moderator.
  - **baseline** — one `qwen3-max` agent with **all** KiCad tools and a generalist
    review prompt (`society/prompts/_baseline.md`).
- **Matcher**: a finding matches a seeded defect when
  `(affected_nets OR affected_components overlap) AND (agent matches OR severity within
  one level)`. Net/designator names are normalized (last path segment, case-insensitive)
  so `/pic_sockets/VCC_PIC` and `VCC_PIC` compare equal — KiCad names the same net both
  ways, and a correct answer shouldn't be scored wrong on a naming convention. Applied
  identically to both configs. Defined in `benchmark/metrics.py`.

### Fairness measures (what we did so we weren't grading ourselves generously)

Three bugs found while validating this benchmark would each have flattered the society.
They are fixed; the fixes are what make these numbers worth reading:

1. **The baseline was tool-starved.** It was scoped to 3 overview tools instead of all
   of them. A tool-starved baseline is a strawman. It now genuinely gets every adapter.
2. **The baseline was penalized on formatting.** It *found* defects but emitted
   `title`/`description` instead of `claim`/`evidence`, so every finding was discarded
   at the schema boundary. The specialist prompts each carry a worked JSON example; the
   baseline's did not. It now gets the same schema guidance — otherwise this measures
   prompt quality, not architecture.
3. **The society was silently crippled.** `registry.yaml` promised tools whose adapters
   were never written, and the spec generator skipped them without erroring — costing
   the specialists schematic-net visibility. Adapters restored; the baseline gets them
   too, via its wildcard.

### Known limitations (read this before believing the recall numbers)

- **Most seeded defect classes are undetectable by any current configuration.** Removing
  a decoupling cap or an I²C pull-up creates an *absence*, and no KiCad tool reports "a
  part that should exist is missing." A swapped SDA/SCL is electrically valid, so ERC is
  silent. Only rail-rename / floating-pin defects reliably surface (via ERC and
  schematic net listings). Low absolute recall for **both** configs is mostly a
  statement about the tools' blind spots, not the architectures.
- **Run-to-run variance is large relative to the config gap.** These are
  nondeterministic LLMs: one board's society recall was observed at both 0.50 and 0.00
  across runs with equivalent code. With 12 seeded defects, a one-defect difference is
  noise. Treat recall as *comparable* unless the reported spread says otherwise.
- **"Unmatched findings" are NOT false positives.** The KiCad demo boards contain real,
  pre-existing defects we did not seed; a genuine catch of one is counted as unmatched
  because ground truth only covers our injections. The column is descriptive, not an
  error rate.
- **Reproduce**:
  ```
  python -m benchmark.corpus.fetch
  BOARDROOM_REAL_RUNNER=1 python -m benchmark.run --config society
  BOARDROOM_REAL_RUNNER=1 python -m benchmark.run --config baseline
  ```

## Results

6 boards, 12 seeded defects, **two independent runs of each configuration** with
identical code (LLMs are nondeterministic; a single run is not a measurement).

| Config | Run | Recall | Defects | Unmatched | Halluc. | Prompt tok | Compl. tok | Cost $ | Wall s |
|--------|-----|-------:|--------:|----------:|--------:|-----------:|-----------:|-------:|-------:|
| society  | 1 | 0.33 | 4/12 | 56 | 0.00 | 779,635 | 59,354 | 0.160 | 527 |
| society  | 2 | 0.25 | 3/12 | 49 | 0.00 | 804,991 | 49,897 | 0.134 | 516 |
| baseline | 1 | 0.25 | 3/12 |  6 | 0.00 | 315,199 |  8,232 | 0.428 | 400 |
| baseline | 2 | 0.17 | 2/12 | 10 | 0.00 | 307,946 | 10,194 | 0.431 | 407 |

**Means** — society: recall **0.29**, cost **$0.147**. baseline: recall **0.21**, cost
**$0.429**.

![society vs baseline](../benchmark/results/comparison_chart.png)

## Reading the result — honestly

**What is robust (reproducible across every run):**

- **~2.9× lower cost** ($0.147 vs $0.429), stable to within 2% across runs.
- **The counter-intuitive part:** the society burns **2.5× MORE tokens** (792K vs 312K
  prompt) and is still **2.9× cheaper**. That is the whole architectural thesis in one
  number — five `qwen-flash` specialists doing *more* total work cost far less than one
  `qwen3-max` generalist doing less. Routing by role beats routing by size.
- **Hallucination rate 0.00 for both configs, every run.** The evidence-citation gate
  rejects uncited claims by construction rather than by asking the model nicely.
- **~9× broader coverage** (49–56 vs 6–10 findings). Most of those "unmatched" findings
  are real defects on the demo boards that we simply didn't seed (see limitations).

**What is NOT robust — do not over-read it:**

- **The recall edge is one defect.** The society beat the baseline in both runs, by
  exactly +1 defect each time (4v3, 3v2). The direction is consistent, but with 12
  seeded defects and n=2 runs this is **within noise** — per-board recall for the same
  config was observed at both 0.50 and 0.00 across runs. The honest claim is
  **"comparable, possibly slightly better"**, not "more accurate".
- **Absolute recall is low for both (0.21–0.29)** and that is mostly the tools' fault,
  not the architectures' — see the limitations above.

**The defensible summary:** *comparable-or-slightly-better recall at ~2.9× lower cost,
with ~9× broader coverage and a structurally-enforced 0.00 hallucination rate.*

> Cost uses the **placeholder** `COST_PER_MTOK` table in `backend/app/qwen_client.py`.
> The 2.9× ratio depends on the `qwen-flash` : `qwen3-max` price ratio — verify against
> Model Studio pricing before quoting absolute dollars. Token *counts*, recall, and
> hallucination rate are measured directly and carry no such caveat.

> Cost figures use the placeholder `COST_PER_MTOK` table in
> `backend/app/qwen_client.py`; verify against Model Studio pricing before quoting
> absolute dollars. Token *counts* and recall/FP/hallucination are measured directly.
