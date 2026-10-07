# General audit: correctness and simplification — 2026-10-06

**Status: W01–W07 implemented and verified, including W04's Chrome browser review.**
Baseline: clean `main` at `c4c2ffc`, verified equal to `origin/main` after the authorized push.
The completed V01–V03 audit and implementation evidence remain in
`c4c2ffc:docs/project-audit-2026-10-06-follow-up.md`.

## Recommendation

The seven findings below describe the audited baseline; implementation outcomes are recorded
at the end. Four address incorrect or unusable eval behavior;
three remove unnecessary work. The most useful simplifications are removing misleading
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
| W07 | P3 | Project email administration reads without hydrating applicant records | Twenty delivery issues cause 21 queries and twenty answer-blob reads; a narrow projection preserves recipients in one query |

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
contract, including unused fields, UI text, and tests that preserve those definitions. Derive
plain graded agreement with an explicit decisive-case denominator and separate contested counts
from the case results already sent to the browser. Keep explanatory per-case output and existing
family grouping. Do not add a new per-family reporting surface. Do not just rename the current
number or invert one boolean: clean cases, negative guards, score bands, and matching labels
do not share one established failure-detection taxonomy here.

This is a visible operator-report simplification worth approving as part of implementation.
If a future decision actually needs a categorical statistic, define its population and labels
for that particular family first. Do not build that hypothetical statistics layer now.

**Coverage-driven refinement:** the current frontend summary also counts a contested
disagreement as agreement: one decisive agreement plus one contested disagreement renders
`2/2 agree`. A real `runSummary` probe reproduced this. Correct the numerator/denominator
together. Consumer search found no browser/script use of the backend's separate per-category
counts or the two problem-classification booleans outside this calibration pipeline. Remove
the abandoned aggregate producer and its scaffolding instead of preserving unused fields.
This makes W03 a smaller result contract, not a replacement statistics subsystem.

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

**Coverage-driven refinement:** additional real-component probes reproduce the same coercion
for string lists, nested any-of lists, and empty lists. Another probe shows that although
`metadata.pass` cannot be removed directly, its entire `metadata` parent can be removed.
Honor locked descendants when offering ancestor removal. This is a UI contract defect;
the probe does not establish a valid unauthorized server write.

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

## W07 — Use narrow read models for email administration

**Anchors:** `backend/app/services/email/outbox.py:email_delivery_issues`,
`email_queue_status`, `_delivery_recipient`; lazy relationships on `EmailDelivery` in
`backend/app/db/models.py`; dashboard/email-delivery API consumers.

The issue list loads full delivery entities and resolves each address through lazy
application/draft/user relationships. A synthetic twenty-recipient probe recorded **21
SELECTs and twenty application answer-blob projections**. The response needs delivery metadata
and an email address, not the applicant's answers or a mutable application entity.

A narrow outer-join projection returned the same ordered IDs and recipients in **one query**
without answer blobs. A second probe covered six recipient variants: application, draft,
committee user, explicit targetless address, explicit address overriding an application,
and the unavailable-recipient fallback. All matched the existing presentation.

The sibling `email_queue_status` reader fetches every queued delivery, including retry-intent
JSON, to calculate count, quota-blocked count, and min/max timestamps. This is two queries
already, but it unnecessarily hydrates all queued rows. Calculate those summaries in SQL,
retaining the existing unexpected-failure predicate and its independent count if that keeps
the query clearer. These are internal materialization costs, not a demonstrated data leak.

**Recommendation:** keep read projections in the current outbox owner. Preserve recipient
precedence, filters, date fallback, limits and ordering. Leave full entities on the actual
retry/send path, which needs them. No cache, new service, or change to delivery semantics.

**Acceptance:** six recipient variants; queued versus expected/unexpected failures; limits;
empty queue; quota flags; timestamp bounds and fallback; query count independent of distinct
recipients; no answer/retry-intent projection for the summary views. Preserve existing
attempt/cancellation/lifecycle tests. The first mixed-recipient probe had an incomplete draft
fixture (`created_at` omitted); after fixing that probe setup all six cases matched.

**Complexity/latency:** remove per-recipient lazy reads and Python row aggregation. No extra
request, synchronization, model work, or production operation. This follows the same review
question as W06 but belongs to the separate email read owner.

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

## Initial audit verification and implementation order

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

Suggested commits: W06/W07 (separate read-owner simplifications), W05 (catalog removal), W04 (editor),
W02 (shared grading policy), W01 (complete outcome handling), W03 (metric simplification).
W01–W03 need one joint final review of fingerprints, retained history, and summaries so that
fixing the grader does not leave its consumers using an obsolete success definition.
Run relevant suites/build/lint for each package, then the full suites and a final consumer-matrix
review. Keep the document open for any implementation finding inside those boundaries.
The coverage extension preceded implementation authorization; its evidence and stopping
decision are retained below. Implementation followed the user's subsequent instruction.

