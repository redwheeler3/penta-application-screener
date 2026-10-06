# General project audit — 2026-10-06

**Status: complete.** Baseline: clean `main` at `99d9bbd`. This is a fresh audit
following the completed B01–B10 implementation recorded in the October 5 report.
Runtime changes are outside this audit phase.

## Scope and retained decisions

Review correctness, concurrency/reliability, readability, redundancy/dead code,
simplicity and responsiveness in multiple passes. Trace candidate findings through
producers, consumers, sibling flows and tests, and reproduce meaningful failures.

- Preserve submission-time age, automatic matching-cache adoption, coverage-based
  Screen/Rank readiness and retained consumed findings without applicant stale labels.
- Preserve unranked behavior and the two distinct paid Rank actions.
- Evals/Observability remain admin-only; evals are uncapped and fixture editing is local.
- A04 export privacy/source-guard work remains deliberately deferred.
- No production changes, real model calls, email sending, dev-server start, browser
  reload, database reset or applicant-data export is planned.

## Passes

1. Inventory and recent changes: source reachability, contracts, long owners and docs.
2. Backend correctness: transactions, authority, lifecycle/retention, caches, AI jobs,
   email, recovery and operational boundaries.
3. Frontend correctness: delayed responses, draft acknowledgements, navigation, actor/
   resource changes, run lifecycle and exceptional outcomes.
4. Simplification and responsiveness: duplicate rules/reads, dead interfaces, projections,
   unnecessary waits and misleading names or documentation.
5. Confirmation: reproduce candidates, inspect sibling paths, reject weak findings,
   consolidate recommendations and verification evidence.

## Findings

These recommendations are confirmed against the baseline. Implementation has not started.

| ID | Recommendation | Priority | Evidence |
| --- | --- | --- | --- |
| C09 | Clear only the browser draft acknowledged by submission | P2 | Synthetic save-flow interleaving removes a newer revision's stored draft |
| C02 | Keep note deletion final across retries of an uncertain creation | P2 | Real API create/delete/retry recreates the deleted note under a new ID |
| C03 | Make eval live/history reconciliation choose one coherent result per case | P2 | Two hook probes: missing current coverage and conflicting scores |
| C12 | Serialize scoped Judge case identity consistently across layers | P2 | A valid non-ASCII case runs once but restores zero results |
| C01 | Make recovery regression fixtures independent of the wall clock | P2, tests | Two baseline failures; both pass with explicit synthetic creation time |
| C04 | Batch opening candidate selection and project only needed fields | P3 | Forty candidates require 43 SELECTs and two full application reads |
| C07 | Derive eval call estimates from a stable per-case call shape | P3 | Six-case K=5 fixture shows 25 total calls and four per row; actual base shape is thirty/five |
| C10 | Make previous-applicant name search consistently Unicode-aware | P3 | Exact accented synthetic name returns zero results while its ASCII suffix returns one |
| C11 | Scope eval metadata reads and reuse captured Judge briefs | P3 | Five briefs need ten file reads; even empty scoring history reads all five families |
| C05 | Reuse the existing AI pass catalog for eval model/reasoning bindings | P3 | Five duplicated family bindings plus three duplicate categorical specs |
| C06 | Remove the contradictory missing-score neutral fallback | P3, cleanup | Healthy plan/retry paths enforce completeness; helper still fabricates zero for missing input |
| C08 | Align ranking comments/docs and helper ownership with coverage readiness | P3, readability | Current comments/docs still describe fingerprint gating contrary to SPEC/runtime |

### C01 — Recovery regression fixtures have passed their fixed deletion timestamp

`test_restore_upgrades_producer_fk_before_replaying_deletions` inserts applications
without `created_at`, so SQLite supplies the wall clock. Its deletion ledger instead
uses the fixed `2026-10-06 12:00:00` UTC timestamp. Once the inserted producer is newer
than that timestamp, restore correctly treats it as a later generation and retains it.
The test still expects the producer to disappear, so both parameterizations now fail.

