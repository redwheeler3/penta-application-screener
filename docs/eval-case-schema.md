# Eval case schema

Every eval case — for every AI pass — uses **one identical top-level envelope**. Only the
*contents* of the payload blocks and the *type* of `metadata.expected` vary by pass; the shape
you read, edit, and validate is the same everywhere. This is what lets one case serve two
consumers (a live eval and a judge audit — see "Two consumers") and lets the Judge tab read
every pass's cases without per-pass parsing.

Cases live in per-pass files under `backend/eval-data/`, named `<pass>_golden.json`:
`scoring_golden.json`, `consolidation_golden.json`, `decomposition_golden.json`,
`matching_golden.json`, `screening_golden.json`. Each file is
`{ "_comment": "...", "judge_background": "...", "cases": [ <case>, ... ] }`.

The per-pass `given`/`expected` shapes here were derived from what each pass's real
`build_prompt` + output schema actually sends and returns — see
`docs/pass-io-investigation.md`. (The retired `judge_cases.json` — a standalone judge case set —
was mined into these golden files; the judge now owns no files and reads them all.)

## The envelope

Every case, for every pass, is exactly three top-level keys — no per-case judge or produced
block:

```jsonc
{
  "key": "unique_case_key",          // top-level identity; upsert/dedup/filter key on this

  "metadata": {                      // HARNESS-ONLY — no model, live or judge, ever sees this
    "expected": <verdict|band>,      // REQUIRED. The human label. Type varies by pass (below).
    "note": "one-line what/why",     // optional: human orientation
    "pass": "consolidation",         // which production pass this case exercises
    "contested": false,              // optional: both labels defensible (see ai-evals.md)
    "label_rationale": "why expected is what it is",  // optional but strongly encouraged
    "provenance": { },               // optional: source run's models + prompt versions
    "source": "where this case came from",            // optional: traceability
    "ungraded": { }                  // optional: model self-labels we DON'T grade — see below
  },

  "given": { /* WHAT THE PRODUCTION PROMPT RECEIVES — see the per-pass shapes below */ }
}
```

The file also carries ONE top-level `judge_background` string (a sibling of `cases`, not part
of any case): a plain-language "what this pass does" brief, editable in the Judge tab. It is
the only thing the blind judge is told about the pass — see "Two consumers".

### One payload block: `given`

`given` is what the production prompt *receives*. Both consumers use it:

- The **live eval** feeds `given` through the real production prompt and grades the FRESH output
  against `metadata.expected` — deterministically (categorical exact-match; scoring band-check).
- The **blind judge** feeds the SAME `given` through an independent model driven by
  `judge_background` (never the production instructions, never the label), reproduces the pass's
  output, and the harness grades it against `metadata.expected` with the same grader.

There is no recorded-output (`produced`) block and no per-case judge question. An earlier design
recorded a model output to judge for "defensibility" and gated a per-case judge on a `judge`
block; both are gone. Every pass is now graded one way — production reproduces the output live,
the judge reproduces it independently — so a case only ever needs its input (`given`) and its
label (`metadata.expected`).

### Fidelity rule (load-bearing)

The blind judge is shown **`given` + the pass's `judge_background` only** — never `metadata`.
Revealing `metadata.expected` (or `label_rationale`, which often holds the reasoning/`r`-value)
hands the judge the answer and defeats the audit. Enforced by the loaders: `metadata` is
flattened into the harness dataclass but never serialized into a prompt.

## The shared `descriptor` sub-object (three passes)

Three passes reason over the same atomic unit — a **dimension descriptor** — so their `given`
blocks share it (`docs/pass-io-investigation.md`, Finding 1):

```jsonc
"descriptor": { "key": "...", "name": "...", "definition": "...", "high_end": "?", "low_end": "?" }
```

`high_end`/`low_end` are optional (matching judges identity by definition alone and omits them;
consolidation and decomposition keep them). Using one descriptor shape across the three
comparison passes is the unification we DO exercise — one shared eval runner backs them.
(Serialization of this shape in *production* is refactor A, docketed separately; the eval builds
on the shared shape now regardless.)

## Per-pass `given` shapes

