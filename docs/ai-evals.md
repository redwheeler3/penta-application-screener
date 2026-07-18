# AI Evaluations

This guide records how Penta evaluates AI-assisted ranking quality, the boundary
between the application and its evals, and the current maturity of each layer.

## Purpose

Ordinary tests answer whether the software works: an endpoint returns the right
shape, a cache invalidates, or a ranking run saves scores. AI evaluations answer
whether the model's *judgements* are good: criteria are meaningful, distinct,
oriented, and grounded in evidence.

Penta needs both. The final ranking is deterministic math over committee weights
and stored scores, but discovery, decomposition, matching, consolidation, and
scoring make semantic model judgements. Plausible-looking prose is not enough
evidence that those judgements are sound.

The practical goals are to:

- catch regressions when a production prompt or model changes;
- distinguish a prompt/model failure from a pipeline/storage bug or an unresolved
  committee policy decision;
- make known weak cases repeatable rather than relying on memory of a past run;
- keep evaluation separate from production ranking decisions.

## Layers

### Software tests

Unit and API tests prove the plumbing: schemas, caching, persistence, cost
accounting, and UI/API contracts. They are deterministic and run normally in
the test suite.

### Deterministic property evals

`backend/app/evals/invariants.py` reads a committed, PII-safe Rank fixture and runs
**invariants** — checks that are ALWAYS a bug regardless of pool (a dimension missing a
pole; a criterion keyed on a protected class). A breach fails pytest.

The invariant/signal distinction still matters conceptually — a check you'd have to
soften to keep green is a *signal* (a judgement call), not an invariant, and belongs in
the LLM-judge evals, not the CI gate. Two such signals once lived here (high-correlation
dimension pairs; carry-forward rate), but they duplicated — worse — what the **AI Quality
tab** shows over the *live* run (Consolidation nominations with verdicts; the Matching
reuse rate), so they were retired. Only invariants remain in `invariants.py`.

### Manual LLM judge

`backend/app/evals/judge.py` covers semantic questions a program cannot answer
honestly, such as whether a proposed merge loses a meaningful distinction or
whether a structured decomposition result follows its own written decision.

Run it from the in-app **AI Quality tab** → Judge subtab: a whole-set "Run judge +
agreement" or a per-case "judge"/"stability" run. (There is no CLI wrapper any more;
the tab calls the same `judge_case`/`stability_run` functions directly.)

It is intentionally **manual and non-gating**:

- it never runs during Rank, pytest, or normal CI;
- it makes paid Bedrock calls only when someone confirms a run in the tab;
- it cannot modify criteria, scores, rankings, or the database;
- a disagreement is a review signal, not an automated correction.

## Production vs. judge identity

There are two independent prompts and models:

```text
Production Rank                     Evaluation
---------------                     ----------
production prompt + model           judge prompt + model
          |                                     |
          v                                     v
criterion / score / decision  -->   verdict on that output
```

The production identity tells us what generated the output under review. The
judge identity tells us how it was evaluated. A mature eval record needs both;
otherwise a change in the judge can be mistaken for a change in production
quality.

The `Prompt:` and model line printed by the judge command refers to the **judge**
prompt and model. Each committed case additionally carries the **production**
provenance (`pass_models` + `pass_prompt_versions`) of the run it came from, so a
verdict is attributable to both identities.

### Same information, different prompt (the fidelity rule)

The judge must see **exactly the information the production step saw — no more,
no less** — even though its *prompt* differs. The prompt is allowed (encouraged)
to differ: production asks the model to *perform* a task; the judge asks whether
the resulting decision was *defensible*, and reusing the production wording would
repeat its framing and risk repeating its error. But the *evidence* must match
production's exactly. If the judge is handed a fact production never had, a
disagreement can no longer be attributed to judgement — it may just be the
information asymmetry, and the eval proves nothing.

Worked example (consolidation): the production confirm call sees only the two
dimension **definitions**, plus the qualitative constant that the pair "scores
near-identically" (that framing lives in its system prompt). So each judge case's
`evidence` carries only `definition_a`/`definition_b`, and the "scores alike"
constant lives in the judge instructions. The correlation **`r` value and any
description of *how* the pair diverges are withheld** — production never sees
them, so the judge must not either. Those live only in the case's
`label_rationale`, which is the *labeler's* justification (ground truth may use
more information than the model under test) and is never shown to the judge.

