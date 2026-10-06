# General audit: correctness and simplification — 2026-10-06

**Status: five review passes complete; W01–W06 recommended, not implemented.**
Baseline: clean `main` at `c4c2ffc`, verified equal to `origin/main` after the authorized push.
The completed V01–V03 audit and implementation evidence remain in
`c4c2ffc:docs/project-audit-2026-10-06-follow-up.md`.

## Recommendation

Implement these six bounded changes. Four address incorrect or unusable eval behavior;
two remove unnecessary work. The most useful simplifications are removing misleading
Judge metrics, shrinking the unused eval catalog contract, sharing grading rules, and
replacing the dashboard's participant-loading loop with an existence query.

This is not evidence that the recent reliability work needs to be dismantled. Git blame
places the failed-repetition filtering, screening Judge adapter, and scalar-only array
editor in July. Recent changes improved their surrounding persistence and validation
without covering these older semantic gaps. Keep the existing ownership boundaries.

| ID | Priority | Recommendation | Evidence |
| --- | --- | --- | --- |
| W01 | P2 | Distinguish complete, valid eval outcomes from missing/failed attempts | Five attempts with four timeouts report stable with 100% agreement; repeated missing verdicts also report stable |
| W02 | P2 | Use the same expected-value parsing and grading rules for live and Judge consumers | Wrong pets and wrong scoring key pass Judge; valid any-of screening expectation fails Judge; two committed cases have different contested policy between consumers |
| W03 | P2 | Remove misleading pooled Judge kappa and failure-recall metrics | Correct outputs produce 100% agreement / 0% recall; wrong outputs produce 0% agreement / 100% recall |
| W04 | P2 / P3 focus issue | Make the fixture editor preserve and edit nested lists; keep text controls stable | Object arrays render as `[object Object]`; editing converts them into strings; crossing 60 characters loses focus |
| W05 | P3 | Reduce the eval catalog to the configuration actually consumed | Five fixture reads and 13 verbose descriptors; browser consumes only keys, repetitions, and editing availability |
| W06 | P3 | Check overdue-opening participation with `EXISTS` | Twenty overdue openings cause 21 queries and 20 answer-blob reads; a one-query probe returns the same IDs |

No production action or paid AI work is part of this recommendation. Preserve submission-time
age, automatic cache reuse, coverage-based Screen/Rank readiness, committee authority,
retained imported records, local-only fixture editing, admin-only operator surfaces, and
uncapped eval runs. The previously deferred export/source-guard policy stays deferred.

## Review method and coverage

1. **Inventory and history:** recent commits, existing audits, module sizes, exported-symbol
   references, repeated blocks, CSS consumers, and documentation. Inventory covered 198
   backend application Python files and 134 non-test frontend TypeScript files. This was
   navigation/triage, not a claim to have read every line of every file.
2. **Ownership and simplification:** applicant persistence and its save/email/withdrawal
   boundaries; committee refresh, ranking, notes, eligibility/settings, opening decisions;
   backend application presentation, eligibility pools, result selection, opening summaries,
   email adapters, stream lifetime, retention and recovery. Look for unnecessary work and
   duplicated decisions, not merely similar syntax or large files.
3. **Consumer parity:** trace the same fixture and output through live grading, Judge grading,
   stability, API summaries, restored history, and UI presentation. Exercise object/array/scalar
   forms as actual controls. This expanded beyond the earlier emphasis on response ordering.
4. **Controlled counterexamples:** real functions/hooks/components with synthetic values,
   mock providers, and an isolated in-memory database; measure calls and query projections.
5. **Consolidation:** inspect siblings and historical consumers, run existing affected suites,
   check proposed removals for consumers, reject low-value rewrites, and group changes by owner.

## W01 — An incomplete or invalid run must not become successful evidence

**Anchors:** `backend/app/evals/stability.py:120–150`,
`backend/app/evals/judge.py:190–222`, `backend/app/api/evals/_categorical.py:113`,
`frontend/src/components/evals/evalResultPresentation.ts:8–27`.

Both stability implementations filter failed pool results out before computing agreement.
They then divide by the successful subset, without representing missing attempts. The API
still reports the requested K. A synthetic five-call probe with one success and four
`TimeoutError`s returned one run, `[stable]`, and `agreement=1.0`. The real Judge stability
path produced the same result with a mock provider containing only one queued response.

There is a related validity gap: the consolidation runner explicitly identifies missing
pair output as verdict `?` with a failure. Five such outputs yield `{ '?': 5 }` and `[stable]`.
If the single-run case is contested, `contested or passed` also counts this missing verdict
as passing. The frontend contested branch softens it without checking output validity.
Contested means two valid answers are defensible; it does not establish that any answer arrived.