**Evidence:** the full baseline produced these two failures and 1,059 passes. A
controlled rerun of the same scenarios, assigning synthetic application creation time
`2026-10-01 12:00:00` before backup, passed both. The observed audit clock was already
after the hard-coded deletion instant. This is fixture drift, not evidence that restore
should delete later generations.

**Recommendation:** make creation, deletion and retention timestamps explicit within
the synthetic scenario. Keep the production generation guard. Review sibling recovery/
migration fixtures for mixed fixed and live timestamps, rather than moving this cutoff
into the future again. **Latency:** none; test-only.

### C02 — A creation retry can resurrect a deleted committee note

The new creation key is stored only on `ApplicationCommitteeNote`. DELETE physically
removes that row, including the key. A browser retaining an uncertain creation attempt
can therefore retry after another tab of the same author deletes the committed note;
the server finds no prior key and creates the note again.

**Evidence:** isolated ASGI requests with synthetic data returned 200 for creation,
200 for deletion, then 200 for the original creation-key retry. One note reappeared
under a new database ID. The same-author, second-tab path is reachable; no manual
identifier collision or invalid input is needed.

**Recommendation:** preserve a minimal content-free creation/deletion receipt using
the existing application/author/creation key, or an equivalent representation of the
existing row. Replays of an already deleted creation must acknowledge its deletion,
not append it again. Purge that receipt with its application and retain no deleted note
text. Do not build a generic idempotency subsystem or deduplicate intentional repeated
text. Test delayed create acknowledgements, deletion and replay together, including
author/application scoping. **Latency:** a short database check; no network lock.

### C03 — Eval history still disagrees with displayed case results

`useEvalRunner` clears a mode by assigning `undefined`, then merges historical results
as `{ ...storedModes, ...existingModes }`. An existing `undefined` mode can overwrite
a valid restored outcome. The same merge also preserves any existing compatible local
result, not just the fresh receipt whose telemetry might have failed.

**Evidence:** two synthetic hook scenarios passed assertions for the current defects:

- After a partial run changes experiment, restored history contains valid results for
  cases A and B, but the live case map leaves B unset. The footer and a remounted tab
  show more current coverage than the live row dots.
- In one unchanged experiment, initial B is 0.1; stored history later returns B=0.9
  while an explicit run refreshes A. The history carries B=0.9, but live detail remains
  B=0.1. Matching input fingerprints establish compatibility, not equality of repeated
  model outputs.

**Recommendation:** actually remove cleared mode entries. Use stored newest outcomes
for ordinary compatible cases; protect only the exact just-completed receipt when its
storage cannot be confirmed. Reuse existing result/producer identity if ordering needs
to be carried, rather than introducing random revisions or another result cache.
Preserve changed-input/model/reasoning/K filtering. **Latency:** no extra read is needed;
the history refresh already occurs after every summary.

### C04 — Opening selection still has one query per applicant

`_selection_response` loads the active participants, then `selectable_opening_candidates`
loads them again and calls `selected_opening_id` individually for each application.
Both participant reads load full application entities, including answer/normalized JSON,
although this display needs IDs, names, emails and selection state.

**Evidence:** instrumenting the real response builder on forty synthetic candidates
recorded **43 SELECTs**, including two reads containing full application answer columns.
Selection confirmation also repeats the participant read before locating its candidate.
The already optimized opening-summary path remains separate and should be preserved.

**Recommendation:** use a batch selected-household predicate/set and a lightweight
selection read projection. Reuse captured participants on the commit path where it is
safe, retaining application/opening writer locks and fresh eligibility/finality checks.
Cover selected-elsewhere, withdrawn and expired households. **Latency:** fewer queries
and less JSON materialization; do not add a global pool cache.

### C05 — Eval configuration has a second copy of pass bindings

`AI_PASS_CATALOG` already owns each configurable pass's model and reasoning attribute.
`current_model` uses it, while `current_reasoning_effort` recreates all five eval-family
bindings and the three categorical eval specs repeat their model/reasoning strings.

