# Case study: making an LLM's scores monotonic when the world isn't

*A 0-to-1 fit score can't be neutral — so which end is "good" has to be decided
somewhere. Where you put that decision turns out to matter a lot.*

This is a design story about a small, sharp constraint that most people wouldn't
notice until it produced a wrong ranking — and about resisting the "smart"
solution in favour of a simpler one that moved the decision to a better place.
Companion to [dimension-convergence.md](dimension-convergence.md) and
[designing-an-ai-feature.md](designing-an-ai-feature.md).

## The constraint (easy to miss, expensive to ignore)

The screener discovers dimensions a pool of applicants varies on, scores each
applicant 0..1 per dimension, and ranks by a weighted sum: `fit = Σ weight ·
score`. That formula has a property that's obvious once stated and invisible
until it bites: **a higher score always pushes fit up.** There is no neutral
score. So for every dimension, *some* end of the axis has to be "the good end,"
and the system has to know which — or the ranking is silently wrong.

Most axes are fine: "participation commitment," more is better. But two kinds of
axis break the assumption:

1. **"Less is better" axes.** "Frequency of maintenance breakdowns" — a high
   score would push fit *up* for the worst applicant. Score direction is
   inverted from the naming.
2. **"Goldilocks" axes** — best value in the *middle*, both extremes bad. Score
   the raw quantity and the ideal applicant reads as a misleading "moderate," and
   a monotonic weight can't express "peak in the middle" at all.

If you don't handle these, the model happily emits "number of pets" or "income
level," scores them literally, and the weighted sum quietly rewards the wrong
end or flattens the peak. Nobody sees it unless they audit the math.

## The tempting solution — and why it was reverted

The first design was the "obvious" one: **let the model tag each dimension with a
direction** — a `more / less / undecided` enum on the schema — and make the
ranking math *sign-aware*, flipping "less is better" axes when it sums. Clean
separation: the model reports direction, the math handles it.

It was designed, built, and then **reverted.** The reasons are the interesting
part:

- It put a **values-shaped decision in the schema and the math.** "Which end is
  good" is sometimes not a fact about the axis — it's a committee policy (are
  pet-welcoming households good or bad? depends on the co-op). Baking a direction
  flag into scoring pretends that's a settled property when it isn't.
- It added a **permanent complexity tax** — every consumer of a score now has to
  respect the sign; `undecided` has undefined ranking behaviour; the math is no
  longer "just a weighted average."
- It solved the problem in the **wrong place.** The direction question is really
  a *discovery* question ("what is this axis, and which way does it point?"), not
  a *ranking* question.

## The resolution — orient at discovery, split when you can't

The kept design removes the flag entirely and pushes the decision up into
discovery, where the axis is defined:

- **Every dimension is oriented so its high end is the desirable end, at
  discovery time.** Discovery recasts a "less is better" axis into its positive
  form — "frequency of breakdowns" becomes "mechanical reliability." The
  definition states which end is high. Ranking stays a plain weighted average
  with no sign logic; there is no direction flag in the schema at all.
- **Goldilocks axes get one of two treatments, by cause:**
  - A peak from *one quantity vs. a target* → **reframe** to the underlying
    monotonic fit-concept. Not "amount of salt" but "seasoned about right"; not
    "income level" but "income distribution balance." One honest more-is-better
    judgment. (Confirmed working on a real run.)
  - A peak from *two opposing forces* a household could have one without the
    other → **emit two separate more-is-better dimensions** and let the
    committee's *weighting* place the peak — never a pre-merged "balanced X." A
    committee request for "a strong primary earner, but not single-income-
    dependent" became two axes: `primary_earner_income_strength` and
    secondary-income contribution. The peak lives in how the committee weights
    them, not in a dimension that hard-codes it.

The through-line: **keep scoring dumb and monotonic; move all the judgment to
where the axis is named or where the human weights it.** The model orients; the
committee owns direction only by ignoring an axis or asking for a rephrase.

A nice detail on the prompt: the orientation examples are kept deliberately
*out-of-domain* (salt, car reliability) so they teach the *move* without leading
the model toward a pool-specific answer it should discover for itself. Teaching
the technique, not the answer.

## The sequel — the same principle, still being pressure-tested

Months later, the [convergence experiment](dimension-convergence.md) surfaced the
exact failure mode this design exists to prevent, in a spot the prompt didn't
fully cover. On a real run, the pool varied on pets — and pets is *direction-
contested* (some co-ops value pet-welcoming households, some don't). The
"two opposing forces → emit two dimensions" rule should have fired. Instead the
model emitted **one** dimension oriented "fewer pets = better," and — tellingly —
*its own reasoning admitted the doubt*: "the committee should determine which
direction aligns with co-op policy." It **recognised** the two-sidedness and
collapsed it anyway, treating its uncertainty as something to note in prose
rather than a trigger to split.

That's a precise, actionable prompt gap: the rule says "split when both ends
carry a fit story," but doesn't land on the *direction-uncertainty* case
specifically. The fix (recorded, not yet shipped): make direction-contest an
explicit split trigger — "if you can't commit to which end is desirable *without
knowing the committee's policy*, that IS the two-dimension case." Same principle
as the original design, sharpened by a real observation.

## Why it's worth keeping

- **A monotonic scoring model is a design choice with teeth.** The moment you
  reduce judgment to a number and sum it, you've committed to "more is better" —
  and every non-monotonic axis in the real world becomes a bug you have to design
  around. Naming that constraint early is the whole game.
- **Move decisions to where they belong.** Direction isn't a ranking concern
  (the reverted flag) — it's a discovery concern (orient the axis) or a human one
  (weight two axes). Putting each decision at its natural layer kept the math
  trivial and the schema clean.
- **The reverted design is the most instructive part.** The direction-flag +
  sign-aware-math version *worked* — it was reverted for being complex and
  putting a values decision in the wrong place, not for being broken. Knowing
  when a working solution is the wrong one is the judgment worth showing.

For the build-facing detail see the "Dimensions are oriented so MORE is better
fit" note in `SPEC.md`; for the live prompt gap see "Prompt Engineering To-Do"
there.