**Recommended implementation:** keep every attempted repetition and its error/validity outcome
in the existing report, retaining successful details and original attempt numbering. Compute
stability only when the required attempts have usable outputs. Expose an incomplete/error
result without certifying current coverage; do not automatically retry paid work. Share this
small collection/completeness rule between live and Judge stability. Ensure missing categorical
verdicts stay errors even on contested cases, in fresh responses, restored summaries, and dots.
A valid but consistently incorrect answer can still be stable: accuracy and repeatability
remain separate concepts.

**Acceptance:** all succeed; one/four/all fail; out-of-order completion; cancellation;
missing verdicts; contested valid disagreement; complete repeated valid failures; persisted
history and unrecorded receipts. Successful details must remain inspectable, while incomplete
output cannot count as completed stability coverage. An all-failed run must not reach an empty
majority calculation.

**Complexity/latency:** a local outcome distinction and shared collector, not a new job system.
No extra requests, model calls, or serialization of currently parallel work.

## W02 — Live and Judge consumers still grade different contracts

**Anchors:** `backend/app/evals/screening.py:106–125,230–253`,
`backend/app/evals/scoring.py:113–127,196–215`, `backend/app/evals/judge.py:86–110`.

Four concrete discrepancies belong to the same correction:

- **Pet facts:** a committed synthetic screening case expects two dogs and one cat. The same
  mocked output with no pets fails the live grader but returns `agrees=True` in Judge. The
  Judge adapter drops `expected.pets` when constructing its probe and does not pass produced
  pets to the shared checker.
- **Any-of flags:** the supported `fires: "fake_contact|minimal_essay"` representation is
  normalized by the live loader. Judge instead applies `list(...)`, producing characters.
  A correct `fake_contact` output passes live and fails Judge in the controlled probe.
- **Scoring identity:** live scoring requires the requested dimension key. Judge falls back
  to the first score when that key is missing. An in-band score for an unrelated key fails
  live and passes Judge in the controlled probe.
- **Contested policy:** the screening loader reads `metadata.expected.contested`; Judge reads
  `metadata.contested`. The current committed corpus has two screening cases contested only
  in the live consumer. They therefore enter Judge's decisive agreement denominator.

**Recommended implementation:** one screening expectation parser used by the live loader and
Judge adapter, and the same grading inputs (flags and pets) on both paths. Remove the
wrong-key scoring fallback. Put contested policy in the common metadata envelope and update
the two affected fixtures and their readers together; do not retain two permanent locations
or a compatibility branch. Keep family-specific graders: a score band, flag set, and pair
verdict are different rules and do not need a generic grading framework.

**Acceptance:** a table of supported expectation shapes, run through both real consumers with
identical mocked output: any-of string/list forms, required/forbidden flags, correct/wrong pet
counts, other pets, clean applicants, exact/missing/wrong scoring keys, and contested cases.
Assert the returned grade and aggregate inclusion, not merely parser output or direct dataclass
construction. Blind prompts must continue to exclude human labels.

**Historical-output requirement shared with W01/W03:** corrected bookkeeping must not silently
certify results produced under the defective harness. Use the existing eval fingerprint/validity
boundary to distinguish corrected grading, and retain older output as historical evidence.
Do not change production Screen/Rank prompt versions or invalidate applicant AI caches for
an eval-only correction. No automatic paid rerun is required.

**Complexity/latency:** remove divergent parsing and fallback behavior; reuse the actual grader.
No extra model calls. Prompt changes are not needed merely to repair deterministic grading.

## W03 — Remove aggregate metrics whose inputs do not represent their claims

**Anchors:** `backend/app/evals/agreement.py:62–118`,
`backend/app/evals/screening.py:250–253`, `frontend/src/components/evals/evalResultPresentation.ts:34–43`.

A synthetic probe passed two real screening Judge results into `score_agreement`:

| Produced output | Graded agreement | Reported kappa | Reported failure recall |
| --- | --- | --- | --- |
| Both required flags correctly produced | 100% | 0.0 | 0% |
| Both required flags omitted | 0% | 0.0 | 100% |

Kappa compares display strings: for example the human's `fires: fake_contact` with the
Judge's `fake_contact`; scoring compares a band string with a numeric score string. These
are not matching category representations even when grading establishes agreement. Mixing
families further combines different label vocabularies.

The screening adapter sets `human_is_problem` when a case has a guard and `judge_is_problem`
when the Judge fails it. Consequently, failing the expected behavior increases the metric
labelled failure recall. Existing metric tests construct the boolean fields directly; they
prove arithmetic for those fabricated fields, not the semantics supplied by the adapters.
A full saved Judge run retains this aggregate for its UI history marker.