## Coverage-driven extension

Starting revision: `0a98582`. The agreed audit procedure is now in `.clinerules`.
This extension began with the matrix below marked pending, then recorded evidence and
a final challenge. W01–W06 remain open; repeating their reproductions is not new coverage.
It added W07 and refined W03/W04 within this same audit, without an intervening handoff.

| Subsystem | Correctness / consumer meaning | Failure / concurrency | Shapes / lifecycle | Redundancy / readability / cost |
| --- | --- | --- | --- | --- |
| Applicant answers and browser persistence | S/T: submitted vs working projection, age/cache facts | S/T: exact acknowledgements and newer browser drafts | S/T: native/retained answers, opening selection, save vs submit | S: keep distinct persistence owners; no proposed generic state machine |
| Identity and administrative authority | S/T: captured identity vs current cookie, admin-only writes | S/T: sign-in replacement and demotion while waiting | S/T: applicant/committee sessions, revoked links/copies | S: admission and commit-time checks serve different purposes |
| Committee actions and details | S/T: private/shared notes and narrow field receipts | S/T: uncertain saves, deletion replay, pending detail reads | S/T: author restrictions, blocked drafts, retained review | S: queues stay by existing owner/field; no shared mutation engine |
| Opening publication and decisions | S/T: phase, participation, publication facts, finality | S/T: stale edits, selection/withdrawal, uncertain decisions | S/T: withdrawn/expired/unsubmitted, direct vs ordinary | S/P: W06; retain full participant loader for decisions |
| Screen/Rank and cached output | S/T: coverage/selection/cache identity, unranked behavior | S/T: leases, cancellation, partial model failures, stale boards | S/T: incomplete score vectors, human overrides, frozen age | S: keep shared cache/read owners and separate member/shared pools |
| Eval runners, grading and histories | S/P: W01–W03; contested-summary probe expands W03 | S/T: receipt/history ordering and failed refreshes; W01 remains open | S: common envelope and family-specific grading; W02 remains open | S: W05; remove W03 aggregate rather than replace it |
| Fixture and settings editors | S/P: W04 strings/lists/locked ancestors | S/T: save/reset ordering and newer typing | P: strings, nested/empty lists, ancestor removal; T: settings/date controls | S: array support in existing editor; D: browser visual/gesture checks |
| Email delivery and maintenance | S/T: recipient intent, notice eligibility and summary meaning | S/T: attempt ownership, cancellation, daily lease replacement | S/T/P: targetless/applicant/draft/member recipients; expired notices | S/P: W07; preserve richer entities on actual send paths |
| Retention, recovery and migrations | S/T: entitlement and deletion ledger, schema preparation | S/T: renewed retention, replaced work, failed restore preparation | S/T: producer/consumer deletion orders, old/new IDs, WAL snapshots | S: shared erasure justified; D: actual production restore and POSIX-only check |

Evidence labels: **S** = source/caller review, **T** = executed existing behavior test,
**P** = controlled new probe, **D** = explicit deferred verification. These labels describe
the evidence, not a guarantee that a subsystem has no bugs.

### Evidence behind the matrix

All test files named here ran in the full suites during this extension; their relevant
scenarios were inspected rather than treating the suite count as proof of the claims.

- **Applicant:** `applicantSaveFlow.ts`, `draftStorage.ts`, backend `applications/intake.py`,
  `answers.py`, and `openings/participation.py` keep private drafts separate from published
  answers and validate participation. `test_intake.py`, `test_application_answers.py`,
  `applicant/test_save_acknowledgement.py`, `test_applicant_copy_concurrency.py`,
  `applicantSaveFlow.test.ts`, and remembered-draft suites exercise those boundaries.
  `test_ai_analysis.py:test_cache_identity_uses_only_frozen_submission_facts_consumed_by_the_pass`
  verifies the deliberate age/cache policy; no calendar-driven invalidation is proposed.
- **Identity:** `api/dependencies.py`, `auth/authority.py`, `api/identity.tsx`, and
  `useRequestScope.ts`; `test_request_identity.py` drives real cookie-switch/write/read/logout
  paths. `test_identity_concurrency.py` and `test_admin_write_authority.py` cover preloaded
  identities and revoked authority, while frontend identity/session suites cover client scope.
- **Committee:** `api/applications/routes.py` preserves minimal creation/deletion receipts;
  `useCandidateActions.ts`, `usePrivateNotes.ts`, and `useNavigation.ts` separate write receipts
  from navigation. Their suites plus application API/lifecycle tests exercise replay, newer
  typing, blocked edits, and an overlapping detail response. No evidence supports merging them.