**Evidence:** the duplicate categorical bindings currently equal their catalog entries;
this is redundancy and future drift risk, not a current model mismatch. The runners,
output schemas and graders legitimately differ by family.

**Recommendation:** resolve configurable model/reasoning bindings through the existing
catalog consistently. Keep Judge's independent fixed model and each family's concrete
runner/grader. Do not replace the evals with a generic engine or consolidate different
semantic prompt versions. **Latency:** neutral; fewer configuration definitions.

### C06 — An unreachable scoring fallback contradicts completeness

`plan_dimension_scoring` partitions every report dimension into validated cached output
or missing work. `_score_all_dimensions` retries missing outputs and raises on incomplete
results. However, `_assemble` still manufactures score 0.0 with low confidence if neither
map supplies a dimension; its docstring describes a policy the real scoring path now
explicitly prevents.

**Evidence:** direct synthetic invocation with a missing dimension produces a zero score.
Tracing both production callers shows healthy plans should never take that branch. It
therefore adds contradictory behavior and can hide a future completeness regression.
This does not establish that today's normal runs have fabricated scores.

**Recommendation:** remove the fabricated fallback and make assembly enforce the
existing complete-score invariant clearly. Keep legitimate model-produced neutral zero
scores and the targeted missing-dimension retry behavior. **Latency:** neutral; smaller,
more truthful assembly code.

### C07 — Eval spend confirmations use a stale total as their call shape

`AIWorkspaceView` reads the catalog when its family mounts. Saving/adding a case updates
`RunnableEval.cases` but leaves the catalog's absolute call totals unchanged. Per-row
estimates divide this stale total by the new case count.

**Evidence:** a component probe with an initial five-case K=5 catalog (25 calls) and
a current six-case fixture displays **four calls** for one row and **25 calls** for the
whole fixture. The normal base shape is five calls per row and thirty for all six.
This is the state reached after adding a case; removing cases has the inverse error.

**Recommendation:** carry a stable per-case call/repetition shape from the run/catalog
contract, and multiply by the current case count for whole runs. Keep the confirmation
and actual requested K consistent. Preserve the approximate wording for provider retries
and uncapped eval policy. No spending caps or additional user choices are proposed.
**Latency:** local arithmetic; no repeated catalog request is necessary.

### C08 — Ranking documentation still teaches the retired readiness rule

`frontend/src/types/applications.ts` says ranking currentness is not score coverage and
that a pool change flags Rank with full coverage. `docs/ai-screening.md` still calls the
rank-input fingerprint a gate and says the estimate exposes fingerprint currentness.
The `services/ranking/freshness.py` module description also presents its provenance
fingerprint as the readiness owner.

**Evidence:** SPEC and the actual dashboard/workflow use current score coverage and
pending proposals; discovery-only configuration changes do not invalidate retained
scores. The input fingerprint remains useful captured provenance. These are conflicting
explanations in current files, not historical ADRs.

**Recommendation:** correct the current comments and docs. Make the provenance helper's
description/ownership truthful; consider a narrow module rename if that improves its
discovery, without changing stored fingerprint shapes. Keep historical decisions in Git
and ADRs. This is not a proposal to bring fingerprint gating back. **Latency:** none.

### C09 — Submission cleanup deletes a newer remembered draft from another tab

After a successful submit, `persistAuthenticatedApplication` verifies that its own live
draft still matches the submitted snapshot, then calls `clearApplicationDraft(id)`.
That helper checks the consent lifetime but unconditionally deletes the application's
current storage record. It does not compare the browser record's answers/base revision
with the acknowledged submission.

**Evidence:** a synthetic save-flow probe delays the submission acknowledgement, writes
a newer remembered draft at the acknowledged working revision from another tab, then
delivers the original response. Submission succeeds, but the newer stored draft is gone.
The original tab's draft did not change, so its local equality check cannot protect the
other tab. The text remains in that tab's memory, but its promised browser recovery copy
has been removed. Invalid-date cleanup uses the same unconditional helper.

