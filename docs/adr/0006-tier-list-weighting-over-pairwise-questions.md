# 6. Tier-list weighting instead of sequential pairwise narrowing questions

- Status: **accepted** (still holds)
- Date: Milestone 9

## Context

The SPEC originally envisioned an interactive screening experience built on **sequential
pairwise narrowing questions** ("what matters more — X or Y?"), with deliberately redundant
and overlapping questions so no single early answer could "lock in" the ranking prematurely,
backed by a constraint-solver to integrate the overlapping comparisons.

By M9 the equal-weight baseline (ADR 0005) had been validated against the real pool and
judged not good enough — every dimension counting equally doesn't reflect committee values.
Something was needed to let the committee express what matters.

## Decision

**Use a tier-list maker, not sequential pairwise questions.** The committee drags the
discovered dimensions into importance tiers they define themselves (from 2 tiers to
one-per-dimension, most in between), plus a bottom **Ignore** zone (weight 0). The ranking
re-sorts instantly as **deterministic math over cached scores — no model call.**

- **Tier layout is the source of truth; weights are derived.** The run stores
  `criteria.tiers`; a pure `weights_from_tiers` recomputes `criteria.weights` (non-ignore
  tiers get a descending weight by position, equal within a tier; Ignore = 0). Every weight
  traces to a tier position — maximally auditable.
- **The ranking engine is untouched** — `weights_from_tiers` writes the same `criteria.weights`
  map `rank_candidates` already reads (ADR 0005). M9 adds only the tier→weights derivation.

## Consequences

- **Direct beats indirect for a committee that already has opinions.** Backing into a known
  preference via many pairwise questions is slow; dragging dimensions into tiers states it in
  one pass and can zero out whole groups at once ("only the top 3 matter").
- **The anti-lock-in machinery becomes unnecessary.** The pairwise design's redundant/overlapping
  questions and constraint-solver existed to prevent premature lock-in; with every dimension
  visible and re-draggable at any time, there is nothing to lock. Re-weighting is freely
  reversible — no separate undo state, re-sorting rather than un-rejecting.
- **The assistant never "cuts" candidates.** At ~300 applicants, hard removal is the wrong
  model; the tool stack-ranks the whole pool with per-row rationale, and re-weighting adjusts
  standing (soft ranking), never removes anyone. There is no fixed cut line.
- A future "Criteria Coach" may still *ask* questions — but to help the committee reflect on
  and challenge the weighting they built, not to elicit it. It does not re-rank.
- Built with `@dnd-kit` for accessible drag; thin persistence (`GET`/`PUT /ranking/tiers`).
