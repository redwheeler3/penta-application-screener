# Pass I/O investigation — what each AI pass actually sends and receives

Read-only audit (2026-07-18) of the five production AI passes, taken from their real
`build_prompt` + output schema in `backend/app/ai/`. Goal: find where genuine unification
exists so the per-pass live-eval build collapses toward one contract instead of five copies —
and where it honestly does not. No code changed; this is the basis for the schema + build
decision.

## Ground truth: what each pass sends (input) and returns (output)

| Pass | Prompt INPUT (what `build_prompt` serializes) | Output schema | Verdict shape |
|---|---|---|---|
| **scoring** (`dimension_scoring.py`) | `<dimensions>`: list of `{key, name, definition, high_end, low_end}` + `<applicant>`: `{applicant_id, facts, essays}` | `DimensionScoringReport` = list of `DimensionScore {dimension_key, score −1..+1, rationale, evidence, confidence}` | continuous score + confidence |
| **consolidation** (`dimension_consolidate.py`) | `<candidate_pairs>`: list of `{key_a, definition_a, key_b, definition_b}` | `ConsolidationReport` = list of `ConsolidationVerdict {key_a, key_b, same_concept: bool, reason}` | categorical (merge/keep) |
| **matching** (`dimension_matching.py`) | `<prior_dimensions>` + `<new_dimensions>`: two lists of `{key, name, definition}` | `DimensionMatchReport` = list of `DimensionMatch {new_key, old_key}` | categorical (matches/omitted) |
| **decomposition** (`dimension_decompose.py`) | `<discovery_reports>`: K reports each `{report_index, dimensions:[{key, name, definition, high_end, low_end, from_committee_request}]}` (+ optional `<kept>`) | `DecompositionReport` = list of `DecomposedDimension {key, name, definition, high_end, low_end, source_keys[], from_committee_request, decision}` | grouping (source_keys folds) |
| **screening** (`screening.py`) | `<fields>`: 7 named applicant fields + `<essays>`: 4 essays in full | `ScreeningReport` = list of `ScreeningFlag {category, summary, evidence}` | categorical per flag (warranted?) |

## The atomic unit: a **dimension descriptor**

Three of the five passes consume the SAME atomic unit — a dimension descriptor — and differ
only in how many and in what wrapper:

- **PoolDimension** (canonical): `{key, name, definition, high_end, low_end, why_it_differentiates, from_committee_request}`.
- scoring sends `{key, name, definition, high_end, low_end}` (drops why/committee — not needed to score).
- matching sends `{key, name, definition}` (drops poles — identity is by definition).
- decomposition sends `{key, name, definition, high_end, low_end, from_committee_request}` (keeps poles to carry forward).
- consolidation sends `{key_a, definition_a, key_b, definition_b}` — a *pair*, and notably **key+definition only, renamed with `_a`/`_b` suffixes** (its own bespoke shape, not even reusing the descriptor field names).

**Finding 1 — real unification exists among the three "reason over dimension descriptors" passes** (consolidation, matching, decomposition). All three: take dimension descriptors, decide *sameness/grouping* by comparing definitions, return a categorical verdict. They hand-roll three different serializations (`<candidate_pairs>` with `_a`/`_b` fields; `<prior>`/`<new>` lists; `<discovery_reports>` nested) and three different verdict schemas for what is conceptually one operation.

**Finding 2 — scoring and screening are genuine outliers.** They consume APPLICANT evidence
(facts + essays), not dimension descriptors, and scoring returns a continuous value. Forcing
them into a shared dimension-comparison contract would be fake unification. Leave them apart.

## Two unification opportunities (production), ranked

### A. Shared dimension-descriptor serialization (low risk, high payoff)

A single `descriptor_json(dims, *, fields=[...])` helper that every dimension-consuming pass
calls, instead of three near-identical `_dimensions_block`/`_reports_block`/`_pairs_block`
functions. Each pass selects which descriptor fields it needs. This is a pure refactor of
*serialization* — the prompt text and verdict schemas stay per-pass — so it's low-risk and
independently testable. Notable cleanup: consolidation's `_a`/`_b` field renaming is the
odd one out; a shared descriptor would express a pair as two descriptors, not a flattened
`definition_a`/`definition_b`.

### B. Shared "sameness verdict" schema (medium risk)