**Recommendation:** capture the specific browser record being acknowledged before the
request and compare it under the existing storage lock before deletion. Remove only an
unchanged matching record; preserve newer answers or a different base revision. Apply
the same snapshot rule to malformed-record cleanup where appropriate. Reuse the existing
consent scope, record fields and lock; no new storage identifier is needed. Keep explicit
sign-out/withdrawal consent-clearing semantics. **Latency:** one local comparison, with
no additional server request or save wait.

### C10 — Exact accented names can fail previous-applicant search

`search_previous_applicants` casefolds the query in Python, then compares it against
SQLite's ordinary `lower()` result. Those operations do not provide the same Unicode
normalization: accented uppercase name characters remain uppercase under this SQLite
function while the query becomes lowercase.

**Evidence:** an eligible synthetic previous applicant named `Élodie Synthetic`, with
a future retention deadline, produces zero results for its exact full name and one
result for the ASCII suffix `Synthetic`. The control holds eligibility constant; the
missing result is not caused by withdrawal, selection or expiry.

**Recommendation:** use the same Unicode-aware case normalization for the name and
query. Keep literal wildcard escaping, multi-term matching, current eligibility and
the result limit. For this small pool, a lightweight name/email projection with matching
before the result limit is a reasonable option; a tested database function is another.
Do not introduce a search service or expand direct-fill eligibility as part of this fix.
**Latency:** measure the chosen bounded read; it needs neither model work nor an extra
client request.

### C11 — Eval metadata reads are duplicated and wider than their scope

The catalog now reads each family once, but `/evals/judge-backgrounds` loads all five
families through `load_cases` for counts, then calls `get_background` once per family,
reading all five files again. The brief PUT also loads all five families solely to
return the changed family's count. `/evals/last-run` unconditionally captures every
family even for one pass, and even when no matching run is stored.

**Evidence:** instrumenting the real GET with the committed synthetic fixtures recorded
five brief rows and ten file reads, exactly two per family. An empty scoring-history
request also read all five files. These are siblings of B10 that the earlier catalog-only
fix did not cover. Count and text can come from different snapshots during local edits;
pass-specific history unnecessarily depends on unrelated family files being valid.

**Recommendation:** construct GET text/count rows from one captured dataset. For PUT,
read/capture only the changed family's metadata for its acknowledgement. Reuse the
existing snapshot and per-file locking. History should capture only the requested
families that have stored runs, reading a shared live/stability family once. Do not add
a global cache or another corpus.
**Latency:** fewer file reads and validations on the admin eval surface.

### C12 — Scoped Judge identity drops valid non-ASCII case keys

Python's `case_identity` uses `json.dumps` with its default ASCII escaping, while the
frontend's `JSON.stringify` and SQLite's `json_array` produce a different string for
non-ASCII keys. The family/key pair is semantically identical, but the qualified string
keys do not compare equal. The case schema permits these keys.

**Evidence:** a captured synthetic fixture with Judge key `synthetic-café` produced one
successful live case and zero restored cases through the real API/mock-provider path.
Python's qualified identity contains a literal `\u00e9` escape, so SQL's qualified raw
Unicode identity is excluded by the current-case filter. The same mismatch affects the
frontend's current-fingerprint lookup. The stored result itself remains in the database.

**Recommendation:** use one consistent representation of the existing family/key pair
across Python, JavaScript and SQLite; emitting Unicode consistently is the small direct
fix. Test accented/non-BMP keys, quotes and literal backslashes through run, restore and
row selection for both Judge modes. Do not add an identifier, restrict valid keys to
ASCII or alter their case. Existing ASCII identities and case-input hashes can remain
unchanged. **Latency:** neutral; no new query or model call.

## Source map at the audited baseline

