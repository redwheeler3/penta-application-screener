# 2. Reframe the eval "judge": blind-then-compare, one deterministic grader per pass

- Status: **superseded** (earlier per-pass inline-judge design replaced 2026-07-18/19)
- Date: 2026-07-18 (grader architecture decided); 2026-07-19 (shipped)

## Context

The observability/evals milestone (M13) needed to grade non-deterministic model passes
(consolidation, decomposition, matching, screening, scoring). The interim design leaned on
an **LLM judge inline in each pass's eval**: every pass would get a judge tier grading its
recorded output, plus per-case `judge?`/`produced?` blocks in the fixture. A multi-source
review (OpenAI evals/graders guides, promptfoo, Raschka, Galtea; 23/25 claims confirmed
adversarially) was run before building to test whether three signals (label +
production-vs-label + independent judge) beat something simpler.

The core failure modes identified: a judge shown the human label rubber-stamps it; and a
judge grading a case you can already exact-match is redundant cost.

## Decision

**Match the grader to the output shape, and make the judge a blind auditor — not a gate.**

- **Categorical passes** (consolidation/decomposition `merge·keep`, matching
  `matches·mismatches`, screening `flag_supported·flag_unsupported`) grade by
  **deterministic exact-match**: `production_verdict == expected`. No judge — a judge on a
  case you can exact-match doesn't earn its cost.
- **Scoring** (continuous) grades a **band** (`expected = {score_min, score_max}`); the
  produced score must land in range. Still deterministic.
- **The judge moved wholesale to the Judge tab as a generic blind label-auditor.** For every
  golden case across all five passes, an independent model reproduces that pass's output
  from an editable per-pass `judge_background` brief + the case's `given`, **blind to the
  label**, and the harness grades that blind output with the pass's own grader. Agreement
  (Cohen's κ, target ≈ human-human ~0.80) calibrates the judge; a consistent disagreement on
  a subjective case flags the *label*, not the pass. Blindness is load-bearing (judge sees
  `given` + `judge_background` only, never `metadata`).
- The judge is run **occasionally as audit/calibration**, never per-run and never a CI gate.
  The deterministic invariants stay the only commit gate.
- `judge_cases.json` was mined into the per-pass `<pass>_golden.json` files, then retired.

## Consequences

- One clear grader per pass; the redundant "judge grades what a regex could" cost is gone.
- The Judge tab answers two useful questions it couldn't before: *are our `expected` labels
  defensible?* and *is our judge trustworthy (κ vs. human)?* — demoted from grader to
  audit instrument, which resolved the long-parked "how useful is judge-the-judge?" question.
- The multi-agent judge escalation (N-judge voting / adversarial skeptic) was **not built**:
  a K=5 stability run on real Bedrock showed the single blind judge is stable on all
  clear-answer cases; only genuinely-contested cases split, as designed. Re-open only if a
  non-contested case flips on fixed inputs.
- See `docs/ai-evals.md` ("Grader architecture") and `docs/eval-case-schema.md` for detail.
