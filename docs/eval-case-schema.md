# Eval case schema

Every eval case — for every AI pass — uses **one identical top-level envelope**. Only the
*contents* of the `input` block and the *type* of `metadata.expected` vary by pass; the shape
you read, edit, and validate is the same everywhere. This is what lets one case serve two
consumers (the live eval and the judge audit — see "Two consumers" below) and lets the Judge
tab read every pass's cases without per-pass parsing.

Cases live in per-pass files under `backend/eval-data/`, named `<pass>_golden.json`:
`scoring_golden.json`, `consolidation_golden.json`, `decomposition_golden.json`,
`matching_golden.json`, `screening_golden.json`. Each file is `{ "_comment": "...", "cases": [ <case>, ... ] }`.

## The envelope

```jsonc
{
  "key": "unique_case_key",          // top-level identity; upsert/dedup/filter key on this

  "metadata": {                      // HARNESS-ONLY — no model, live or judge, ever sees this
    "expected": <verdict|assertion>, // REQUIRED. The human label. Type varies by pass (below).
    "note": "one-line what/why",     // optional: human orientation
    "pass": "consolidation",         // which production pass this case exercises
    "contested": false,              // optional: both verdicts defensible (see ai-evals.md)
    "label_rationale": "why expected is what it is",  // optional but strongly encouraged
    "provenance": { },               // optional: source run's models + prompt versions
    "source": "where this case came from"             // optional: traceability
  },

  "input": { /* WHAT THE PRODUCTION MODEL CONSUMES — shape varies by pass (below) */ },

  "judge": {                         // OPTIONAL. Present ⇒ this case is label-audited by the judge.
    "question": "the instruction posed to the judge"  // phrased as the judge's task
  }
}
```

### Fidelity rule (load-bearing)

The judge is shown **`input` + `judge.question` only** — never `metadata`. Revealing
`metadata.expected` (or `label_rationale`, which often contains the reasoning/`r`-value) would
hand the judge the answer and defeat the audit. This is enforced by the loaders: `metadata`
is flattened into the harness dataclass but never serialized into a prompt. See
`docs/ai-evals.md` → "the fidelity rule".

## Per-pass `input` shapes

The envelope is fixed; `input` carries what that pass's real prompt actually reads.

| Pass | `input` contents |
|---|---|
| **scoring** | `applicant` (facts + essays), `dimension` (key/name/definition/high_end/low_end) |
| **consolidation** | `pair`: `{ key_a, definition_a, key_b, definition_b }` (the two definitions the confirm call compares) |
| **decomposition** | `definitions`: the N carvings decomposition folded (or kept apart) — `{ definition_1, definition_2, ... }` |
| **matching** | `{ new_dimension, prior_dimension }` (the two definitions the match pass compared) |
| **screening** | `{ flag_category, flag_severity, flag_summary, cited_evidence, co_op_pet_policy? }` (the flag + the resolved policy the pass saw) |

`input` must be an **exact slice of what production saw** — the same fidelity discipline as
the recorded judge cases. For applicant-facing passes (scoring, screening) the evidence is
committed only from the synthetic pool (see `synthetic_guard.py`), never a real applicant.

## `metadata.expected` shapes

Categorical passes carry a **string verdict**; scoring carries an **assertion object** (there is
no single right number, so we pin properties, not a value):

| Pass | `expected` |
|---|---|
| **consolidation** | `"merge"` \| `"keep"` |
| **decomposition** | `"merge"` \| `"keep"` |
| **matching** | `"matches"` \| `"mismatches"` |
| **screening** | `"flag_supported"` \| `"flag_unsupported"` |
| **scoring** | assertion object: any of `score_equals`, `score_min`, `score_max`, `confidence` (e.g. `{ "score_equals": 0.0, "confidence": "low" }`) |

## Two consumers (why the schema is unified)

The same case object is read by two evaluators, which is the whole point of the shared shape:

1. **Live eval** (the routine regression net): feeds `input` through the **real production
   prompt**, then grades the output.
   - *Categorical passes:* `production_verdict == metadata.expected` (deterministic exact-match).
     No judge — a judge here is redundant (see the grader-architecture decision in
     `docs/ai-evals.md`).
   - *Scoring:* deterministic assertions from `metadata.expected` **plus** a defensibility judge
     (scoring is continuous/open-ended — the one pass where a judge earns its cost).
2. **Judge audit** (periodic, not per-run): for any case with a `judge` block, the judge
   independently answers `judge.question` from `input` alone, and its verdict is compared to
   `metadata.expected`. This is **label auditing** — a judge that disagrees with our label on a
   subjective case is a signal the *label* may be wrong, and the aggregate judge-vs-label
   agreement (κ) is how we calibrate whether the judge itself is trustworthy. See the Judge-tab
   reframing in `docs/ai-evals.md`.

So `judge` is **optional**: a case with no `judge` block is a pure live-regression case; a case
with one is *also* available for label audit. A case can be both at once.

## Validation

`app/evals/case_store.py` gates writes: only the allowlisted `<pass>_golden.json` files are
writable, and each write must carry the required top-level blocks (`key`, `metadata`, `input`;
`judge` optional) with a non-empty string `key` and a present `metadata.expected`. A bad
payload is refused whole, never partially written. Loaders flatten the envelope into each
pass's flat runner dataclass — the on-disk grouping documents *who sees what*; the runner is
agnostic.