| Pass | `given` |
|---|---|
| **consolidation** | `{ pair: [descriptor, descriptor] }` — the two definitions the confirm call compares (NOT `_a`/`_b` flattening) |
| **matching** | `{ prior: [descriptor, …], new: [descriptor, …] }` — the two lists (or a focused single-pair case) |
| **decomposition** | `{ reports: [[descriptor, …], …] }` — the K discovery reports to settle |
| **scoring** | `{ applicant: { facts, essays }, dimension: descriptor }` — outlier: applicant evidence, not a comparison |
| **screening** | `{ fields: { … }, essays: { … } }` — outlier: the applicant fields + essays the pass reviews |

`given` must be an **exact slice of what production sends**. For applicant-facing passes
(scoring, screening) the evidence is committed only from the synthetic pool
(`synthetic_guard.py`), never a real applicant.

## `metadata.expected` shapes

Categorical passes carry a **string verdict**; scoring carries a **band** (continuous output,
so we pin a range not a point); screening carries **fires/absent category lists**:

| Pass | `expected` |
|---|---|
| **consolidation** | `"merge"` \| `"keep"` |
| **decomposition** | `"merge"` \| `"keep"` |
| **matching** | `"matches"` \| `"mismatches"` |
| **screening** | `{ fires: [category, …], absent: [category, …] }` — categories that MUST fire / must NOT (over-reach guards); a clean applicant has empty `fires` and any flag fails it. A `fires` entry may itself be a **list** = "at least ONE of these must fire" (for a concern with more than one defensible bucket — e.g. a fictional pet reads as `pet_policy` OR `other`; the test is that it's flagged, not which bucket). A category in NEITHER list is ungraded (fire or not, both pass) — this is how a genuinely *contested* flag axis is expressed on a per-category case (the top-level `contested` flag is for whole-verdict passes; screening contests one axis by omitting it from both lists) |
| **scoring** | band object: any of `score_min`, `score_max`, `confidence` — the produced score must land in `[score_min, score_max]` (a neutral case pins a tight band straddling 0) |

## Ungraded model-assigned fields — `metadata.ungraded`

A field the *model itself produces* but the case does **not** grade needs care: if the judge
sees it, it can leak the answer. The rule is not blanket — it turns on whether the field is a
throwaway self-label or load-bearing signal:

A field the model produces but the case doesn't grade is hidden in `metadata.ungraded` so the
blind judge never sees it and can't be biased by it. *Example:* screening's `flag_severity`
(`info`/`notable`) — if a case's evidence were shown with a "notable" tag it would nudge the
judgment. `metadata` (including `ungraded`) is harness-only and never serialized into any
prompt, so the rule is simply: *a model self-label the case doesn't grade goes in `ungraded`.*
(A field that IS graded lives in `metadata.expected` — e.g. scoring's `confidence` band.)

## Two consumers (why the schema is unified)

Both consumers read the SAME `given` and grade against the SAME `metadata.expected` with the
SAME per-pass grader; they differ only in WHO produces the output:

1. **Live eval** (routine regression net): feeds `given` through the **real production prompt +
   model** and grades the fresh output. Categorical → exact-match; scoring → band-check. This
   catches a prompt/model regression.
2. **Blind judge** (periodic label audit / calibration — the Judge tab): feeds the SAME `given`
   through an **independent model** driven by the pass's editable `judge_background` (what the
   pass does) — never the production instructions, never the label — reproduces the pass's
   output, and grades it the same way. A case where the independent judge consistently disagrees
   with `metadata.expected` signals the **label** may be wrong; aggregate judge-vs-label
   agreement (κ, failure-recall) calibrates whether the judge itself is trustworthy.

Blindness is the load-bearing rule: the judge is shown `given` + `judge_background` only, never
`metadata` (a judge shown the answer rubber-stamps it — see the fidelity rule). Whether to run
the audit is a whole-tab action, not a per-case switch: the Judge tab audits every pass's cases.

## Validation

`app/evals/case_store.py` gates writes: only the allowlisted `<pass>_golden.json` files are
writable, and each write must carry `key` (non-empty string), `metadata`, and `given`. A bad
payload is refused whole, never partially written. The file's non-`cases` top-level keys
(`_comment`, `judge_background`) are preserved across a write. `judge_background` itself is
edited through `save_background` (Judge tab), which writes the same file. Loaders flatten the
envelope into each pass's flat runner dataclass — the on-disk grouping documents *who sees
what*; the runner is agnostic.
