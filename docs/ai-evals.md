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

`backend/app/evals/` reads a committed, PII-safe Rank fixture. These checks split
into two honest categories:

| Category | Example | Behaviour |
| --- | --- | --- |
| Invariant | Every dimension has distinct high/low poles | Fails pytest: a breach is always a bug |
| Signal | Two dimensions have highly correlated score vectors | Reports for review: correlation can be legitimate |

Do not turn a judgement signal into a hard gate merely to make it measurable.
A check that would need weakening to stay green is a signal, not an invariant.

### Manual LLM judge

`backend/app/evals/judge.py` covers semantic questions a program cannot answer
honestly, such as whether a proposed merge loses a meaningful distinction or
whether a structured decomposition result follows its own written decision.

Run it explicitly:

```sh
bash ./judge.sh
bash ./judge.sh --case decompose_routing_drift
```

```powershell
./judge.ps1
./judge.ps1 -Case decompose_routing_drift
```

It is intentionally **manual and non-gating**:

- it never runs during Rank, pytest, or normal CI;
- it makes paid Bedrock calls only when someone invokes it;
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

Judge cases are committed in `backend/app/evals/fixtures/judge_cases.json` and
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

## Stability harness (built 2026-07-16)

`python -m app.evals.judge --stability K` judges each selected case **K times on
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