**Recommendation:** remove pooled kappa and the current cross-family failure-recall/precision
contract, including unused fields, UI text, and tests that preserve those definitions. Retain
plain overall and per-family graded agreement with an explicit decisive-case denominator and
separate contested counts. Keep explanatory per-case output. Do not just rename the current
number or invert one boolean: clean cases, negative guards, score bands, and matching labels
do not share one established failure-detection taxonomy here.

This is a visible operator-report simplification worth approving as part of implementation.
If a future decision actually needs a categorical statistic, define its population and labels
for that particular family first. Do not build that hypothetical statistics layer now.

**Acceptance:** real adapters feeding aggregates; all-right/all-wrong/mixed cases; contested
exclusion; zero decisive cases; full vs accumulated partial history. Summary text must agree
with case-level grades. Remove all producer/type/consumer remnants of the abandoned metrics.

**Complexity/latency:** a net reduction in code and misleading surface area; no waiting cost.

## W04 — Finish the existing structured editor's supported value types

**Anchors:** `frontend/src/components/evals/StructuredFields.tsx:24–46,49–89,104–136`;
family templates in `EvalCaseEditor.tsx`.

`FieldValue` includes arrays, and the templates require arrays of objects and nested arrays.
The renderer excludes arrays from its object branch and casts them to scalar input. A real
component probe rendered a pair of dimension objects as `[object Object],[object Object]`.
Editing that input emitted `{ given: { pair: "Edited axis" } }`. The backend rejects that
shape, so this does not demonstrate corrupted fixture storage; it demonstrates an unusable
editor path for consolidation pairs, matching lists, and decomposition reports. Scalar lists
also lose their type when edited.

A second component probe typed from 60 to 61 characters. The editor replaced its `<input>`
with `<textarea>`, and keyboard focus moved to the document body.

**Recommendation:** explicitly render scalar, object, and array values using the existing
recursive editor. Array entries must be edited at their indices and remain arrays; set/remove
operations must understand those paths. Preserve nested lists and locked identity fields.
Keep a string's control type stable while typing (a textarea styled for short/long content is
one simple option). Remove the type assertion that hides unsupported arrays. Do not introduce
a form-generation library or five separate large family editors.

**Acceptance:** edit and save an existing case from every family through the actual editor;
array-of-object, nested array, string array, any-of nested string array, empty array, number,
boolean, and long string; preserve focus, shape, identity locks, newer typing, and save errors.
Keep the server schema as the validation authority.

**Complexity/latency:** a small amount of necessary array traversal replaces misleading scalar
handling. No new network work; stable controls improve responsiveness directly.

## W05 — Shrink the catalog contract and remove corpus reads with no consumer

**Anchors:** `backend/app/api/evals/catalog.py:45–141`,
`backend/app/schemas/evals.py:21–34`, `frontend/src/components/ai/AIWorkspaceView.tsx:114–115`,
`frontend/src/components/evals/RunnableEval.tsx:113`.

The browser reads catalog keys/repetition counts and `fixtureEditingEnabled`. It owns its own
labels/descriptions and computes confirmation totals from the visible cases times repetitions.
The server still reads and validates every golden file, builds 13 detailed descriptors, and
returns `label`, `description`, `spends`, and `estimatedCalls`. Repository searches found these
extra fields in definitions and fixtures/tests, but no current browser consumer. A direct
catalog probe counted **five file reads and approximately 3.3 KB of serialized data**.

**Recommendation:** retain the existing endpoint with a narrow mode/repetition/editability
contract. Remove unused descriptive/estimated fields from both schemas and catalog construction;
keep copy in its existing UI owner. Catalog availability should not depend on unrelated corpus
contents. No registry framework or process-wide cache is needed. Update stale API/eval docs that
still attribute total confirmation counts to the catalog.

**Acceptance:** zero fixture reads for catalog; existing mode repetition defaults preserved;
local/hosted editing policy retained; displayed totals change after adding a case; catalog
failure/retry still gates paid controls. Replace tests of unused fields with these contract checks.

**Complexity/latency:** deletes substantial descriptor boilerplate and five unnecessary reads
per catalog load, without adding a cache or moving model-run policy into the browser.

## W06 — Let SQL answer whether an overdue opening has participants

**Anchor:** `backend/app/services/openings/selection.py:102–113`; caller
`backend/app/api/dashboard.py:105–112`.

