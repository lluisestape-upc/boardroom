# I built a society of AI agents to review circuit boards. Then I tried to prove it was better — and nearly fooled myself three times.

*Building BoardRoom on Qwen Cloud for the Global AI Hackathon Series — Track 3: Agent Society.*

---

Every hardware engineer knows the specific dread of clicking "order boards." Three weeks
and a few hundred euros later, a package arrives, and you discover you forgot a
decoupling capacitor, or your I²C bus has no pull-ups. Nothing to do but respin.

So for the Qwen Cloud hackathon I built **BoardRoom**: not one AI reviewer, but a
*society* of five — power integrity, signal integrity, connectivity/ERC, DFM & layout,
and firmware bring-up — that inspect a real KiCad project through the KiCad MCP server,
file findings that must cite tool evidence, and argue with each other under a Moderator
before signing off.

The build went fine. It's what happened when I tried to **prove** the society was better
than a single big agent that turned out to be the interesting part. Three separate times,
my benchmark was quietly lying in my favor. Here's each one, because I think the bugs are
more instructive than the architecture.

## The setup

The measurable claim Track 3 asks for is "a demonstrable efficiency gain over
single-agent baselines." So:

- **Corpus:** stock KiCad demo boards.
- **Seeding:** a script injects reproducible defects with a ground-truth manifest —
  removed decoupling cap, swapped SDA/SCL, missing I²C pull-ups, floated enable pin,
  renamed power rail. One board (a pure-analog valve preamp) gets *no* defects, as an
  honesty check that nobody invents findings.
- **Two configs, same inputs, same token gateway:** the society (five cheap specialists
  on `qwen-flash`/`qwen3-vl`/`qwen3-coder`, one `qwen3-max` Moderator) versus a baseline
  of one `qwen3-max` agent with *all* the tools and a generalist prompt.

Then I ran it. **Recall: 0.00.** The society caught zero of the seeded defects.

## Lie #1: my agents were right, my scoring was wrong

Rather than tune anything, I dumped the actual findings. And there it was:

```
[critical] connectivity_erc: Hierarchical label VCC_PIC has no matching sheet pin
                             in the parent sheet, creating an unconnected rail
```

That's *exactly* the defect I'd seeded. The society found it. The scorer called it a miss.

Why? The matcher compares structured fields — `affected_nets`, `affected_components` —
and the agents had left them **empty**, naming the net only in the prose of the claim.

That's not a benchmark artifact. That's a product bug I'd have shipped: **the report's
headline visualization — a blast-radius graph linking findings to the nets and parts they
touch — is built entirely from those fields.** My centerpiece visual was silently empty
and I hadn't noticed, because I'd been reading the claims, which looked great.