| Finding | Main anchors |
| --- | --- |
| C01 | `backend/tests/test_backup.py:272`; generation guard in `backend/app/services/backup.py` |
| C02 | `backend/app/api/applications/routes.py:349`, `:402`; `ApplicationCommitteeNote.creation_key`; `CandidateNotes` uncertain creation attempt |
| C03 | `frontend/src/components/evals/useEvalRunner.ts:103`, `:162`; `caseResults` versus `restored` |
| C04 | `backend/app/api/openings.py:303`; `backend/app/services/openings/selection.py:53` |
| C05 | `backend/app/ai/pass_catalog.py`; `backend/app/api/evals/_shared.py:217`; categorical specs in `runs.py:168` |
| C06 | `backend/app/ai/dimension_scoring.py:228`; `plan_dimension_scoring`, `_score_all_dimensions`, both assembly callers |
| C07 | `frontend/src/components/ai/AIWorkspaceView.tsx:62`, `:112`; `RunnableEval.tsx:108` |
| C08 | `frontend/src/types/applications.ts:14`; `docs/ai-screening.md:223`; `backend/app/services/ranking/freshness.py:1`; current policy in `SPEC.md:1182` |
| C09 | `frontend/src/applicant/applicantSaveFlow.ts:183`; `draftStorage.ts:125`, malformed-date cleanup at `:73` |
| C10 | `backend/app/services/openings/direct_selection.py:47` |
| C11 | `backend/app/api/evals/cases.py:66`, `:77`; `catalog.last_run` unconditional dataset capture |
| C12 | `backend/app/evals/dataset.py:16`; `backend/app/api/evals/history.py:40`; `frontend/src/api/evals.ts:143` |

## Completed passes and confirmation

1. **Inventory/recent changes.** Reviewed the seven latest implementation/documentation
   commits and ownership changes. Ran source/reference scans over roughly six hundred
   tracked source/test/migration files, excluding generated caches and dependency trees.
   No obvious unreferenced top-level backend functions or frontend runtime exports, or
   substantial exact duplicate function bodies, justified deletion. These scans are
   triage, not proof that dynamic references or semantic duplication cannot exist.
2. **Backend correctness.** Traced application save/submission and frozen-age input
   identity; opening participation/selection; eligibility and selected consumers; retention,
   purge and restore; auth/actor checks; run leases, streaming cancellation and cost capture;
   email reservation/retry/consent; eval capture/readers/history; health/static serving and
   local/Fly/watchdog entry points. Followed the new note retry contract through deletion,
   and the new history contract through repeated, partial and Unicode cases.
3. **Frontend correctness.** Reviewed actor-scoped clients, request scopes, navigation and
   pending-detail receipts; opening/eligibility/settings saves; private and committee notes;
   Screen/Rank start/completion and passive refreshes; applicant browser consent, saves,
   email identity, logout/withdrawal; eval editing, live summaries and history accumulation.
   Traced the browser cleanup beyond single-tab acknowledgements into another tab's record.
4. **Readability/redundancy/responsiveness.** Checked large owners, exact duplicates and
   public reachability; looked for conflicting field/configuration definitions, dead policy
   branches, stale comments and overly wide reads. Instrumented opening selection and eval
   metadata I/O rather than inventing another cache. Distinguished static documentation
   drift from a request to change accepted product behavior.
5. **Confirmation/sibling review.** Used isolated API/service/hook/component probes for
   the retained findings. Checked Unicode in both human-name search and qualified eval
   identity, and fixture-read duplication in both catalog siblings and pass-specific
   history. Rechecked the producers that make the missing-score fallback unnecessary.
   Consolidated recommendations without an arbitrary finding count; rejected candidates
   that did not establish a worthwhile change in the supported flow.

Temporary probes were removed after confirmation. They asserted the current defects or
controlled fixture behavior; their green results do not mean these findings are fixed.
Only this audit document is an intended repository change.

## Verification and limits

| Check | Result |
| --- | --- |
| Backend Ruff | Passed on the clean baseline |
| Full backend pytest | **1,059 passed, two failed, one existing platform skip**; failures are the C01 date-dependent restore scenarios |
| C01 timestamp controls | Both original scenarios pass with explicit synthetic creation time |
| Frontend tests | **319 passed across 48 files** on the baseline |
| Frontend TypeScript/build/ESLint | Passed |
| Watchdog TypeScript/tests | Passed; **nine tests** |
| Focused frontend probes | Four synthetic scenarios reproduced C03, C07 and C09 |
| API/service instrumentation | Confirmed note resurrection; 43 selection SELECTs for forty candidates; Unicode search 0 versus ASCII control 1; ten reads for five Judge briefs; five reads for empty scoring history; Unicode Judge live 1 versus restored 0 |
| Filesystem/Git | Probe files removed; build/cache inheritance enabled; runtime working tree unchanged |