The function selects overdue undecided openings, then calls `active_opening_participants` for
each merely to test list truthiness. That hydrates full application answers and participation
entities on a routine admin dashboard read. An isolated database with twenty qualifying
openings produced **21 SELECTs, including twenty answer-blob projections**.

A proposed correlated `EXISTS` query returned the same ordered IDs in **one SELECT**, without
projecting applicant answers. This is measured query behavior, not a production timing claim.

**Recommendation:** use the same active/retained/submitted predicates inside `EXISTS` and keep
the current ordering. Leave the full participant loader on actual decision paths, where those
records are needed. No shared cache or new service layer is warranted.

**Acceptance:** no participants, withdrawn participation, withdrawn application, unsubmitted,
expired, future move-in, decided opening, multiple matching participants, and stable ordering.
Check that query count does not grow with opening count and no answer blobs are projected.
The everyday benefit is modest when there is only one overdue opening, but the implementation
is simpler and removes avoidable work from a repeatedly read surface.

## What I would keep / not tackle now

- Keep request scopes, queued writes, exact save acknowledgements, run leases, authority checks,
  deletion receipts, and recovery guards. They protect different boundaries. Similar-looking
  `try/finally` blocks do not justify a general mutation engine.
- Keep retained imported-answer readers. The form is retired; its stored records remain supported.
- Keep the applicant persistence orchestrator and its cohesive helper flows. Its size reflects
  several real access/recovery states. I found no evidence supporting a state-machine rewrite.
- Do not split the 1,139-line ORM model file solely to satisfy a line-count target. It is a
  coherent schema map; no concrete correctness or navigation benefit was established here.
- Keep production-pass-specific prompts and graders. Consolidate actual shared expectations,
  not superficially similar model requests with different meaning.
- Do not delete CSS based on text-search misses. Most candidates were generated class names
  (tier badges, column counts, fit bands, shortlist sizes); callers were present.
- Do not prune concurrency tests because they are numerous. Prune catalog/metric tests when
  their contracts are removed; replace them with consumer-path checks rather than adding
  another layer of mock-only tests. Symbol-reference triage found no clear orphan module
  deserving a deletion campaign.
- Do not add broad caches, dependencies, generalized registries, or new persistent identities.

## Why this pass found more, and how to reduce misses

Earlier passes emphasized lifetime, ordering, acknowledgement, and storage. This pass compared
**the same input and output through every consumer**, then exercised the real editor with every
shape its type admits. That exposed defects direct helper tests and scalar-only editor tests
could not see. The new probes passed assertions for defective behavior while the existing
related suites remained green.

For each future change, add a short consumer/shape matrix to the implementation review:

1. Trace each retained field to its actual consumers; remove work for fields with no consumer.
2. For shared rules, run the same synthetic case through all consumer entrypoints and compare
   the relevant grade/meaning. Do not only feed invented intermediate booleans into a helper.
3. For repeated work, account for every attempted item, including failures; inspect numerator,
   denominator, and the claim made by the summary. A failed item must not disappear from evidence.
4. For editors, exercise every supported value shape through the rendered controls and save
   boundary. Type assertions are not proof that a shape is supported.
5. Retain the adverse-state/both-completion-orders method from V01–V03. These methods complement
   each other; neither is replaced by another broad source reread.

This is a review discipline, not a proposal for a new testing framework. It can reduce misses
without accumulating more synchronization code. It cannot guarantee a single audit finds every bug.

## Verification, implementation order, and limits

- Existing affected backend suites: **115 passed** across two runs (92 + 23).
- Existing eval/workspace frontend suites: **50 passed across five files**.
- Two temporary real-component probes reproduced array coercion and focus loss. Removed after
  recording the results; no application or permanent test files changed.
- In-memory/function probes reproduced stability, grading, and metric problems and measured
  catalog reads and overdue-opening queries. Only mock providers and synthetic data were used.
- No full-suite rerun was needed for this documentation-only audit. The just-pushed baseline's
  previous implementation checks were 1,081 backend passes / one skip, 356 frontend passes,
  build and linters passing; those are prior-turn results, not new audit verification.
- No real model call, provider email call, production access, database reset, server start,
  applicant-data export, or browser reload occurred.

Suggested commits: W06 (small query simplification), W05 (catalog removal), W04 (editor),
W02 (shared grading policy), W01 (complete outcome handling), W03 (metric simplification).
W01–W03 need one joint final review of fingerprints, retained history, and summaries so that
fixing the grader does not leave its consumers using an obsolete success definition.
Run relevant suites/build/lint for each package, then the full suites and a final consumer-matrix
review. Keep the document open for any implementation finding inside those boundaries.
Application changes await authorization; only the audit document is changed by this pass.