### Why `r` stays out of the confirm step (nomination vs. confirmation)

`r` (score-vector correlation) has two roles, and it is only valid in one. In
**nomination** — the deterministic gate "is this pair worth checking?" — `r ≥
threshold` is exactly right. In **confirmation** — "*why* do they score alike:
same concept, or a confound?" — `r` cannot discriminate: two genuinely distinct
axes can correlate at 0.95 (conscientious people both arrive on time *and* dress
neatly, yet a punctual slob splits them). Only the definitions answer the confirm
question. Feeding `r` into the confirm step therefore adds no discriminating
signal while anchoring the model toward merge on a big number — amplifying exactly
the rationalization bias in the higher-stakes direction (a wrong merge is
unrecoverable; a wrong keep self-heals next run). So the math nominates, the model
judges concepts, and the number stays on the math side of the line — a
specialization of the project's "the LLM extracts features; the math does the
ranking" spine. (Decided 2026-07-16.)

## Application/eval interface

The boundary is one-way and explicit:

```text
Application database
  -> completed Rank output
  -> explicit PII-safe fixture capture
  -> offline deterministic evals and manual judge
```

`backend/app/evals/fixture.py` records a safe subset of a completed Rank:

- criterion definitions and poles;
- structured decomposition, match, and consolidation audits;
- score vectors whose application IDs are replaced by opaque positions.

It excludes applicant names, contact data, raw rows, essays, and model narrative
that can quote those sources. Evals consume this snapshot; they never feed a
verdict back into the application.

Judge cases are committed in `backend/eval-data/judge_cases.json` and
loaded by `load_cases()` (no longer hardcoded). Each case carries the exact
PII-safe criterion/audit evidence, the human `expected` verdict, a written
`label_rationale` (the *why*, so a disagreement is weighed against recorded
reasoning rather than a bare verdict), the `provenance` of its source run
(models + prompt versions), and a `source` pointer. The label rationale is
deliberately kept OUT of the judge prompt — revealing the expected verdict would
defeat the evaluation.

The seed cases are three exact KEEPs on high-correlation dimension pairs — the
judge's most important discipline is resisting over-merge on correlation alone,
and each pair correlates strongly (r=0.84–0.89) yet measures a genuinely distinct
axis:

- `values_vs_social_keep` (r=0.84) — co-operative values (ideology) vs. communal
  social orientation (behaviour). From the committed `rank_baseline.json`; its
  source run predates provenance capture, so its `provenance` is a note.
- `disposition_vs_community_keep` (r=0.86) — philosophical co-op motivation vs.
  active social investment (hosting, organising). From Rank run 4, with exact
  `pass_models`/`pass_prompt_versions`.
- `specificity_vs_followthrough_keep` (r=0.89) — essay writing quality vs.
  behavioural follow-through. A cross-run fork-heal: `essay_specificity`'s
  definition is from run 4, `follow_through_reliability`'s recovered from run 1
  (the last run it was a live dimension). Exact provenance from run 4.

A fourth case balances the set with a clear MERGE:

- `pet_situation_ownership_merge` (r=0.904) — pet ownership vs. pet situation,
  a genuine duplicate the consolidation pass merged. Tests that the judge will
  actually merge a true duplicate, not just resist over-merging. From Rank run 5.
  This one is a worked example of why definition capture matters: the merge
  removed `pet_situation` from the settled report, and the run predated the
  audit-capture fix, so its definition had to be recovered from run 5's raw
  discovery report. Runs after the fix carry `definition_keep`/`definition_drop`
  on the `consolidate_audit` pair row (added 2026-07-16), so a merge case is
  self-contained from the audit alone — no discovery-report spelunking.

A fifth case is deliberately **contested** — a first-class category, not a
degenerate label:

- `trade_skills_licensed_handson_keep` (r=0.925) — licensed vs. hands-on trade
  skills. Both verdicts are defensible *from the definitions the model is given*:
  MERGE (the same core capacity; the unlicensed-crafts extension is marginal) and
  KEEP (formal certification vs. practical breadth is a real distinction) are each
  coherent. The decision turns on how MATERIAL the divergence is for THIS pool —
  which only the withheld score distribution settles — so neither production nor
  the judge can resolve it from the inputs. The leaning was **flipped merge→keep
  (2026-07-16, recorded in the case's `label_rationale`)** on a definitions-first
  principle held independently of the judge — distinct concepts stay apart, we
  don't merge just because they rarely diverge in one pool. Crucially this was NOT
  the judge dictating the label: the judge (keep, 5/5 on the stability run) merely
  agreed with a reconsidered human view, and the case stays `contested` because the
  MERGE argument remains genuinely coherent. A worked example of the honest way to
  change a label — reconsider the merits, record why, keep the ambiguity — vs. the
  rubber-stamp trap of tuning the label to match the judge.

  A contested case carries `contested: true`; its `expected` is the human's
  *leaning*, not an answer key. The judge command marks it `[contested]` (never
  `[ok]`/`[review]`) and prints "leaning" rather than "expected". Agreement is
  neither pass nor fail — it is always review material. This keeps the eval honest:
  some decisions are legitimately under-determined by the evidence, and an eval that
  forced a verdict on them would just be punishing the judge for a defensible call.
  What matters for a contested case is **consistency across repeated runs**, not
  which side a single run picks — instability there is the escalation-ladder signal
  (multi-judge vote), the verdict *direction* is not.

A sixth case extends coverage to a **second AI step** — decomposition, not
consolidation. Each case carries a `pass` field (default `consolidation`) so the
report groups by step and coverage across the pipeline is visible:

- `health_safety_decompose_merge` — three health/safety dimensions, each
  discovered by a different parallel discovery worker, folded into one settled
  axis by decomposition ("all three keys are identical in definition and scoring";
  a clean same-concept fold). Labelled MERGE. This exercises a genuinely different
  judgement from the consolidation cases: decomposition judges from **definitions
  alone, pre-score, with no correlation signal**, and folds N carvings at once
  rather than adjudicating a pair. The harness is step-agnostic — the same
  MERGE/KEEP verdict serves both — so the only per-step additions are the `pass`
  label and the case's own self-describing `task`. Evidence is the three
  definitions exactly as the decomposition call saw them (from run 6's raw
  discovery reports); the model's own "straightforward merge" decision is withheld
  from the judge, per the fidelity rule.

Two earlier generalized historical cases (a health/social merge and a
decomposition routing drift) were dropped: their source runs were not retained,
so they could never be made exact, and a generalized case masquerading as exact
is worse than none.

## Human labels and judge disagreements

The seed case's label is based on manual analysis recorded with the case (its
`label_rationale`). It is a starting point, not yet a formal
independently-labelled dataset. A judge disagreement on it — for instance the
judge merging the values/social pair on its r=0.84 correlation despite the
recorded KEEP rationale — is useful evidence, not an instruction to tune the
judge until it agrees. It may mean:

- the judge is over-weighting an edge case;
- the generalized case omitted important context;
- the original human label is legitimately debatable; or
- the product policy needs a clearer merge rule.

The judge's role is to expose this uncertainty for human review, not to create a
self-confirming answer key. When the third bullet is the settled explanation —
the label is legitimately debatable because the evidence under-determines it — the
case graduates to the `contested` category above, where disagreement is expected
by construction rather than treated as a signal about either side.

## Design rules

- The judge has a **separate prompt** from production. Production prompts ask the
  model to perform a task; a judge asks whether the resulting decision was
  defensible. Reusing the production prompt would repeat its framing and risk
  repeating its error.
- Give the judge the relevant production output, PII-safe evidence, and the
  applicable product rule. Do not reveal the expected human verdict.
- Keep the judge's prompt version derived and report its model, tokens, and cost.
- Use a structured verdict and concise reason so results can be compared.
- Do not make stochastic judge output a normal CI gate or a production mutation.
- Treat model disagreements as inputs to review, not proof that either side is
  correct.

## Next checkpoint

Before treating judge agreement as a meaningful quality measure:

1. ~~Move seed cases into a dedicated PII-safe fixture with exact relevant
   production artifacts, production model/prompt metadata, a human label, and a
   written label rationale.~~ **Done (2026-07-16):** cases live in
   `judge_cases.json` with exact evidence, label + rationale, and provenance;
   the fixture recorder now captures per-pass models + prompt versions. Growing
   the set to exact-by-construction from future runs is the retention discipline
   (see `.clinerules`: durability lives in committed fixtures).
2. Build a small balanced labelled set: clear merges, clear keeps,
   narrative/output contradictions, and intentionally ambiguous cases.
   **In progress (2026-07-16):** three clear KEEPs, one clear MERGE, and one
   contested case seeded. Still owed: a narrative/output-contradiction case (the
   decompose routing-drift signature — SPEC golden case #2).
3. Calibrate the judge on the clear cases first. Ambiguous cases remain review
   material, not pass/fail scoring.
4. Add persistence and a trend view only after the labelled set is useful.
5. ~~Design a separate safe evidence fixture before adding score-defensibility
   cases, because that category is closest to applicant text.~~ **Done
   (2026-07-16):** see "Score-defensibility evals" below — the safe substrate
   turned out to be a synthetic-source guard, not a separate scrubbed fixture.

## Score-defensibility evals (built 2026-07-16)

The highest-value judge category: **does the applicant's cited `evidence` support the
`score` the scoring pass gave?** (`SUPPORTED`/`UNSUPPORTED`.) It is the one category that
must show the judge an applicant quote — the quote is the thing under test — so it can't
follow the "strip all applicant text" rule the other categories use.

**Safe substrate = a synthetic-source guard, not a scrubbed fixture.** A quote is
committable only when its pool is synthetic. The DB can't infer synthetic-vs-real (both
arrive as a Google Sheet id on `SyncRun`), so `app/evals/synthetic_guard.py` holds an
allowlist of known-synthetic sheet ids; `require_synthetic_pool(run)` traces a run →
its source `SyncRun` → sheet id and **refuses** anything not allowlisted (fail-safe: a
real deployment's sheet is rejected by default). To make that link exist, `create_run`
now stamps `RankingRun.source_sync_run_id` with the latest import (it was a latent unused
FK). `python -m app.evals.capture_scores` proposes opaque-indexed candidate cases from a
run, guard-gated, `evidence_source`-stamped; a human labels `expected` + rationale before
they land in `judge_cases.json` (capture never labels).

Three "clear" seeded cases show the basic spectrum: empty evidence → 0.0 against an
absence-defined low pole (**supported**), a 50/50 income split → 0.95 dual-earner
resilience (**supported**), and a mid 0.5 on **empty** evidence (**unsupported** — an
unanchored guess, the score-not-grounded failure the category exists to catch). Note the
deliberate boundary: this asks "is the CITED evidence sufficient?", NOT "did the pass cite
the BEST evidence?" (the latter needs full applicant text — a different, harder eval,
deferred).

