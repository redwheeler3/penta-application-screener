# 4. Orient dimensions at discovery instead of a per-dimension direction flag

- Status: **reversed** (the `more/less/undecided` direction flag was designed then reverted)
- Date: decided 2026-06-28

## Context

Ranking is a weighted sum over per-dimension scores (`fit = Σ weight·score`). For the sum to
mean anything, every dimension's score must push fit in a consistent direction. An early
design gave each dimension a **direction flag** — a `more/less/undecided` enum — plus
**sign-aware ranking math** so the ranking engine could interpret "less is better" axes and
undecided ones at ranking time.

The alternative: bake direction into the dimension at the moment of discovery, so the score
scale is always oriented the same way and the ranking math never needs to know about direction.

## Decision

**Orient every dimension so MORE is better fit, at discovery time.** There is **no
per-dimension direction flag in the schema.** The discovery prompt recasts "less is better"
axes into their positive form (e.g. "frequency of breakdowns" → "mechanical reliability").
For "goldilocks" axes (best value in the middle) two paths:

- A peak from ONE quantity vs. a target → *reframe* to the underlying monotonic fit-concept
  ("amount of salt" → "seasoned about right"; confirmed working: income level → distribution
  balance).
- A peak from TWO opposing forces a household could have one without the other → *emit two*
  separate more-is-better dimensions and let the committee's weighting place the peak (e.g.
  "strong primary earner, but not single-income-dependent" → `primary_earner_income_strength`
  + secondary-income-contribution). Never a merged "balanced X."

The committee owns direction only by Ignoring an axis or proposing a rephrase.

## Consequences

- The signed `more/less/undecided` enum and its sign-aware ranking math were **reverted** —
  orienting at discovery is simpler and needs no ranking-math change. The score always pushes
  fit up, so scoring can't be neutral; direction is a property of the dimension, not the ranker.
- The two-dimension split reliably fires only for **independently-measured** forces. For
  single-variable, two-reading axes (e.g. child age toddlers↔teens) the model does not split
  no matter how hard the prompt pushes — it absorbs the trait into a nearby measured axis
  (child age → `long_term_residency_intent`). This is **accepted behavior, not a bug**: the
  one-concept discipline working correctly; pushing harder produced fusion artifacts.
- Prompt examples are kept out-of-domain so they teach the orientation move without leading
  the pool-specific answer.
- Later confirmed by the eval invariant `poles_present` (every dimension has distinct
  high/low ends) — the mechanical form of this decision.
