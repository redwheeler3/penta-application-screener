# Eval case schema

Every eval case — for every AI pass — uses **one identical top-level envelope**. Only the
*contents* of the payload blocks and the *type* of `metadata.expected` vary by pass; the shape
you read, edit, and validate is the same everywhere. This is what lets one case serve two
consumers (a live eval and a judge audit — see "Two consumers") and lets the Judge tab read
every pass's cases without per-pass parsing.

Cases live in per-pass files under `backend/eval-data/`, named `<pass>_golden.json`:
`scoring_golden.json`, `consolidation_golden.json`, `decomposition_golden.json`,
`matching_golden.json`, `screening_golden.json`. Each file is
`{ "_comment": "...", "cases": [ <case>, ... ] }`.

The per-pass `given`/`produced`/`expected` shapes here were derived from what each pass's real
`build_prompt` + output schema actually sends and returns — see
`docs/pass-io-investigation.md`, not from the old `judge_cases.json` recordings.

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
    "source": "where this case came from",            // optional: traceability
    "ungraded": { }                  // optional: model self-labels we DON'T grade — see below
  },

  "given": { /* WHAT THE PRODUCTION PROMPT RECEIVES — the live eval feeds this to the real prompt */ },

  "produced": { /* A recorded model OUTPUT to judge — OPTIONAL, defensibility cases only */ },

  "judge": {                         // OPTIONAL. PRESENCE IS THE SWITCH: block present ⇒ the
    "question": "..."                //   judge runs on this case; absent ⇒ it does not.
  }
}
```

**The `judge` block is the on/off switch for the judge, per case.** Present → the judge runs
(scoring cases, which need a defensibility judge because the output is continuous). Absent →
no judge runs (the categorical passes — consolidation/matching/decomposition/screening — grade
by exact match alone, so they carry no `judge` block). Leaving it out is not an omission to
fill in later; it is the explicit statement "this case does not need a judge."

### `given` vs `produced` — the two payload blocks

A pass can be evaluated two ways, and they need different payloads:

- **`given`** is what the production prompt *receives*. The **live eval** feeds `given` through
  the real prompt and grades the fresh output against `metadata.expected`. Every case has a
  `given`.
- **`produced`** is a recorded model *output* under judgment — for a **defensibility** case
  ("is THIS flag / THIS score warranted?"). Optional: present only when the case grades a
  recorded output rather than re-running the prompt. Screening/scoring defensibility cases (the
  ones migrated from `judge_cases.json`) carry a `produced`; a pure live-regression case does
  not.

This distinction is why screening's old "input" was wrong: production screening *receives* an
applicant (`given`) and *produces* a flag (`produced`) — the flag is output, not input.

### Fidelity rule (load-bearing)

The judge is shown **`given` + `produced` + `judge.question` only** — never `metadata`.
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

Categorical passes carry a **string verdict**; scoring carries an **assertion object** (no
single right number, so we pin properties):

| Pass | `expected` |
|---|---|
| **consolidation** | `"merge"` \| `"keep"` |
| **decomposition** | `"merge"` \| `"keep"` |
| **matching** | `"matches"` \| `"mismatches"` |
| **screening** | `"flag_supported"` \| `"flag_unsupported"` |
| **scoring** | assertion object: any of `score_equals`, `score_min`, `score_max`, `confidence` |

## Ungraded model-assigned fields — `metadata.ungraded`

A field the *model itself produces* but the case does **not** grade needs care: if the judge
sees it, it can leak the answer. The rule is not blanket — it turns on whether the field is a
throwaway self-label or load-bearing signal:

- **Hide (→ `metadata.ungraded`, judge never sees it):** a self-assessment the case doesn't
  grade that could bias the verdict. *Example:* screening's `flag_severity` (`info`/`notable`).
  The case asks "is this flag warranted by its evidence?"; the model's own "notable" would nudge
  the judge toward "supported." Not under test, and leaky → hide.
- **Keep (→ inside `produced`, judge sees it):** a produced field that is itself part of what
  "defensible" means. *Example:* scoring's `confidence`. A `score 0.0, confidence: low` on a
  silent applicant is defensible; `confidence: high` would be suspect — so confidence is
  load-bearing for the judgment and belongs in `produced`. (When we grade confidence directly,
  it's in `expected`, not a free field at all.)

The test: *hide model self-labels that would leak the answer; keep produced fields that are
load-bearing for the judgment.*

## Two consumers (why the schema is unified)

1. **Live eval** (routine regression net): feeds `given` through the **real production prompt**,
   grades the fresh output.
   - *Categorical passes:* `production_verdict == metadata.expected` (deterministic exact-match).
     No judge — redundant (see `docs/ai-evals.md` "Grader architecture").
   - *Scoring:* deterministic assertions from `metadata.expected` **plus** a defensibility judge
     (scoring is continuous — the one pass where a judge earns its cost).
2. **Judge** (only when the case carries a `judge` block): the judge answers `judge.question`
   from `given` (+ `produced` if present); its verdict is compared to `metadata.expected`. This
   serves the continuous pass (scoring's defensibility judge, part of that pass's live grade)
   and — via the reframed Judge tab — periodic **label auditing**: a judge that disagrees on a
   subjective case signals the *label* may be wrong; aggregate judge-vs-label agreement (κ)
   calibrates whether the judge itself is trustworthy.

So the **`judge` block is the switch**: present ⇒ judge runs on this case; absent ⇒ it does
not. Categorical passes carry no `judge` block (exact-match only); scoring cases carry one.
Whether to run the periodic label-audit over a whole pass is a pass-level choice, not encoded
per case — a categorical pass without `judge` blocks simply isn't judged.

## Validation

`app/evals/case_store.py` gates writes: only the allowlisted `<pass>_golden.json` files are
writable, and each write must carry `key` (non-empty string), `metadata` (with `expected`
present), and `given`; `produced` and `judge` are optional. A bad payload is refused whole,
never partially written. Loaders flatten the envelope into each pass's flat runner dataclass —
the on-disk grouping documents *who sees what*; the runner is agnostic.