Consolidation (`same_concept: bool`) and matching (`new_key→old_key`) and decomposition
(`source_keys` folds) all encode "these are/aren't the same concept." A shared
`SamenessVerdict {a, b, same: bool, reason}` could back consolidation and matching directly;
decomposition's N-way grouping is a superset (it groups, doesn't just pair) so it would NOT
collapse cleanly. Medium risk because it touches output schemas that the ranking pipeline and
audit surfaces read. **Recommendation: do NOT force this now** — the schemas earn their
differences (matching is new→old directional; consolidation is unordered; decompose is N-way).

## What this means for the eval schema

Regardless of whether production is refactored, the eval `given` block for the three
dimension-comparison passes SHOULD use the shared descriptor shape — because the eval is
already a fresh consumer we're building now, so it costs nothing to build it unified:

- **consolidation** `given`: `{ pair: [descriptorA, descriptorB] }` (two descriptors, not `_a`/`_b`).
- **matching** `given`: `{ prior: [descriptor...], new: [descriptor...] }` (or a single pair for a focused case).
- **decomposition** `given`: `{ reports: [[descriptor...], ...] }`.
- **scoring** `given`: `{ applicant: {...}, dimension: descriptor }` — outlier, its own shape.
- **screening** `given`: `{ fields: {...}, essays: {...} }` — outlier, its own shape.

Where `descriptor` = `{key, name, definition, high_end?, low_end?}`. That gives one shared
sub-object across the three comparison passes' `given` blocks and one shared eval runner for
them, with scoring/screening as two deliberate specializations. This is the "exercise
unification where it genuinely exists, don't force total unification" outcome.

## Recommendation

1. **Eval schema now:** adopt the shared `descriptor` sub-object in `given` for the three
   comparison passes (free — we're building it fresh). Finalize `eval-case-schema.md` on this.
2. **Production refactor A (shared descriptor serialization):** worth doing, low risk — but as
   its OWN slice, not smuggled into the eval build. Docket it.
3. **Production refactor B (shared verdict schema):** do NOT do — the schemas earn their
   differences. Recorded here so it's a considered "no", not an omission.

### Why not B — the reasoning (not primarily risk; it's wrong long-term)

Grounded in the project rules (`.clinerules`), B fails on its merits:

- **Not real duplication ("abstractions only for real duplication or a meaningful boundary").**
  The three verdicts encode three genuinely different operations, not one rule written thrice:
  matching is **directional** (`new_key → old_key`, asymmetric); consolidation is an
  **unordered** pair (a↔b, older key wins); decomposition is **N-way grouping**
  (`source_keys`), not a pair at all. A shared `SamenessVerdict {a, b, same}` fits
  consolidation, only *sort of* fits matching (by flattening away direction), and does **not**
  fit decomposition — you'd unify 2½ of 3 and immediately need per-pass escape hatches. That's
  abstracting a *coincidental shape*, not a shared rule.
- **It would erase load-bearing information ("prefer fewer identities" cuts the other way here).**
  Matching's `new→old` direction drives score carry-forward (`adopt_matched_keys`);
  consolidation's older-key-wins preserves determinism. Collapsing to a symmetric `{a, b}`
  throws away directionality the pipeline depends on. The distinctness is information, not
  redundancy.
- **False boundary / fragility ("optimize for future maintainers", "look around corners").**
  A unified `SamenessVerdict` reads as "these three passes are interchangeable" — then a
  maintainer discovers matching is secretly directional. Three honestly-different schemas are
  *more* legible than one that lies. And the shared schema would couple three independently
  evolving passes through the ranking pipeline + audit surfaces (`consolidate_audit`,
  `match_audit`), so accommodating one ripples to all three.
- **Over-engineering ("right-size; over-engineering violates the rules as much as sloppiness").**
  Enterprise-grade unification on a stable, small solo-MVP surface. The bar is "clean, boring,
  obvious" — three schemas named for what they do *is* that.

The risk (ripple through audit surfaces) is real but **secondary** — B is a "no" even if it
were risk-free.

**The transferable line: unify serialization (mechanical sameness → refactor A), not verdict
schemas (semantic difference → B).** Same investigation, opposite verdicts, because one is
coincidental shape and the other is true redundancy. A's three `_block` functions turn
descriptors into JSON identically — genuine duplication, exactly what the rules say to
abstract.
