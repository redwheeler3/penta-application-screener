# 5. The LLM extracts scored features; ranking is deterministic math on top

- Status: **accepted** (still holds)
- Date: Milestone 7 (foundation); Milestone 8 (equal-weight baseline)

## Context

The screener's primary output is an explainable ranked list of the eligible pool. A tempting
design is to let the LLM rank the pool directly (or rank on every committee answer). The
question was where the model's judgment belongs and where deterministic math takes over.

## Decision

**The LLM extracts scored features; ranking is deterministic math on top of them.** The model
scores each candidate on a fixed set of *discovered* dimensions (per dimension: a 0..1-style
score, rationale, grounding evidence, confidence label). It **never produces "the ranking"
and never opines on importance.** The ranking is a plain weighted sum over cached scores:
`fit = Σ(weight·score) / Σ(weight)` over dimensions with weight > 0.

The division of labor: **the AI discovers *what varies*; the committee decides *what
matters*.** Weights start at an **equal-weight baseline** — an honest "no judgment yet"
(fit is the plain average of a candidate's scores) — and only the human moves them (via the
tier list, ADR 0006), with every deviation traceable to a recorded human choice. A
non-uniform AI-proposed default was **rejected**: it would quietly pre-commit the values
question, presenting one applicant ahead of another before anyone said what they cared about.

Ranking lives in `app/domain/ranking.py` alongside `hard_filters.py` — a pure function over
already-fetched scores + weights, no DB or provider access, trivially unit-testable.

## Consequences

- **Re-weighting is instant, free, and deterministic**: a weighting change re-runs the math
  over cached scores, never the model. Re-ranking the pool with the LLM on every answer was
  **rejected** — ~300× the cost per answer, slow, no cheap impact preview, and nondeterministic
  (order would jump for reasons unrelated to the answer).
- **Confidence is surfaced, not folded into fit** — a score moves the ranking by exactly its
  weight and nothing else, so "why is this candidate here" stays answerable. Confidence-weighting
  was considered and rejected for M8.
- **Qualitative labels are relative bands** (Strong/Promising/Mixed/Limited) by pool
  percentile, not fixed thresholds — matching "how does THIS pool vary" and keeping numbers as
  supporting detail per the SPEC's "hidden internal scores support ranking; the UI explains in
  plain language."
- This decision is what makes the tier-list interactions (ADR 0006) and the per-dimension
  score cache (ADR 0007) possible, and it satisfies the hard product requirements
  (pre-run cost estimates, caching, auditability, eval-replayability) that a runtime-variable
  call graph would fight.