**Adversarial cases — because a clean sweep on clear cases proves too little.** A first
judge pass went 10/10, which prompted a leak audit: confirmed the prompt serializes ONLY
`task` + `evidence` (no `expected`, `label_rationale`, `title`, `key`, or `provenance`
reaches the model — the only occurrence of the verdict words is the task's own "SUPPORTED
or UNSUPPORTED" choice-list, which names both options equally, not a tell). So no leak —
but the clear cases are *easy by construction* (surface cue = answer: empty→low,
rich→high), so 10/10 shows the judge handles clear cases, NOT that it discriminates. A
"empty=unsupported, full=supported" pattern-matcher would also pass them. Two adversarial
cases were added where the **surface cue fights the correct answer**, to tell a real judge
from a cue-matcher: (a) `coop_motivation` — rich, values-flavoured evidence at 0.7, but
half of it is *environmental* ethics (off-axis for *co-operative* motivation), so the
correct verdict is **unsupported** despite the "lots of nice text" cue (an exact 0.7 slice
— a real overclaim the pass made); (b) `child_age_profile` — a terse "Children ages 14,
11, 8" at 0.65, **supported** because for an age-profile dimension the bare ages ARE the
complete evidence, testing that the judge doesn't equate brevity with insufficiency. These
are the cases whose result actually means something.

## Coverage across the AI steps (2026-07-16)

The judge harness is step-agnostic — each AI step is just a verdict pair + a per-step
evidence shape on the shared `JudgeCase`/`stability_run` machinery. As of tonight it
covers **five of the six** model steps:

| AI step | Judge question | Verdict pair | Cases |
| --- | --- | --- | --- |
| Screening | Is the flag warranted by its cited evidence + policy? | `flag_supported`/`flag_unsupported` | 9 (6 supported, 3 over-reach) |
| Discovery | *(covered via decomposition — discovery output is its input)* | — | — |
| Decomposition | Same-concept fold? / narrative-vs-routing drift | `merge`/`keep`; drift via detector | 2 folds + drift aid |
| Matching | Is this new dim the same concept as the prior it matched? | `matches`/`mismatches` | 3 (2 match, 1 constructed mismatch) |
| Consolidation | Merge or keep this correlated pair? | `merge`/`keep` | 5 |
| Scoring | Does the cited evidence support the score? | `supported`/`unsupported` | 5 |

**Screening** reuses the score-defensibility pattern exactly (it also cites applicant
text), so its cases go through the same synthetic-source guard, and `capture_screening.py`
mirrors `capture_scores.py`. One fidelity nuance: pet-policy flags are judged against the
policy, so the capturer injects the *resolved* policy line the pass actually saw (from
settings) — not just whatever the flag's quote happened to name — so the judge isn't ruling
on a partial policy. The over-reach cases (child surname differs from parents; email name ≠
applicant name) are the discriminating ones — real flags the pass produced that a screener
shouldn't act on.

**Matching** is definition-only (no PII), so cases need no guard. Run 2's 25 real matches
all inspected correct (the pass is high-bar by design), so there was no natural
`mismatches` to catch — one is *constructed* by pairing two real verbatim definitions from
different concepts (trade skills vs. financial governance), clearly flagged as constructed.
A wrong match is the pass's high-stakes error (it corrupts a carried-forward score), so
having the mismatch direction covered matters even absent a live failure.

**Decomposition drift** (`app/evals/decompose_drift.py`) is a *manual hunting aid*, not a
seeded case or a gate: run it by hand to surface candidate narrative-vs-routing
contradictions (prose claims a key folds in here, but it routed elsewhere — SPEC golden
case #2). It's a tightened heuristic (suppresses the benign "distinct from X" and
"X's component is covered by Y" split-routing patterns that naively flagged 22/run); on the
runs to date it finds **zero** real drift — decompose is behaving well — so no case is
seeded. It earns its keep the run it finally catches one. Subtle no-key-named drift remains
the LLM judge's job (that's the `matches`/`mismatches` task applied to a decision).

## Judge-vs-human agreement metrics (built 2026-07-16)

Best practice (Arize, Evidently, Pragmatic Engineer, 2025/26) is unanimous: before you
trust an LLM-as-judge, **validate it against human labels with real metrics** — an
eyeballed "5/5" isn't validation. So a whole-set judge run (the AI Quality tab → Judge →
"Run judge + agreement") returns, after the per-case verdicts, a `score_agreement`
summary (`app/evals/agreement.py`):

- **Overall agreement** — share of *decisive* cases the judge matched, plus **Cohen's
  kappa** (chance-corrected; raw agreement inflates when one label dominates the set).
- **Per-AI-step agreement** — so a strong `supported`/`matches` score can't hide weak
  `unsupported`/`mismatches` performance (the field's "85% overall can still be unusable"
  warning).
- **Failure-detection recall + precision** — *the number that matters*: of the cases
  whose human label flags a PROBLEM (`unsupported` / `mismatches` / `flag_unsupported`),
  how many did the judge catch, and how many of its problem-calls were right? A judge
  that aces clean cases but misses over-reaches is worse than an overall score implies.