- **Openings:** `openings/catalog.py`, `participation.py`, `selection.py` and the three opening
  editors; `test_opening_edit_concurrency.py`, `test_lifecycle_concurrency.py`, ordinary/direct
  opening suites, and editor/decision tests cover stale facts, finalization and uncertainty.
  W06 retains the predicates of the existing participant reader; its query probe is documented
  above. The optimization must not move decision locks onto ordinary reads.
- **Screen/Rank:** `ai/analysis.py`, `dimension_scoring.py`, `dimension_discovery.py`,
  `services/cached_results.py`, `eligibility/status.py`, `domain/ranking.py`, and ranking view
  consumers were traced. Relevant tests include score-current selection, cache reuse,
  committee union, ranking scores/provenance, run leases/HTTP disconnects and frontend workflow
  and ranking hooks. The production discovery path deliberately permits surviving workers
  while recording failures; it is not a K-repetition stability claim and should not inherit
  W01's completeness rule indiscriminately.
- **Evals/editors:** `evalResultState.ts`, `evalResultPresentation.ts`, `EvalResults.tsx`,
  `EvalCaseList.tsx`, `StructuredFields.tsx`, `fixture_files.py`, `case_store.py`, and the
  live/Judge/summary consumers. Five new component/presentation probes checked the additional
  W03/W04 cases; all reproduced the defects. Existing runner/editor/history tests remain green.
  `useEligibilityRules.ts` and `NumberInput.tsx` were reviewed as sibling editors; their state
  ownership does not require the recursive fixture editor's array machinery.
- **Email:** `email/delivery.py`, `outbox.py`, `openings/notifications.py`, and `maintenance.py`.
  `test_email_outbox.py` covers overlapping workers, cancelled intents, and late attempts;
  `test_notice_eligibility.py` covers lifecycle changes after audience capture;
  `test_maintenance.py` covers obsolete attempts finishing after replacement. New W07 query
  probes use the real read functions. Rich write models stay on the retry path; only display
  projections change.
- **Retention/recovery:** `applications/retention.py`, `purge.py`, `result_retention.py`, and
  `services/backup.py`; `test_retention_purge.py`, `test_result_retention.py`, `test_backup.py`,
  and `test_migrations.py` cover extended lifetimes, both owner-deletion orders, failed isolated
  preparation, identity high-water marks, and historical migration independence. No production
  recovery or retention-policy change is inferred from those tests.

### Final challenge and stopping decision

The final review worked backward from user-visible claims and narrow response fields, instead
of following recent commits again. It asked whether every claim has appropriate evidence and
whether each proposed fix can remove code rather than add another representation.

- Followed the new email issue-list finding into recipient variants and queue summary reads.
  Both are captured in W07; no separate unexamined email-read finding is left for another pass.
- Followed W03 into UI summary counts and actual aggregate consumers. This found the contested
  numerator error and eliminated the need for a replacement aggregate layer from the plan.
- Followed W04 into nested/string/empty arrays and ancestor removal. These are acceptance cases
  in the same editor fix, not new independent feature proposals.
- Challenged W01 against the production fan-out policy and ordinary failed-but-complete evals.
  Preserve that distinction; do not make all partial production progress unusable.
- Rechecked W02's historical-output implications and W05's call-estimate consumer. Fix grading
  through eval validity boundaries without changing production cache versions; keep confirmation
  totals derived from the visible case set and catalog repetitions.

The planned rows now have source/test/probe evidence or explicit verification limits. After
these sibling expansions, the closing challenge identified no further unexamined material issue.
Stop discovery here and use W01–W07 as one implementation plan. This conclusion is narrower than
claiming every project defect has been found.

**Fresh checks:** full backend **1,081 passed, 1 skipped**; full frontend **356 passed in 49
files**; five temporary frontend probes reproduced their expected defects and were removed.
Email probes used isolated in-memory databases. The only remaining edits are this document and
`.clinerules`; no application, fixture, migration, or permanent test was changed.

**Explicit limits:** no real-provider judgment/billing validation, actual production restore,
browser layout/drag/mobile-accessibility verification, or production latency measurement.
The existing POSIX-only test remains skipped on Windows. These checks require different
environments or actions and do not block the documented deterministic recommendations.
Before implementing a materially changed editor workflow, include browser interaction review;
before changing prompts, apply the project's real-output verification rule. No such application
or prompt change was made here.

## Implementation outcomes

Implemented from `c055007` in seven cohesive commits:

