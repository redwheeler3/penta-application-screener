# Case study: choosing between two things you built — with a judge that overturned my own diagnosis

*How building the measuring instrument first, then building the design I was rooting for and letting it lose, settled an architecture question the way a bake-off settles a recipe: by tasting both.*

This is the companion to [dimension-convergence.md](dimension-convergence.md).
That story is about **not building** — a cheap experiment killed an appealing
design before a line of it shipped. This one is the opposite discipline: I had
two designs I actually wanted to build, I built both, and I chose between them
with a number instead of taste. Same underlying method (measure, don't intuit),
opposite decision (which thing to keep, not whether to start).

The transferable part isn't the dimension pipeline. It's three moves:

1. **Build the judge before the thing it judges** — and be willing to let the
   judge overturn your own hand-diagnosis.
2. **Build the fancy option you're rooting for, then let it lose on the number.**
3. **Don't let the winning metric answer a question it didn't measure** — name
   the gap and close it with a second experiment.

## Background (one paragraph)

The screener uses an LLM to *discover* the dimensions a pool of housing co-op
applicants varies on, then scores each applicant so a committee can weight and
rank. The convergence experiment (the companion) had already decided the shape:
discovery is nondeterministic, so run it **K times in parallel** on fresh
contexts and take the union — more coverage than any single run. But a union of
K carvings is messy: the same concept comes back reworded, re-split, carved at
different granularities. Something has to **settle** those K reports into one set
of axes that are each genuinely differentiating and mutually non-overlapping.
That settling step is where the two designs competed.

## The two designs

- **The baseline I expected to outgrow:** one structured LLM call. Hand it all K
  reports, tell it to produce the finest non-overlapping set, and force it to
  *show evidence both ways* — to merge two axes it must assert they'd score the
  same applicant the same way; to keep two apart it must name an applicant who'd
  land high on one and low on the other.
- **The design I was rooting for:** a multi-agent loop. A Merger proposes
  merges, then an adversarial Splitter challenges them and splits back the ones
  it thinks went too far, round after round until stable. It *felt* more
  rigorous — a skeptic checking the merger's work is exactly the kind of
  structure that sounds like it should win.

I wanted the loop to win. That's precisely why I refused to decide by taste.

## Move 1 — Build the judge first, and let it correct me

Before building either settler, I needed a way to score their output. The
quality question is "did it over-merge or under-merge?" — and I could answer it
without a model at all. I already had, on disk, every historical run's
per-candidate scores: a dense grid of dimension × applicant. If two axes are
really the same concept re-carved, they score people the same way — their score
vectors correlate. So the judge is a read-only script
(`backend/scripts/dimension_overlap.py`): pairwise Pearson correlation over the
cached score vectors, flag any pair above a threshold as a suspected duplicate.
No model grading a model. An afternoon of pure Python.

Then the judge did the thing that justified building it first: **it overturned
my hand-diagnosis.**

I had eyeballed the historical dimensions and "known" that the three
participation-flavoured axes — governance participation, maintenance
participation, general commitment — were one concept the model kept re-splitting.
Obvious over-carving, I thought; a good settler should collapse them. The judge
said no. `governance_participation_commitment` vs.
`maintenance_participation_commitment` correlated at **r = 0.20** — they rank
*different people* high (one applicant scored 0.65 governance / 0.10
maintenance; another 0.50 / 0.85). "Will you sit on committees" and "will you
show up for the physical work-days" share the word *participation* and nothing
else. **Collapsing them would have been an over-merge** — the exact
lose-a-distinction failure the whole redesign is supposed to prevent — and I had
been about to instruct the settler to do it.

That reframed the judge's job. Its highest value wasn't catching *under*-merges
(redundant survivors); it was as an **over-merge guardrail**, telling me "r =
0.20, keep these apart" when my intuition wanted to lump. The instrument didn't
just score the contestants — it fixed the rubric I would have judged them by.

(One honesty note worth carrying: that dense score grid existed *only* because
the old sequential pipeline wastefully re-scored every accumulated dimension on
every run — the very overspend the redesign exists to eliminate. So the judge
runs in full only as a one-time bake-off instrument. In production it can still
catch under-merges on the settled set, but it goes blind to over-merges, because
a wrongly-merged pair never gets two separate score columns. The net that caught
*this* over-merge is gone in production — which is exactly why the over-merge
evidence had to be baked into the settler's prompt, not left to a post-hoc
check.)

## Move 2 — Build the fancy option, then let it lose

With a judge in hand, I built both settlers and ran each three times on the same
fixture (10 discovery reports, 246 input dimensions), scoring every run:

| Variant | Stability | Mean overlaps | Mean dims | Cost (3 reps) |
|---|---|---|---|---|
| **Single-call baseline** | 0.60 | **0.0** | 28.0 | $0.82 |
| Merger↔splitter loop | 0.62 | 0.7 | 31.3 | $1.01 |

The loop I was rooting for was **strictly dominated**: 23% more expensive, no
more stable (0.62 vs 0.60 is noise), and *worse* on the one thing that mattered
— it reintroduced 0.7 overlaps per run, the redundancy the redesign exists to
kill. The baseline hit zero overlaps every single rep.

The reasoning traces explained *why*, and the why is the reusable lesson: the
loop's Splitter is a **one-directional force**. It can only split merges back
apart; it can never merge harder. So bolting an adversarial skeptic onto a merge
step isn't a neutral referee — it's a structural thumb on the scale toward
*under*-merging, which is just creep wearing a rigorous-looking costume. The
"more rigorous" design was systematically biased in one direction, and I'd never
have seen the direction without measuring it. The baseline — one call forced to
show evidence in both directions — was simply good enough, and I'd have talked
myself out of it on aesthetics alone.

So the loop didn't ship. Its mechanism, its verdict, and its lesson live in the
spec and in git history; the code was deleted. That's the "don't buy the
multi-agent machinery you didn't earn" rule, decided by a number.

## Move 3 — Don't let the metric answer a question it didn't ask

The bake-off measured **overlap** and **stability**. It did *not* measure
**coverage** — whether the K-parallel union actually surfaces *more real
differentiators* than a single run, or just more padding. That was the entire
premise of running discovery K times, and the bake-off was silent on it. It
would have been easy to declare victory and move on; the winning table looked
conclusive.

So I built a second instrument (`backend/scripts/coverage_gate.py`): count
distinct differentiating *territory* — real axes (non-flat score variance),
greedily clustered by correlation so re-carvings of one concept count once — for
a single run versus the union of all runs. Result: **single run 18.4 distinct
territories; K-union 25; +36%.** A single discovery run genuinely *misses* about
seven real differentiators that other fresh contexts surface (one run never
named health-safety skills, or governance-body experience, or child-age
profile). Not padding — distinct territory, with near-flat axes excluded.

That's what earns the K× cost. The redesign is justified end-to-end by two
separate measurements: **K-parallel for coverage (+36%)**, **single-call
decomposition for cleanliness (0 overlaps)** — and a multi-agent loop in neither
seat, because neither number asked for one.

## What generalizes

- **Build the judge before the contestants — it may be judging you too.** The
  overlap metric didn't just rank two settlers; it caught me about to hard-code
  an over-merge into the winner's prompt. An instrument you build *before* you're
  attached to an outcome can overrule your diagnosis, not just grade your
  options.
- **Build the design you're rooting for, then let the number kill it.** I
  wanted the multi-agent loop. Measuring it is the only reason I know it was
  biased toward creep rather than more rigorous. Taste would have shipped it.
- **A metric only answers the question it measured.** The bake-off proved
  cleanliness and said nothing about coverage — the actual reason for the whole
  architecture. Naming that gap and closing it with a second cheap experiment is
  the difference between "the numbers looked good" and "the design is justified."
- **Cheap instruments, expensive decisions.** Two read-only Python scripts —
  no product surface, no model-grading-model — settled which of two AI
  architectures to keep and whether the parallelism was worth its cost.

For the build-facing detail (the bake-off table in context, the D1–D9 decisions,
the coverage gate, the D9 committee-request guard), see the "Fan-Out Redesign"
section of `SPEC.md`. This document is the story; that one is the blueprint. For
the twin discipline — killing a design *before* building it — see
[dimension-convergence.md](dimension-convergence.md); the two are a deliberate
pair (choose-by-building / kill-before-building). For the design judgment behind
the feature these experiments shaped, see
[designing-an-ai-feature.md](designing-an-ai-feature.md).
