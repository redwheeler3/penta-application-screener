# 9. Signed −1..+1 scoring scale with silence = neutral

- Status: **accepted** (still holds; supersedes two intermediate absence policies)
- Date: 2026-07-17

## Context

Each candidate is scored per discovered dimension. An unaddressed dimension ("the applicant
said nothing about this") needed a defined score. The absence policy went through three
positions before settling:

1. **Absence → 0.0, empty evidence.** The eval judge correctly called it unsupported — an
   empty citation justifies no score.
2. **0.0 with a stated basis** ("not addressed in application") — floored but auditable.
3. **0.5 neutral on a [0,1] scale.** Viewing a dimension in isolation exposed #2's flaw:
   flooring absence to 0.0 ranks someone who said *nothing* **below** someone who explicitly
   says they're a poor fit — an indefensible inversion, since **silence is not evidence.** But
   on a re-score the prompt kept losing: 66 of 99 zeros were absence-worded yet still scored
   0.0, most at high confidence. Two forces beat the "0.5" instruction — the model's deep
   prior that **0 = nothing**, and many `low_end` poles literally *worded as absence* ("no
   skills mentioned"), so silence pattern-matched the low pole. On [0,1], "nothing" and "worst"
   collide at 0.

## Decision

**Move to a signed −1..+1 scale: −1 (low_end) · 0 (neutral / no-signal) · +1 (high_end).**
This separates "nothing" from "worst" — the model's "0 = nothing" prior now lands *exactly*
where we want silence, instead of fighting it. Plus an explicit prompt line for the residual
pole-text force: *"a `low_end` worded as absence still means a DEMONSTRATED low — an
unaddressed dimension scores 0, not −1."*

## Consequences

- **Mathematically identical to 0/0.5/1** (an affine remap; all ranking math — fit, pool_mean,
  impact, relative bands, Pearson — is scale-invariant), but **cognitively the right frame for
  an LLM.** `DimensionScore.score` constraint widened to `ge=-1.0`; neutral placeholder 0.0;
  the UI bar remaps [−1,+1] → [0,100%] with neutral at centre, bands red (bottom quarter) /
  blue (middle, where silence sits) / green (top quarter).
- **Accepted consequence (explicit, Jeff):** a candidate who addresses almost nothing floats
  to neutral and thus ranks above one who is explicitly a poor fit — fair, because we have no
  evidence against the silent one.
- Kept the clean top-down fit formula (confidence surfaced, not folded; confidence-weighting
  rejected as it would reward strong-but-narrow over broad-but-thorough).
- **Two scoring golden cases guard the rule:** an empty citation must land in a neutral band
  (not negative), and evidence saying "not addressed" must too (the exact pole-floor bug
  signature — a −1 fails it). The prompt-version bump re-scores every dimension on the next
  Rank, which is itself the measurement of whether the signed scale fixed the 66 leaks.
- See `docs/ai-evals.md` ("Absence policy").