No production health/database inspection, deployment, push, model call, actual email,
dev-server start, browser reload or data reset was performed. Tests and probes used
synthetic records, temporary/in-memory databases, committed synthetic fixtures and mock
providers. The review does not claim every possible future interleaving is exhausted.
Rendered layout and real model judgement were outside this source/contract audit.

## Recommended implementation sequence

1. Fix C01's test clock at its source, making the baseline useful again without loosening
   restoration's generation protection.
2. Fix C09's browser-record acknowledgement/deletion rule, with the cross-tab submission
   regression and malformed-record sibling coverage.
3. Complete C02's note creation/deletion replay contract, keeping receipts minimal and
   applicant-scoped. Verify purge/restore ownership if persistence changes.
4. Fix C12's small identity serialization mismatch and C03's live/history reconciliation.
   Then address C07/C11's call shape and scoped metadata capture; C05 can be a separate,
   behavior-preserving configuration cleanup. Keep family graders and exact prompt content.
5. Tackle C04/C10 together as opening candidate read/search improvements, preserving the
   existing eligibility/finality policy and measuring reads after the change.
6. Remove C06's contradictory fallback and correct C08's present-tense documentation and
   ownership wording. Keep legitimate zero scores, historical records and stored provenance.

Use cohesive commits with relevant regressions, not one broad rewrite. All twelve are
worth addressing; none requires a new product feature, blanket network synchronization,
automatic paid work or an eval spending cap. If implementation uncovers an actual product
decision or significant measured latency tradeoff, surface that specific choice then.

## What I would leave alone

- The ORM registry is about 1,137 lines but remains a coherent set of schema/relationship
  definitions. Other large production owners are below the roughly 800-line review trigger.
  A cosmetic split or general rename sweep would make this audit less useful.
- Preserve `useRequestScope`, ordered same-field writes, snapshot acknowledgements,
  account-owned private-note drafts, per-file fixture locks and short writer/lease fences.
  The findings are gaps at specific boundaries, not evidence that these mechanisms should
  be replaced with a generic transaction/event framework.
- Preserve automatic matching-cache adoption, coverage/proposal readiness, meaningful
  provider-route equivalence and frozen submitted ages. Do not reintroduce cache-reuse
  prompts, birthday-triggered misses or per-applicant stale labels.
- Preserve distinct family graders and Judge independence. C05 is about repeated model/
  reasoning bindings, not homogenizing different assertions or prompt versions.
- Preserve the previous-applicant search's current cohort/selection/retention policy.
  C10 corrects valid-name matching; it does not open direct-fill selection to a different
  active or unanchored cohort. That would be a product decision.
- Preserve imports of supported historical answer formats and historical migrations/ADRs.
  No retiring-form deletion backlog or dependency upgrade is justified here.
- Preserve the stopped/suspended-machine watchdog rule, bounded public rate limiter,
  consent-aware email consumption, fresh credential publication before send, targeted
  scoring re-asks and deliberately approximate provider-spend estimates.
- A04 export privacy/source-guard work remains deferred. Hosted fixture editing and an
  eval budget subsystem remain outside the accepted scope.

## Complexity assessment

The architecture still benefits from the recent fixes. The strongest new findings come
from extending an existing boundary to its next consumer: storage cleanup must honour the
exact browser record, note creation identity must outlive deletion enough to stop replay,
and a family/key pair must serialize identically wherever it is consumed. The cleanup
recommendations reduce conflicting definitions and unnecessary reads.

I would implement these specific recommendations and stop at the resulting correctness/
readability threshold. I would not use the number of findings to justify a generalized
workflow engine, another results store, global caches, wider locks or a wholesale refactor.