**Contested cases are excluded from every scored metric** and reported separately: their
label is a human *leaning*, not ground truth, so scoring the judge against it would
penalise a defensible call (the field: don't force binary on genuinely indeterminate
cases). It's aggregate-only, no extra cost (same calls as the per-case run), and — like
the rest — non-gating. `merge`/`keep` cases contribute to overall agreement + kappa but
not to failure-recall (neither side is inherently "the problem" — noted in the report so
it isn't a silent omission).

**Best-practices audit (2026-07-16) — where we stand.** Held the system up against the
current LLM-as-judge literature. Aligned, some ahead of typical practice: code-vs-judge
split (deterministic invariants gate CI, judge handles semantics); fixed categorical
verdicts, never 1–10 scores ("easiest to misuse"); the **contested** category (the field's
independently-arrived-at `needs_review` for indeterminate cases); label + rationale +
separate evidence fields; the fidelity rule; judge never gates CI. Gaps this audit
surfaced, now partly closed: **agreement metrics** (this section — was the top gap: we had
no kappa/recall, only eyeballed agreement). Still open, deferred with reason: a **holdout
set** (our cases are both calibration and test — small set, revisit as it grows); **judge
drift tracking** over model/prompt versions (the deferred judge-score-persistence item —
validated as real by the research, still gated on a run cadence); and a **bias audit**
(self-preference — judge and production are both Claude; verbosity — the coop_motivation
case hinted richer text scored favourably). Documented as known risks, not yet measured.

**First real agreement run (2026-07-16) — what measuring bought us.** The first scored
run came in at **86% overall / kappa 0.83 / failure-recall 4/6 (67%)** — and the recall
number is the whole point: a per-case skim of green checks read "great," but the metric
said the judge missed a third of the problem cases. The three disagreements resolved into
two findings, handled by the discipline "a disagreement re-examines the label or is
recorded — never tunes the judge":

- **Label bug fixed (agreement rose honestly to 91% / kappa 0.89 / recall 71%).** The
  judge called a 0.0-on-EMPTY-evidence score *unsupported*; our label said *supported*
  (leaning on the low_end pole). The judge was right and we agreed: the eval judges "is
  the CITED evidence sufficient?", and an empty evidence field cites nothing — it can't
  justify any score, high or low. `score_outdoor_grounds_absent_*` flipped
  supported→unsupported, making our two empty-evidence cases internally consistent
  (empty→0.0 and empty→0.5 are both unsupported). Agreement rose because a label improved,
  not because the judge was tuned.
- **Known judge weakness kept on the record (recall capped at 71% by design).** The judge
  consistently rules a name≠email mismatch a *supported* fake-contact flag; we hold it's
  benign over-reach (people routinely use non-name emails) and kept both cases
  `flag_unsupported`. These stay as genuine judge misses — NOT relabelled to agree, NOT
  used to tune the judge. So **the judge over-flags name/email mismatches** is a measured,
  documented limitation to weigh before trusting it on screening over-reaches. (It ruled
  consistently on both instances — stable, just more aggressive than we want.)

**Absence policy — settled at NEUTRAL 2026-07-17 (after two intermediate positions).** The
empty-evidence score the judge flagged sent us through three positions on how an
*unaddressed* dimension should score, and it's worth recording the whole arc because the
final answer reverses an earlier same-day decision on purpose:

1. **Empty→0.0 with empty evidence (old prompt).** The judge called it unsupported — an
   empty citation justifies no score. Correct.
2. **0.0 with a stated basis ("not addressed in application").** First fix: keep flooring
   absence to 0.0 but make it auditable, on the rationale "the application solicits this,
   so silence is a genuine signal the committee ranks below demonstrated evidence."
3. **0.5 NEUTRAL on the [0,1] scale.** Viewing a single dimension in isolation exposed the
   flaw in #2: flooring absence to 0.0 ranks someone who said *nothing* **below** someone who
   explicitly says they're a poor fit ("my calendar is packed, minimum hours only"). That
   inversion is indefensible — **silence is not evidence.** So absence should be neutral
   (0.5). BUT a re-score revealed the prompt kept losing: **66 of 99 zeros were absence-worded
   yet still scored 0.0**, most at HIGH confidence. Two forces beat the "0.5" instruction: the
   model's deep prior that **0 = nothing**, and many `low_end` poles literally *worded as
   absence* ("no skills mentioned") — so silence pattern-matched the low pole. On a [0,1]
   scale "nothing" and "worst" collide at 0, so neutral-in-the-middle never won.
4. **Signed −1..+1 scale (final, 2026-07-17).** Separate "nothing" from "worst" by moving to
   **−1 (low_end) · 0 (neutral/no-signal) · +1 (high_end)**. Now the model's "0 = nothing"
   prior lands *exactly* where we want silence, instead of fighting it. Mathematically
   identical to 0/0.5/1 (an affine remap — all ranking math is scale-invariant: fit,
   pool_mean, impact, relative bands, Pearson), but **cognitively** the right frame for an
   LLM. Plus an explicit prompt line for the residual pole-text force: *"a `low_end` worded
   as absence still means a DEMONSTRATED low — an unaddressed dimension scores 0, not −1."*
   `DimensionScore.score` constraint widened to `ge=-1.0`; neutral placeholder 0.0; UI bar
   remaps [−1,+1]→[0,100%] (neutral at centre) and bands to red (bottom quarter) / blue (two
   middle quarters, where silence sits) / green (top quarter).

Accepted consequence (Jeff, explicit): a candidate who addresses almost nothing floats to
neutral and thus ranks **above** one who is explicitly a poor fit — fair, because we have no
evidence against the silent one. Kept the clean top-down fit formula (confidence
surfaced-not-folded; confidence-weighting rejected as it would reward strong-but-narrow over
broad-but-thorough). Two judge cases guard the signed-scale absence rule: an empty citation
can't justify a negative score, and evidence saying "not addressed" can't justify a negative
score (the exact pole-floor bug signature). A real new-behavior case (evidence="not
addressed…", 0 → supported) is still to be harvested from a Rank under the new prompt, not
fabricated (fidelity rule). Prompt-version bump re-scores every dimension next Rank; the
next re-score is the *measurement* of whether the signed scale actually fixed the 66 leaks.

## Stability harness (built 2026-07-16)

The AI Quality tab → Judge → "Run stability (K=5)" (or a per-case "stability" link) judges each selected case **K times on
fixed inputs** and reports verdict stability, rather than a single agree/disagree.
This is the escalation-ladder measurement: the open question is not "did the judge
agree with the label?" (one call answers that) but "does the same call, on the same
evidence, return the same verdict every time?" A non-contested case that flips
run-to-run is flagged `[UNSTABLE]` — that noise is what would justify spending up on
the multi-agent shape (N-judge voting / adversarial skeptic). A perfectly steady case
reads `[stable]`; a contested case that splits reads `[contested-split]` (expected,
informational — for a contested case, *consistency* is the signal, not verdict
direction). `agreement` is the modal verdict's share of K. Costs K× a normal run, so
it stays a deliberate manual invocation. This is the tool step 3's calibration uses:
run the clear cases at K≥5 and confirm they don't flip before trusting the judge; the
decision to build (or not build) multi-agent escalation reads these numbers.

## Live scoring eval (built 2026-07-17)

The live scoring eval (AI Quality tab → Live scoring) closes the gap the other
evals leave: the judge cases and the `invariants.py` checks both grade a *recorded*
artifact, so they catch a bad re-baseline and code rot but are **blind to a prompt/model
regression** — the model never runs. The signed-scale absence bug proved it: the invariant
suite stayed green through the whole regression because the frozen fixture never changed.
This eval **tests the actual prompt** — freeze the INPUTS, run the REAL prompt+model, grade
the FRESH output. That distinction (frozen *output* = regression test; frozen *input* + live
output = prompt eval) is the one that matters.

Golden inputs live in `fixtures/scoring_golden.json`: hand-authored **synthetic** applicants
(fictional, so committable with no synthetic-pool guard) + one dimension each, run through
the exact production `dimension_scoring` prompt on the configured scoring model. Two grader
tiers, by what each can honestly decide:
- **Deterministic assertions** (the bulk, cheap, unambiguous): score in `[-1, 1]`, an
  unaddressed dimension scores 0 (neutral — the flagship regression check), a stated
  confidence, non-empty evidence. These are what an `assert` can settle.
- **Rubric judge** (the subjective residue): for a case asserting "this SHOULD score
  high/low", it reuses the validated `judge.py` SUPPORTED/UNSUPPORTED rubric to ask whether
  the produced score is defensible against its evidence — not a reference-match to an
  "expected" number (open-ended scoring has no single right answer; a reference-match would
  be brittle).

Makes real model calls (costs money, non-deterministic), so it is a deliberate,
spend-confirmed tab run, **never in pytest/CI**. The CI half is `tests/test_live_scoring.py`: a structural guard that
the golden fixture loads and is well-formed (both poles, a checkable expectation, bounds in
range) with no model call — so a malformed fixture fails at commit time, not spend time.
`score_equals` uses a tolerance (the model isn't fully deterministic even at temp 0); pin 0
tightly (the value we most care about) and assert ranges/properties elsewhere rather than
exact scores.

## In-UI eval cockpit — the "AI Quality" tab (built 2026-07-17, rewritten to Insights quality)

The evals run from the app under the **AI Quality** tab (renamed from Insights; it now
holds both *observability* — Discovery/Decomposition/Matching/Consolidation/Cost/Trends,
"what the AI did + cost" — and *evals* — "is the AI any good", separated by a divider in
the subtab strip). This is the only run surface; the `judge.sh` / `python -m app.evals.*`
CLI wrappers were retired, and case *harvesting* is now a UI action too (see the Judge
subtab below). Developer/operator surface only (not committee-facing). The eval
subtabs:
- **Invariants** — free deterministic checks; a styled "Re-baseline from current Rank"
  action re-records the committed fixture (replaced the `python -m app.evals.fixture` CLI).
- **Live scoring** — the golden dataset through the real scoring prompt+model.
- **Judge** — the judge case set, run two ways over the *same* cases (one-pass agreement,
  K-repeat stability); cases **grouped by the production pass** each exercises
  (consolidation/decomposition/matching/scoring/screening), so you read the judge's
  accuracy per prompt. A "Harvest cases from current run" panel proposes fidelity-preserving
  candidate cases from the current Rank's scoring/screening output (`GET /evals/harvest/…`,
  synthetic-pool-gated, opaque-indexed); picking one opens it in the editor pre-filled with
  `SET_ME` placeholders to label + save. This is the sanctioned "copy an exact slice from a
  real run" path — the hand-editor can't be, since it can't pull the real evidence the model
  saw — and it supersedes the `capture_scores`/`capture_screening` CLIs.

Each runnable subtab is **master-detail**: a grouped case list on the left, a case's FULL
input on the right (every field, nested objects rendered in full — no truncation), with the
run's result shown above it. Whole-set run buttons + per-case run links (one per mode: a
Judge row runs that one case as judge or stability), all spend-confirmed with the styled
inline card (never `window.confirm`). The model's reasoning streams live **as rendered
markdown**.

Editing is **field-level, not raw JSON** (`StructuredFields`): every scalar is a typed
input, every nested object (evidence / applicant / dimension / expect) is a labeled section
with add/remove — so any case family is editable without a per-family form or a JSON blob.

Architecture / file hierarchy:
- **Code** lives in `app/evals/` (modules) and `frontend/src/components/evals/`
  (InlineConfirm, StructuredFields, EvalCaseDetail, EvalCaseEditor, RunnableEval,
  InvariantsEval). `properties.py` was renamed `invariants.py` (it holds only invariants).
- **Data** lives in `backend/eval-data/` — the versioned corpus (`judge_cases.json`,
  `scoring_golden.json`, `rank_baseline.json`), OUT of the code package. Every module reads
  its path from `app/evals/paths.py`.

Boundaries that keep this honest (dependency flows evals→app, never app→evals):
- **The tab calls the eval runner functions directly** (`run_case`, `judge_case`,
  `stability_run`, `run_invariants`, `record`) — one code path, no CLI/UI drift.
- **Runs stream** via the shared NDJSON vocabulary as Rank/Screen (`thinking` deltas then a
  terminal `summary`); the spend-confirm/call-count come from a free `/evals/catalog`.
- **Runs persist** to an `EvalRun` DB row (result + streamed reasoning) — telemetry,
  queryable for trends, raw material to "eval the eval" later.
- **Cases stay in the versioned JSON dataset**, NOT the DB. Git history, PR review, the
  fidelity rule, and the CI structural guards all ride on the file. The tab edits the file
  (`PUT /evals/cases/{key}`, validated), committed to git deliberately. (Results→DB,
  dataset→version-control is the deliberate split.) A save reformats to `json.dumps(indent=2)`,
  so the first UI edit of a hand-authored fixture churns formatting once, then stays clean.