The prompts already asked for those fields politely. `qwen-flash` ignored it. Making the
final instruction blunt ("a claim that names a net while leaving these arrays empty is
INVALID — the impact graph is built from these fields, not from your prose") took
structured coverage from **0/9 findings to 9/15**, and recall from 0.00 to 0.50.

**Lesson:** when a model "ignores" a field, check whether anything downstream actually
depends on it. Mine did, and the benchmark found the bug my eyes didn't.

## Lie #2: I'd accidentally built a strawman

Now the baseline. It scored 0.00, produced zero findings, and burned 6.8K tokens in 29
seconds. I could have shipped that. "Single agent finds nothing, society wins" — a
beautiful chart.

Except: 6.8K tokens is *nothing*. A generalist reviewing a whole board can't be done in
29 seconds. So I looked.

I'd named the baseline agent `moderator` so it would inherit the wildcard "all tools"
entry from my default allowlist. But `registry.yaml` **overrides** the moderator down to
three overview tools — because in the society, the chair doesn't do analysis. My
"single agent with all 24 tools" had been reviewing boards nearly blind.

**A tool-starved baseline isn't a baseline. It's a strawman**, and it's exactly the thing
a judge should nuke a submission for. Fixed: the baseline now builds its allowlist from
defaults, genuinely getting every tool. Its token use went 6.8K → 63K.

## Lie #3: I was grading the baseline on handwriting

Still 0.00, but now doing real work. Fine — maybe one agent really does drown in 24
tools? That's a great narrative. I nearly wrote it.

Instead I printed its raw output:

```json
{ "id": "B-001",
  "title": "Hierarchical label mismatch for VCC_PIC",
  "description": "...breaking connectivity.",
  "evidence_ids": ["EV-0005"] }
```

**The baseline found the defect too.** Every finding was thrown away at the schema
boundary because it wrote `title`/`description`/`evidence_ids` instead of
`claim`/`evidence`/`recommendation`.

And whose fault was that? Mine. Each specialist prompt carries a full worked JSON example
of the finding shape. The baseline prompt I'd dashed off didn't. **I was measuring prompt
quality and calling it architecture.**

I gave the baseline the same worked example the specialists get. I also normalized net
names in the matcher — KiCad legitimately calls the same net `VCC_PIC` or
`/pic_sockets/VCC_PIC`, and a correct answer shouldn't lose on a naming convention.

Notice the pattern: **all three bugs pointed the same direction.** None of them made the
society look worse. That's not coincidence — it's what motivated reasoning looks like
from the inside. You stop debugging when the number agrees with you.

## What the honest numbers say

Six boards, twelve seeded defects, **two independent runs per config**, because LLMs are
nondeterministic and one run isn't a measurement.

| | society | baseline (1× qwen3-max, all tools) |
|---|---|---|
| Seeded-defect recall (mean) | **0.29** | 0.21 |
| Cost per corpus | **$0.147** | $0.429 |
| Prompt tokens | **792K** | 312K |
| Findings surfaced | 49–56 | 6–10 |
| Hallucination rate | **0.00** | 0.00 |

Read the token row and the cost row together, because that's the whole story:

**The society burns 2.5× MORE tokens and costs 2.9× LESS.**

Five cheap specialists doing *more* total work are dramatically cheaper than one
expensive generalist doing less. The win isn't "multi-agent is smarter." It's that
decomposition lets you **route by role instead of by model size** — you only pay
flagship prices for the one job that actually needs a flagship: adjudicating conflicts.
That number reproduced to within 2% across runs.

And the thing I'm *not* claiming: the society led on recall in both runs, but by exactly
**one defect out of twelve**. With n=2, that's noise — I watched the same config score
0.50 and 0.00 on the same board across runs. So the honest claim is "comparable, possibly
slightly better," and that's what the README says.

## The most useful result is the one that makes my project look bad

Absolute recall is low for *both* configs — 0.21 to 0.29. I could have quietly picked
easier defects. Here's why it's low instead:

**Most of the defects I seeded are invisible to every tool that exists.** Removing a
decoupling cap creates an *absence* — no KiCad tool reports "a part that should be here
isn't." A swapped SDA/SCL is electrically valid, so ERC has nothing to say. The only
class anything reliably caught is rail-rename/floating-pin, because ERC and net listings
actually surface it.

That's not an indictment of the agents. It's a finding about EDA tooling: **the reasoning
layer is now ahead of the observability layer.** These models can absolutely reason about
a missing bypass cap — they just have no instrument that reports its absence. The
bottleneck isn't intelligence. It's that we never built the tool, because no human needed
one to eyeball a schematic.

I think that's the most interesting thing I learned, and it only showed up because I
reported a bad number instead of engineering around it.

## What I'd tell someone starting one of these

1. **Evidence gating works.** Every finding must cite a real cached tool-call ID, and
   uncited claims are rejected at the boundary — not discouraged in a prompt.
   Hallucination rate: **0.00 across every run, both configs.** Make it structural and
   you stop arguing with the model about honesty.
2. **Enforce scope in code, not prose.** Each specialist's tool allowlist is enforced
   before the call. Prompts are suggestions; allowlists are physics.
3. **Route by role, not by size.** This is where the 2.9× lives.
4. **Debug the results that flatter you.** All three of my bugs produced *better* numbers.
   If I'd stopped at the first good chart, I'd have submitted a rigged benchmark with a
   straight face.

One last confession: BoardRoom's negotiation engine — bounded two-round debates,
evidence-cited rulings, fully unit-tested — **never fired on real data.** Across the whole
corpus, no two specialists ever produced conflicting findings. Their scopes are narrow
enough that they rarely collide. The repo ships a clearly-labeled synthetic fixture to
demonstrate the viewer, and says so in the README, because the alternative is faking a
fight and calling it a demo.

That's a real limitation of the design, discovered by measuring instead of assuming. Which
is, I think, the actual point.

---

*BoardRoom is open source (MIT): https://github.com/lluisestape-upc/boardroom — built on
Qwen models via Alibaba Cloud Model Studio, with the KiCad MCP server. Benchmark method,
raw numbers and limitations: [docs/BENCHMARK.md](https://github.com/lluisestape-upc/boardroom/blob/main/docs/BENCHMARK.md).*
