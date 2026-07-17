# Score-Defensibility Evals — Design (for review, not yet built)

Draft 2026-07-16. This is a design to react to before any code. It extends the existing
LLM-judge harness (`app/evals/judge.py`) with a new eval category — **is a dimension
score defensible from the evidence it cited?** — and does so in a way that generalizes to
the remaining un-evaled AI steps (screening, matching), per the north star: **eval every
AI step through one shared harness.**

## The question this eval asks

The scoring pass emits, per (applicant, dimension): a `score` (0..1), a `rationale`, and
an `evidence` quote/field-reference. Defensibility asks: **given the dimension's
definition and the cited evidence, does that evidence support that score?** Failure modes
to catch:

- **Overclaim** — high score, evidence too thin ("I'm pretty handy" → 0.9 on trade depth).
- **Underclaim** — low score despite strong cited evidence.
- **Absence-as-presence** — a confident score where the evidence is silence/irrelevant
  (the pass is explicitly told absence is a low score, not a guess — this checks it held).
- **Evidence-mismatch** — the quote is about a different concept than the dimension.

## Why this category is different (the PII crux, and today's reprieve)

Every other eval category judges *model output about the axes* (definitions, merge
decisions) — safely committable. Score-defensibility must show the judge the **`evidence`
quote**, which is applicant text **by construction** — the exact thing the existing
fixture rule strips. So it cannot follow "strip all applicant quotes."

**Today's reprieve:** the current pool is SYNTHETIC, so its evidence quotes are not real
PII and can be committed exactly. That makes exact-from-run cases possible now — better
than hand-authored, because they carry true provenance and test the real scoring prompt.

**The forever-risk this creates:** the same capture path, pointed at a REAL pool later,
would silently commit real applicant quotes. So the design's load-bearing safety element
is not "evidence is fine" — it is:

> A score-defensibility case is committable **only when its source pool is marked
> synthetic**, and every case records `evidence_source` naming that pool. The capture
> tool REFUSES to emit a committable case from an unmarked/real pool.

This mirrors the DB-guard hook philosophy: make the unsafe path impossible, not merely
discouraged.

## Proposed case shape

Reuses `JudgeCase` (already `pass_name`-tagged and step-agnostic). A scoring case:

```json
{
  "key": "score_handy_overclaim",
  "pass": "scoring",
  "title": "‘Pretty handy’ does not support a high trade-depth score",
  "task": "Given the dimension and the applicant's cited evidence, decide whether the score is SUPPORTED or UNSUPPORTED by that evidence.",
  "evidence": {
    "dimension": "hands_on_trade_skill_depth",
    "dimension_definition": "Depth/breadth of demonstrated building-system trade skill…",
    "high_end": "…", "low_end": "…",
    "cited_evidence": "\"I'm pretty handy and can probably fix most basic things.\"",
    "score": 0.9
  },
  "expected": "unsupported",
  "label_rationale": "A vague self-assessment with no specific trade, credential, or task…",
  "evidence_source": "synthetic-pool: rank run <id> (2026-07-16), applicant <opaque idx>",
  "provenance": { "pass_models": {...}, "pass_prompt_versions": {...} }
}
```

Note: NO `application_id` and no name — the applicant is referenced by opaque index, same
as score vectors. Only the cited quote (synthetic) + the score travel.

## New verdict pair

`JudgeVerdict` gains `SUPPORTED` / `UNSUPPORTED`. (It already holds merge/keep +
matches/mismatches; this is the third pair. Screening will later add a fourth,
e.g. `flag_supported`/`flag_unsupported` — same pattern.) The judge instructions get a
`## How to judge` bullet for the SUPPORTED/UNSUPPORTED task, mirroring the existing
merge/keep and matches/mismatches bullets. No harness change beyond content — the
step-agnostic machinery (`judge_case`, `stability_run`, `format_*`) already handles it.

## Fidelity rule for this category