| Finding | Commit | Outcome |
| --- | --- | --- |
| W06 | `894e3b3` | Overdue-opening discovery uses an existence query with the same active/retained predicates; no participant answer hydration. |
| W07 | `bb3abfe` | Email issues project recipient metadata directly; queue summaries aggregate in SQL. Full entities stay on the send path. |
| W05 | `41de4bc` | Catalog contains only mode keys, repetitions, and editing policy; zero corpus reads. Superseded read-count test removed. |
| W04 | `80515fd` | Recursive list editing preserves types; strings retain focus; locked identity descendants protect their parents from removal. |
| W03 | `017a852` | Removed the calibration aggregate, its fields/adapters/tests, and obsolete documentation. UI derives decisive agreement and separate contested/unrun counts from case results. |
| W02 | `0c30e93` | Shared screening expectation parsing, pet grading parity, exact scoring identity, and one contested-policy location. Added eval-only grading revision. |
| W01 | `c3a2ce2` | Live/Judge stability share one ordered attempt report; errors remain visible and incomplete statistics are null. Invalid contested results do not count as successes. |

### Final consumer review

- **Meaning of current versus successful:** an errored/incomplete eval may still describe
  the current inputs. It remains inspectable as an error/incomplete result and never counts
  as stable or successful coverage. A valid but consistently wrong answer may still be stable.
- **Retention and history:** each attempt retains its explanation, including errors, in
  submission order. Recorded partial failures round-trip through the API and history. An
  unrecorded incomplete result retains its paid output through failed history refreshes.
- **Contested cases:** valid disagreement stays a review signal. Missing/invalid output
  remains an error. Judge summaries separate errors from decisive cases; stability summaries
  separate contested splits from stable measurements.
- **Within-scope follow-up:** decomposition could derive a merge from only part of its input
  key set. W01 now requires every source key exactly once; partial/duplicate source assignments
  are errors in both a single run and stability. No additional production algorithm changed.
- **Cache boundary:** `GRADING_VERSION` enters existing eval case fingerprints only. Earlier
  grading output remains historical evidence; production Screen/Rank cache keys and prompts
  are unchanged. A regression test checks that separation. No automatic paid rerun is added.
- **Ordering/cancellation:** the shared collector uses the existing bounded pool and preserves
  cancellation propagation. Production discovery's intentional survivor policy is unchanged.
- **Read projections:** SQL tests check recipient precedence, limits, timestamp aggregation,
  lifecycle exclusions, bounded query counts, and absence of answer/retry-payload projections.
- **Editor:** tests exercise each family through its actual editor save callback, object and
  nested/scalar/empty lists, adding/removing entries, numeric/boolean values, text focus, locked
  ancestors, and the existing newer-draft/save-order behavior. Server schemas remain authoritative.

The final cross-consumer review found no further confirmed change worth expanding this
implementation to address. The browser review below closes the remaining verification item.

### Verification and net complexity

- Full backend: **1,111 passed, 1 skipped** (existing POSIX-only test on Windows).
- Full frontend: **368 passed across 50 files**.
- Production build, ESLint, Ruff (app/migrations/tests/scripts), and `git diff --check` passed.
- Compared with `c055007`, application source is **418 net lines smaller**. Tests are **319 net
  lines larger**, including removal of the unused agreement suite and catalog-read test.
  The benefit is substantive: one stability report replaces parallel Judge arrays; one
  expectation parser replaces divergent grading inputs; unused contracts and aggregation are
  removed. No new dependency, database migration, persistent identity, or general workflow
  abstraction was introduced.
- Read-side work decreases. Editor changes add no requests. Stability calls remain parallel
  with the same requested K; the collector retains errors rather than retrying. Production
  application cache behavior and user-facing save ordering are unchanged.

**Browser verification — completed after the user started the dev server:** used the Chrome
DevTools MCP and the existing signed-in local application tab. In the actual Evals screen,
checked consolidation object-list editing, blank-item addition/removal, and decomposition's
nested report lists. Typing from 60 to 61 characters retained focus in the note textarea;
locked metadata/pass fields did not expose ancestor-removal controls. Field spacing was 10px.
At 1920×855, the editor was 758px wide with no horizontal overflow. At 700×850 it switched to
one column; the deepest observed fields remained about 563px wide with no horizontal overflow.
The screenshot was inspected for clipping and alignment. No additional fix was needed.

All edits in the signed-in app were cancelled, the original 1920×855 window size was restored,
and Git confirmed that fixture files were unchanged. Before switching to signed-in Chrome, a
temporary local preview importing the real editor had also verified a synthetic object-list
save callback; that preview made no API writes and its files were removed. The browser check
does not claim an additional persisted fixture-save test; existing component/API suites cover
that boundary. No AI run, real provider call, applicant-data change, or production action was
performed. Commits remain local; pushing has not been requested for this follow-up.