The judge must see **exactly what the scoring pass saw for this judgement**: the
dimension definition + poles, the applicant evidence, and the score under test. It must
NOT see the `confidence` field's *meaning* re-explained, nor any hint of the "right"
answer. (The scoring pass sees the full applicant block; the judge sees the *cited*
evidence — which is what "is the CITED evidence sufficient?" is about. If we ever want
"did the pass cite the BEST evidence?" that is a different, harder eval needing the full
applicant text — deferred, flagged here so we don't conflate them.)

## Capture path + the guard (RESOLVED 2026-07-16 — synthetic-source allowlist)

**How we know a pool is synthetic — decided.** The DB cannot infer synthetic-vs-real on
its own: both arrive via a Google Sheet, recorded only as `SyncRun.source_sheet_id`
(the real import path; there is no separate CSV loader). The synthetic pool was created by
exporting `test-data/synthetic-penta-application-responses.csv` into a specific sheet
(`1shuJeJRWL05F4TCQ9yr0-uiQB58MbjaNc6dkokmBn8Y`). So the guard is a **config allowlist of
known-synthetic `source_sheet_id`s**:

- Capture reads the run's originating `SyncRun.source_sheet_id`.
- It emits committable evidence cases **only if that id is on the synthetic allowlist**;
  any other sheet (a real deployment's) is **rejected by default** — fail-safe, not
  fail-open. This is verifiable from data the DB actually has, unlike an operator
  "I promise it's synthetic" flag (asserted, not proven), and it matches the DB-guard
  hook's "make the unsafe path impossible" philosophy.
- Each emitted case records `evidence_source` = the sheet id + run, so a reviewer can
  re-verify the provenance from the committed file alone.

The allowlist lives in config (e.g. `AISettings.synthetic_sheet_ids` or an evals-local
constant seeded with the known id). A real deployment never adds its sheet there, so the
guard can't be tripped by forgetting a flag.

A small CLI, e.g. `python -m app.evals.capture_scores`:
1. Reads scored rows from the current/most-recent run.
2. **Refuses unless the run's `source_sheet_id` is on the synthetic allowlist** (raises
   with a clear message — the safety gate).
3. Emits candidate cases (opaque-indexed, `evidence_source` stamped) for a human to label
   and keep the diagnostic ones. Capture proposes; the human writes `expected` +
   `label_rationale` — same discipline as every other case.

## North-star check: does this generalize to every AI step?

| Step | Judge question | Verdict pair | Status |
|---|---|---|---|
| Screening | Is the flag supported by the essay? | flag_supported / unsupported | future |
| Decomposition | Same-concept fold? / narrative-vs-output drift | merge·keep / matches·mismatches | built + case owed |
| Matching | Is this match the same concept? | matches·mismatches | case owed |
| Consolidation | Merge or keep this pair? | merge·keep | built |
| Scoring | Does evidence support the score? | supported·unsupported | THIS design |

The pattern holds: each step = a verdict pair + a per-step evidence/task shape, all on the
one harness. Score-defensibility is the one with the PII wrinkle; solving its capture
guard also gives us the safe pattern for screening (also applicant-text-facing).

## What I'd build, in order (after this design is blessed)

1. **Synthetic-source allowlist + guard, with tests FIRST** (the safety-critical piece):
   a config allowlist seeded with the known synthetic sheet id, and a guard function that
   refuses a non-allowlisted `source_sheet_id`. Test the refusal path before anything can
   write a case. (Same "build the guard before the thing it guards" order as the DB-guard.)
2. `SUPPORTED`/`UNSUPPORTED` verdict pair + the judge `## How to judge` bullet.
3. Capture CLI (`python -m app.evals.capture_scores`) — proposes opaque-indexed candidate
   cases from the current synthetic run, guard-gated, `evidence_source` stamped.
4. 2–3 seed cases captured + human-labelled (an overclaim, a defensible one, an
   absence-as-presence).
5. Wire into `--stability`; NO persistence yet (still gated on "labelled set is useful").

Deliberately NOT in scope: "did the pass cite the BEST evidence?" (needs full applicant
text — different, harder eval); judge-score persistence/trend (premature); screening +
matching cases (next steps on the same pattern, once this proves the applicant-text-facing
capture path).
