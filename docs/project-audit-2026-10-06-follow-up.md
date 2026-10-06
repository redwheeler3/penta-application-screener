# Consolidation and correctness audit — 2026-10-06

**Status: U01–U06 implemented and verified; post-push review pending.**
Audit baseline: `b4df0b7`; implementation baseline: `440061a`. The recommendations
below retain their original audit evidence. Implementation outcomes are recorded at
the end; they supersede statements describing the unchanged audited baseline.

## Recommendation and assessment

Keep the useful reliability work, then implement the six cohesive packages below.
Do not revert the week or start a broad architectural rewrite. The code is better
organized in several important respects, but some recent fixes have accumulated
overlapping state and incomplete lifecycle rules. Those areas deserve consolidation
alongside the confirmed bugs. Green tests alone did not establish simplicity or
coverage of the subsequent operations.

The clearest excess is in eval reconciliation and ranking response/state ownership.
Cache lookup logic is also repeated across consumers, and local recovery maintains
an additional application-deletion graph. The request identity boundary, revision
checks, consumed-result references, lease fencing, and durable email outbox have
distinct jobs; removing them would recreate demonstrated failures.

This is a comprehensive plan for the reviewed scope, not a guarantee that every bug
has been found. Follow-up discoveries in these same contracts should join the same
implementation campaign, with their evidence recorded here, rather than require
another user-prompted audit round.

## Scope, history, and measured growth

The history window begins September 29, 2026, local time. Its pre-change baseline is
`1b35aa4` (September 28); the audited head is `b4df0b7` (October 6): **129 commits**.
Review included recent implementations, their callers and tests, historical-schema
dependencies, and affected product decisions. Completed B01–B10 and C01–C12 remain
historical records in the other audit documents; this file is the active plan.

| Measure | Before | Audited head | Interpretation |
| --- | ---: | ---: | --- |
| Python application + TypeScript/TSX application source lines | 45,217 | 49,231 | +4,014, about 8.9%; excludes frontend tests and testSupport |
| Files in that source set | 289 | 330 | +41; includes intentional ownership splits |
| Net application/tooling/style/config growth | — | +4,371 lines | Broader than application source alone; excludes tests/docs |
| Net test growth | — | +11,425 lines | Most net growth was regression coverage |
| Net Markdown/collaboration-rule growth | — | +1,832 lines | Includes three audit reports and architecture/spec updates |

These are physical line counts, not a complexity score. File moves/splits do not
inflate net totals. The raw rename-aware diff has 436 changed files; it includes
tests, documentation and tooling. It should not be read as 436 new responsibilities.

Repeatedly changed owners include `CommitteeWorkspace.tsx` (14 commits),
`useApplicantPersistence.ts` (13), `ranking/pipeline.py` and `applicantSaveFlow.ts`
(12 each), `useEvalRunner.ts`, `dimension_scoring.py`, and `score_current.py`
(11 each), and `useRanking.ts` (10). This concentrated churn informed the review;
it is not itself a finding against those modules.

## Established product boundaries

- Age remains calculated at submission. Birthdays alone must not invalidate caches.
- Reuse matching caches automatically. Retain the last consumed findings after a
  submission changes; workflow amber conveys incomplete current coverage.
- Screen/Rank readiness comes from current coverage, with pending criterion
  proposals additionally affecting Rank. Discovery provenance is not a readiness gate.
- Keep the two distinct paid Rank actions. With no positive priorities, keep the
  criteria controls and notice; hide ranked applicants, View, and Print.
- Evals and Observability are admin-only. Evals have no spending cap. Edit their
  fixtures locally and deploy the committed corpus for hosted runs.
- Imported-form data readers are still needed. The discontinued importer is not.
- A04 export privacy/source-guard work remains deliberately deferred.
- Production recovery accepts rollback to a Fly snapshot retained for 30 days.
  `SPEC.md` explicitly excludes a separate production deletion-reconciliation
  system. Local restore has stronger hard-purge handling. Preserve this distinction.

No production access, real model calls, outbound email, local database changes,
dev-server start, browser reload, or deployment was performed for this audit.

## Review passes and evidence

1. **History and ownership:** inventoried the week's commits and changed paths;
   measured net growth; inspected existing decisions and the architecture map.
2. **Contracts end to end:** traced browser identity, applicant saves/storage,
   committee edits/navigation, ranking/cache consumption, run cancellation/cost,
   email attempts, fixture/eval results, and local migration/recovery boundaries.
3. **Behavior and cost:** ran full baseline suites, synthetic sequence probes,
   and query-count instrumentation against a small in-memory pool.
4. **Counter-review:** challenged proposed abstractions and deletions against their
   callers, failure cases, latency, historical data, and prior product decisions.
   In particular, rejected expanding production recovery policy by implication.

Verification at the audited head:

- Backend: **1,072 passed, one platform skip**. The initial sandbox run could not
  prepare the established `.pytest-tmp`; the normal-access rerun passed in 70 seconds.
- Frontend: **329 passed across 49 files**.
- Four temporary frontend probes confirmed the two eval failures, stale mounted
  Matching audit, and older-revision browser overwrite described below.
- Two temporary backend probes reconfirmed the historical migration failure and
  credential resurrection; the recovery probe also confirmed a restored orphaned
  run lease. These probes assert observed defective behavior, not correct behavior.
- An AST import scan, including function-local absolute imports, found no strongly
  connected module groups and no service-to-API imports. This is a bounded static
  check, not proof about dynamic imports.
- No production latency benchmark or visual browser test was run. Query counts
  below are synthetic measurements, not estimates of user-visible milliseconds.

Temporary probes were removed after recording their scenarios. Implementation
should turn them into permanent expected-behavior regressions in the relevant
existing test modules. No application code or permanent tests changed in this audit.

## Implementation packages

| ID | Package | Reason | Expected complexity effect |
| --- | --- | --- | --- |
| U01 | One eval result reconciliation contract | Confirmed P2 failures; prior R02 | Replace overlapping merge branches with explicit input state and one selector |
| U02 | Coherent ranking and Observability ownership | New P2 stale trace; repeated payload/state | Remove unused fields, unnecessary copying/reads, and inconsistent trace lifetimes |
| U03 | Shared cache lookup and request-local inputs | P3 duplication and avoidable work | Delete repeated key-grid/query code without adding another cache |
| U04 | Complete browser draft ordering | New P2 unsaved-draft overwrite | Add the missing revision condition within the existing lock; retain current identity model |
| U05 | Self-contained historical migrations | Confirmed P2 upgrade failure; prior R01 | Remove dependence on changing runtime services/catalogs |
| U06 | Explicit local recovery preparation | Confirmed P2 credential replay; prior R03; orphan lease | Reuse erasure mechanics and reset transient authority/work state |

Prior Q01 is addressed under U06: ordinary snapshot rollback remains the accepted
policy; a universal cross-snapshot preservation system is not part of this plan.

### U01 — Give delivered and stored eval results one reconciliation contract

**Evidence.** `frontend/src/components/evals/useEvalRunner.ts:64` combines
`caseResults`, `restored`, an `experiments` ref, and a one-call `receipt` argument.
The `seedResults` flag changes which source wins. Current configuration and case
fingerprints arrive only inside historical runs from `api/evals/catalog.py:last_run`.
An empty history returns before reconciliation at line 69.

Reconfirmed sequences:

1. Stored score A=0.1; a new same-experiment run delivers A=0.8 but cannot persist.
   The immediate history refresh retains 0.8. A second `refreshHistory()` replaces
   it with 0.1. Saving a brief/case can reach that same reseeding path.
2. With no stored history, deliver a passing A=0.8. Edit the expected minimum to
   0.9 through `setCases`. Empty history leaves the old result displayed as current
   and passing. The server has supplied no independent current metadata to reject it.

The latest fixes correctly protect the first refresh, but do not model the result's
whole lifetime. A same-experiment identifier alone cannot establish which case
result is newer or whether the case's expected answer changed.

**Target design.** Keep the persistence-failure policy: useful paid output remains
visible even if history storage fails. Represent delivered receipts explicitly for
the mounted eval view, alongside stored history and current metadata. Derive displayed
case outcomes through one pure reconciliation function; do not independently mutate
another copy of the same accepted results.

- Return current mode configuration and case fingerprints even when no saved runs
  exist, preferably in the existing history response. Capture metadata per request.
- Use existing run IDs, experiment IDs, input fingerprints, mode and case identity.
  Return the source run ID for each reconstructed historical case: the newest
  aggregate run ID is not proof that every included case is newer. A recorded
  receipt yields when that case's stored provenance reaches or exceeds its run ID.
  An unrecorded receipt has no comparable database ID; retain it as a view-local
  override until the same case is run again, its inputs/configuration change, or
  the view is disposed. Refresh other cases normally. Do not guess chronological
  precedence from an aggregate ID or invent a durable second result store.
- Preserve other cases/modes only when compatible; an unrelated mode's completion
  must not reintroduce or erase outcomes in this mode.
- Derive experiment/display state from these records instead of separately updating
  `experiments.current` while seeding cases. Remove the identical ternary branches
  around line 176 along with the obsolete merge path.
- Make fixture-read failure distinguishable from an empty corpus. `loadCases` now
  catches failures and installs `[]`. Use the existing loading/error/retry convention
  rather than presenting a failed read as an empty fixture.

**Acceptance.** Run → first and second refresh → other mode → editorial note edit →
label/input edit → model/prompt/reasoning change → failed refresh → remount. Cover
stored, unrecorded, and history-older-than-receipt outcomes. Metadata changes expire
current status without automatically buying another AI run. Summaries, per-case
markers, and historical labels must agree.
Also cover two partial runs where the newest aggregate includes an older case;
the stored row's source, not just the aggregate's run ID, must govern precedence.

**Latency/complexity.** Local selection and existing free reads; no new model wait.
Some explicit receipt state is necessary, but it replaces transient merge exceptions.
Preserving only persisted output would be simpler but would discard useful paid
results; that product tradeoff is not recommended.

### U02 — Narrow ranking contracts and scope every trace to its analysis

**New correctness finding.** `AIWorkspaceView.tsx:144` keys Discovery by analysis,
but Matching, Decomposition and Consolidation receive only `openingId`. Their
`useFetchResource` calls have no reload key. A synthetic render of the real workspace
loaded Matching for analysis 1, then changed the run to analysis 2 in the same opening.
The component made no second request and still displayed analysis 1's criterion.

There is a related source-level gap: all four trace endpoints read `/current`, and
their returned `analysisId` is not checked against the run being reviewed. A new
analysis between board and trace requests can therefore mix generations even if
the component remounts. A React key alone is not the complete solution.

**Redundancy.** `api/ranking/presentation.py:30,71` computes member fields separately
for `CurrentRunResponse` and `RankingResponse`. A board contains both. Source/caller
tracing found:

- `keptKeys` is not read by the frontend from either response. Remove these wire
  copies and the now-unneeded per-member `kept_keys` helper; adapt tests to the
  surviving behavior. Preserve the distinct `committee_kept_keys` calculation
  used by discovery, including members who skipped the immediately previous run.
- New/revived/requested badges are rendered from `ranking`, while `/current`
  computes another set. `useRanking.ts:254` even copies requested badges into the
  run object although that copy has no rendering consumer.
- Proposals are rendered from `rankingRun`; the duplicate ranked-list field is unused
  by application consumers. Remove it as part of the matched API/type update.
- The claimed hidden-board “ID-only” check actually fetches the full `/current`
  payload, including dimensions and, for admins, discovery narrative. It is not an
  ID-only request. The dashboard already resolves the current analysis independently.
- `reloadStaleRanking` serially reads `/current` and then `/board`, although the
  successful board already supplies a coherent criteria/ranking/tier snapshot.

**Target design.** Keep `useRanking` as the owner of the accepted board and its
optimistic tier/proposal edits. Make server payload responsibilities disjoint, with
analysis identity retained wherever it validates coherence. Apply reads and narrow
mutation receipts through named transitions over that state. Remove synchronization
code made unnecessary by deleting duplicated fields; preserve the serialized member
write queue and protection of newer optimistic edits.

Expose current analysis identity through the existing dashboard response for hidden
checks where practical, and use one `/board` read for explicit reload. Keep cheap
initial criteria metadata so the Ranking tab/proposals do not require a full ranked
pool just to become visible. Move discovery narrative to the existing admin trace
boundary, preserving the supported single-pass historical fallback there.

Pass the viewed analysis ID through every trace request and verify opening ownership
server-side. Prefer reading that retained analysis explicitly; alternatively return
an explicit stale response rather than silently substituting current analysis.
All trace panels must refresh for changed analysis and applicable completed work
within the same analysis. Do not use a new persistent generation identifier.

**Acceptance.** Old board/new current analysis, pending tier/proposal edit plus late
board read, queued failure plus newer edit, explicit reload, switching openings,
mounted trace across a run, delayed trace after switching analyses, and wrong-opening
analysis requests. Preserve current zero-priority behavior and tier-save acknowledgement
in one round trip. Test the real workspace/panel wiring, not only isolated fetch mocks.

**Latency/complexity.** Fewer unused fields, less repeated member-history work, one
less serial read on reload, and no discovery narrative on ordinary board refreshes.
Do not replace the hooks with a new global state library or refresh every surface
synchronously after every mutation.

### U03 — Share cache lookup mechanics without merging distinct meanings

**Evidence.** The applicant × pass/dimension cache grid is reconstructed separately in
`api/dashboard.py:_coverage`, `ai/dimension_scoring.py:missing_dimensions_by_application`,
`plan_dimension_scoring`, and `services/cached_results.py:_matching_references`.
Chunked row lookups and selected-reference comparisons also recur. The cache-key
function is shared, but the surrounding membership/query algorithm is not.

`present_cache_keys` uses an unchunked `IN`; the scoring/adoption paths independently
choose batches of 500. No installed-SQLite parameter-limit failure was reproduced;
the inconsistent batching is a consolidation opportunity, not a claimed production bug.

A warmed two-applicant/two-criterion synthetic pool measured:

| Operation | SELECT statements |
| --- | ---: |
| Current criteria | 4 |
| Ranking board | 19 |
| Dashboard | 23 |
| Cache adoption with nothing changed | 19 |

The fixture used two mock-provider calls to seed results; measured reads made no
provider calls. Counts depend on pool/rules/session state and are evidence of work
to examine, not performance targets or claims of user-visible sluggishness.

**Target design.** Introduce a small shared cache-key grid/lookup boundary, or expand
the existing helpers coherently, and delete the repeated implementations. Support
thin existence/reference projections for coverage and adoption; scoring alone needs
structured output/tokens and captured model inputs. Reuse an already captured pool,
configuration, and screening findings within a request where it avoids recomputation.

Keep these meanings distinct: a matching cache exists; a result was selected for
this consumer; a prior consumed result is still retained. Do not replace selected
references with “latest result” or cause coverage reads to publish output. Preserve
the adoption service's writer-time recheck and exclusion of active AI runs.

Also avoid calling `email_queue_status` for ordinary members in `read_dashboard`:
the result is only used in the admin branch. That is a direct deletion of wasted
work with no new abstraction. Coordinate refresh scheduling through the existing
workspace owner so adoption-triggered refreshes do not proliferate new owners.

**Acceptance.** Compare coverage, estimates, planned calls and adoption for full hits,
partial vectors, duplicate-content consumers, changed submitted facts, model routes,
reasoning/prompt changes, withdrawal and expiry. Assert bounded query growth over
larger synthetic grids and no extra model calls. Verify producer/consumer deletion
in both orders and retained older findings after a genuine miss.

**Latency/complexity.** Expected reduction in repeated work. Keep lightweight reads
lightweight; making dashboard coverage build full scoring prompts would be a regression.
No process-wide memoization, polling service, new cache table or cross-request snapshot.

### U04 — Reject browser writes based on an older server revision

**New confirmed finding.** `draftStorage.ts:93` serializes writes and checks the
consent lifetime, but unconditionally replaces the application's stored draft at
line 105. In a synthetic same-consent sequence, save unsent answers based on server
revision 2, then let an older tab save its revision-1 draft. The second call reports
success and replaces revision 2. `restoreApplication` only restores browser drafts
whose base revision matches the server, so revision-2 unsent answers are no longer
recoverable from that storage slot.

This overwrite possibility predates the week's changes. The recent locking and
compare-before-clear work addressed other interleavings but did not close this one.
It does not overwrite the server's submitted answers.

**Target design.** Within the existing storage lock and consent check, reject a write
whose base revision is older than the stored record for that application. Return an
unsaved/conflict outcome through the existing browser-storage owner so the tab does
not claim its draft is stored. Keep its in-memory answers and leaving warning.
Reuse `workingRevision`; no timestamp ordering, per-tab persistent identity, or
browser synchronization framework is needed.

Keep exact snapshot comparison for acknowledgement cleanup. Centralize the meaning
of stored-draft equality where useful, but do not merge browser persistence and
server acknowledgement into one “saved” flag: those are different durability claims.

**Acceptance.** Two tabs/same consent: revision 1 queued after revision 2; ordinary
same-revision edits; newer server revision; consent revoked/replaced; delayed submit
cleanup; storage failure; another applicant's independent record. At hook/form level,
a rejected write must not disable the leaving warning. Include focus and subsequent
reload, not just direct storage function calls.
Test reauthentication after a local snapshot restore too: it can rewind a working
revision. Recovery from a browser/server revision mismatch must remain possible
through explicit draft disposal or an acknowledged server save, without silently
discarding a potentially useful newer browser copy.

**Boundary.** One per-application browser slot does not preserve two divergent drafts
at the same base revision. Retain the existing behavior for that case; collaborative
draft merging is a separate product feature and is not proposed here.

**Latency/complexity.** One comparison within an existing short lock, no network
request. This is necessary missing logic, not a reason to rewrite the intake workflow.

### U05 — Make historical migrations independent of today's application

**Reconfirmed R01.** Upgrade a synthetic schema at `f0a1b2c3d4e5` containing two
openings and one submitted participation. Upgrade to head fails with
`no such table: application_ai_selections`. Migration `1c2d3e4f5a6b:303` calls current
ranking provenance/eligibility code before that later table exists. Empty-schema
upgrades bypass the relevant data-dependent path.

The same audit found mutable application imports in `a47e5c19b203` (model identity
catalog) and `d3e4f5a6b7c8` (current settings schema/key). These are future coupling
risks; no additional failure is claimed for those two revisions in today's catalog.

**Target design.** Historical migrations own their revision-local schema and mapping
rules. Remove imports of live ORM/services/settings/model catalogs. Freeze the exact
historical constants/projections where needed. This deliberate historical duplication
is correct: a migration must not change meaning when runtime business rules change.

Preserve the one-opening rule and every paid historical record. For multiple openings,
assign ownership only when persisted revision-local evidence proves it. Leave genuinely
ambiguous analyses unscoped. Do not reconstruct historical intent from today's prompt,
model configuration, eligibility rules or date-sensitive pool. Do not invent ownership
to force an upgrade through, reset the database, or squash the migration chain.

**Acceptance.** Populated one/multiple-opening snapshots, ambiguous analyses, imported
and native answers, retained cache rows, retired provider routes, and restore through
the same upgrade path. Check foreign keys and preservation of paid output/cost. Add
a focused boundary check preventing future live-application imports in migrations.

**Latency/complexity.** Migration/recovery only. A small frozen migration helper is
preferable to a compatibility layer threaded through the live application.

### U06 — Prepare local recovery explicitly and reuse aggregate erasure

**Reconfirmed R03 and new lease case.** A file-backed synthetic snapshot taken before
logout/link consumption restores a valid session and redeemable one-time committee
link. Both are rejected immediately before restore and accepted after it through
the actual authentication/consumption helpers. The same probe captured an active
Rank lease, released it in the live database, then restored the snapshot: a new run
could not acquire the lease although its original worker no longer existed. The
lease can block work until its remaining 15-minute TTL expires.

**Target design.** Keep the isolated candidate-database preparation already in place:
copy → upgrade → replay supported hard-purge facts → sanitize transient state →
preserve identity high-water marks → integrity/FK validation → publish.

- Invalidate restored browser sessions and one-time credentials before publication.
  Preserve referenced audit identities as necessary; fresh authentication follows
  recovery. Cancel restored credential-issuing retry intents too, otherwise the
  outbox could manufacture replacement grants automatically.
- Clear restored run ownership whose process cannot resume. Review maintenance and
  delivery attempt state using their existing lease/attempt contracts. Preserve
  ordinary durable notification intents and their current lifecycle checks; do not
  blanket-delete the outbox or claim exactly-once external delivery after rollback.
- Keep the live database untouched if preparation fails. Do not perform real email
  sends during recovery tests or hold a live database writer while preparing a copy.

**Consolidation.** `services/backup.py:44,321` enumerates child tables and performs
its own application/draft deletion, while `services/applications/purge.py:93,144`
and database cascades own operational erasure. After a real project snapshot has
been upgraded, use the same current-schema aggregate-erasure mechanics. Keep the
decision about *which* records to erase and the deletion ledger outside that helper.
Preserve feedback detachment, reference-aware result retention, and transaction
ownership. Supported legacy/unversioned snapshot handling must be explicit; do not
silently skip unknown schema pieces to claim successful erasure.

**Recovery-policy correction to the previous report.** Its Q01 suggested broadly
preserving access/consent/deletion facts across rollback. `SPEC.md:708,1576` and
`docs/deploy.md:390` already accept production snapshot rollback and reject a
separate production reconciliation system. Do not infer authorization to expand it.
Ordinary notes and other business data remain point-in-time recovery data. Do not
add a note-deletion overlay or universal security/consent ledger in this campaign.

Credential invalidation alone does not preserve every authorization change: restored
allowlist entries or subscriptions still reflect the snapshot. That is a policy
boundary, not something to conceal behind a “secure restore” claim. Changing the
production restore procedure or preserving those facts requires an explicit product/
operations decision. Recommendation: make the bounded local preparation improvements,
document their limits, and retain the existing production policy.

**Acceptance.** Logout → restore → old cookie; consume/revoke link → restore → replay;
queued credential retry after restore; run active in snapshot → stopped → restore;
failed candidate migration/sanitization leaves live state unchanged; deletion replay
with shared result producers/consumers, feedback, drafts, note receipts, and ambiguous
legacy record IDs. Reuse existing isolated file-backed fixtures.

**Latency/complexity.** Recovery-only work and fresh sign-in; no ordinary application
latency increase. Shared erasure should remove the duplicate graph. Explicit transient
reset logic is justified; a generic recovery engine is not.

## What should stay, and what should not be expanded

| Area reviewed | Keep / recommendation |
| --- | --- |
| Captured API clients and server identity checks | Keep. Browser cookies can change independently of queued work; scope checks alone cannot bind the server request to its intended account. |
| `useRequestScope` | Keep its small resource/request lifetime primitive. Do not combine ordered reads and independent writes into one last-request-wins rule. |
| Applicant revision and exact submitted snapshot acknowledgements | Keep. They protect different sides of a save; neither replaces the other. |
| Browser consent scope and snapshot cleanup | Keep; add U04's revision condition. Do not replace them with timestamps. |
| Account-owned private-note editor | Keep. It preserves unsaved drafts across navigation and avoids workspace rerenders on every keystroke. Committee notes have different attribution/retry semantics. |
| Narrow committee mutation receipts and per-field queues | Keep. They prevent unrelated fields and navigation from being overwritten. Remove the unused `selectedApplication` option from `useCandidateActions` during adjacent cleanup. |
| `ApplicationAISelection` and result retention | Keep. “Latest output” cannot represent consumed results shared by multiple applications or the retained-findings policy. |
| Run lease, commit fence and HTTP cancellation layers | Keep. They own cross-process exclusion, publication authority, and request lifetime respectively. No evidence supports collapsing them into one generic job framework. |
| Measured cost capture on failure/interruption | Keep. Useful operational facts should survive partial failure; unknown late provider cost remains unknown. |
| Email attempt identity and durable outbox | Keep. Provider I/O is outside short write transactions, and late attempts cannot replace a newer outcome. No broker or general task queue is justified. |
| Opening publication request identity and conditional edits | Keep. Retry of a new publication differs from revision checking an existing opening. |
| Local fixture locks, atomic replacement, and scoped datasets | Keep. They are small and appropriate to local-only editing. Do not add hosted editing, cross-process distributed locks, or eval caps. |
| Imported-answer adapters and historical migrations | Keep needed data readers; freeze migrations under U05. Old data support is not a dead importer. |
| Large declarative model/schema files | Do not split by arbitrary line limits. `models.py` is large but splitting it now would add navigation/import churn without addressing these findings. |
| Workspace and applicant workflow splits | Retain the existing domain boundaries. Do not add several more tiny hooks merely to shorten the remaining orchestration files. |

The import check and source tracing found no reason for another wholesale directory
reorganization, dependency replacement, state-management library, new ID family,
event bus, cross-request cache, or generalized retry/idempotency subsystem.

## Verification map and completion criteria

Use existing pytest/Vitest helpers, mock providers, controlled promises, explicit
synthetic times and isolated SQLite files. Prefer a small table of operation sequences
per domain over many new tests that only repeat an implementation branch.

| Contract | Required sequence / existing test owners |
| --- | --- |
| Eval validity and source precedence | U01 sequences; `useEvalRunner.test.ts`, `test_eval_experiments.py`, `test_evals_api.py` |
| Ranking snapshot and trace identity | U02 sequences; `useRanking.test.ts`, real AI workspace/panel tests, `test_ranking_board.py`, operator-access tests |
| Cache coverage/selection/retention | U03 cases; `test_cached_results.py`, `test_dimension_scoring.py`, `test_result_retention.py`, dashboard/query-count tests |
| Applicant browser/server acknowledgement | U04 sequences; `useRememberedApplicantDraft.test.ts`, `ApplicantDraftStorage.test.tsx`, save-flow/persistence tests |
| Historical upgrades | U05 populated schemas; `test_migrations.py`, recovery tests |
| Recovery | U06 credential/lease/erasure sequences; `test_backup.py` plus real auth helpers |
| Existing guarantees during refactor | Candidate/navigation, note create-delete-retry, two-member writes, auth changes, selection/withdrawal, HTTP disconnect and silent worker, email late-attempt tests |

For each package: first establish the failure/contract tests, implement the complete
owner change, delete the superseded path in the same commit series, and inspect its
callers/siblings. Tests should observe behavior through an appropriate boundary;
counting more green tests is not a substitute for the sequence matrix.

Finish the campaign with the full backend/frontend suites, Ruff, frontend lint,
TypeScript/production build, targeted import/reference checks, and populated upgrade
tests. Use browser verification for materially changed interactions if needed, with
synthetic data and the existing server; do not reload just to inspect edits.

Then perform two different closure reviews: (1) reordered/failing lifecycle sequences,
(2) removal/readability/latency, explicitly asking which new mechanism can be deleted.
Record residual policy boundaries here. Stop when the covered contracts pass and
neither review finds another worthwhile in-scope change. Do not promise zero future
bugs, rewrite harmless code to manufacture completion, or seek an arbitrary line-count
reduction. No material increase in routine user-facing latency is anticipated from
this plan; verify that claim with query and interaction checks during implementation.

Update the current architecture/API documentation with the actual owners. Correct
the stale claim that private-note queuing lives in `CandidateNotes.tsx`, the “ID-only”
ranking check description, and SPEC's maintenance ordering (runtime purges before
queuing/retrying). Remove redundant historical commentary in touched code; do not
delete forward-useful reasons for retained guards. Keep this file as the single
implementation checklist and record outcomes here.

## Suggested commit sequence and model handoff

Use cohesive commits within one authorized campaign; do not mix all six packages into
one large patch. Multiple commits preserve reviewability without requiring another
discovery round from the user.

1. U04 browser ordering and regression: **Sol**.
2. U01 eval reconciliation, metadata, and sequence tests: **Astra** for the state/source
   precedence design and its first implementation; Sol can handle follow-on wiring.
3. U02 coherent ranking contracts and scoped traces: **Sol**, using the explicit
   responsibilities above; escalate if implementation needs a new state model.
4. U03 shared cache lookup and removed redundant reads: **Sol**; preserve thin queries.
5. U05 migration isolation and populated regressions: **Astra** for the historical
   mapping decisions, then Sol for mechanical migration/test work once settled.
6. U06 local restore sanitation/shared erasure: **Astra**, because erasure, credentials,
   schema versions and rollback semantics must remain coherent together.
7. Documentation, full checks and removal review: **Sol**, followed by an **Astra**
   challenge review of the complete resulting diff and sequence coverage.

If minimizing model switches, keep Astra for U01/U05/U06 first, then switch to Sol for
the defined implementation and cleanup, and return to Astra once for closure. Sol is
suitable for most implementation; the remaining uncertain recovery/eval decisions
are the places where stronger reasoning is worth concentrating. This is a task-based
recommendation, not a guarantee about which model will find or prevent a defect.


## Implementation outcomes — 2026-10-06

All six packages are implemented in this campaign:

| Package | Commit | Outcome |
| --- | --- | --- |
| U04 | `68b6644` | Reject older-revision browser writes under the existing consent lock; retain leaving warnings and explicit recovery paths. |
| U05 | `ad71429` | Eliminate live-app imports from migrations. Preserve historical provenance instead of rewriting fingerprints; keep ambiguous multi-opening history unscoped. Freeze evidence identities. |
| U06 | `1c5a88f` | Share aggregate erasure via current-schema cascades. Upgrade candidates, invalidate restored credentials/credential retries, release abandoned work, and reject unversioned snapshots before publication. |
| U03 | `bb4c5bf` | Share cache-key grids, bounded projected lookups, and selected-reference reads; skip admin-only email queue work for members. |
| U01 | `2524ec2` | Derive displayed outcomes from explicit receipts, per-case historical provenance, and independent current metadata. Remove duplicate result/experiment state and reuse fixture loading/error handling. |
| U02 | `6eca0db` | Remove duplicate/unused ranking fields and the unused kept-key helper. Pin admin traces to viewed analyses/openings and accepted snapshots. Reuse dashboard identity observations and reload with one board request. |

The U02 review also covered a newly introduced ordering risk: a dashboard read started beside
board A must not mark a subsequently accepted board B stale. The observation captures its board
context, and a sequence regression covers this. No numeric-ID ordering assumption was added.

Test pruning removed the migration hash-length test, the unused-option navigation test, and
redundant kept-key assertions already covered by actual tier inheritance. Eval hook tests were
rewritten around complete sequences rather than retaining every superseded merge-branch test.
Recovery tests now use the real schema, and applicant fixtures enforce foreign keys like runtime.
The schema declaration file remains large by design; its only U02 edit corrects a trace-route comment.

Through `6eca0db`, relative to `440061a`, runtime code is **293 lines smaller** (528 added,
821 removed); tests are **102 lines larger** (518 added, 416 removed). These numbers include
migrations in runtime and exclude documentation. No dependencies, persistent IDs, new database
columns, global state library, or general workflow framework were added.

Verified implementation checks:

- Backend: **1,081 passed, one Windows/POSIX runtime skip**.
- Frontend: **338 passed across 49 files**; production/type build and ESLint passed.
- Ruff passed across application, migrations, tests and scripts.
- Static Python import check found no cycles. The API map matches OpenAPI methods/paths exactly.
- Same warmed synthetic pool: current=4, board=19, dashboard=21, unchanged cache adoption=19
  SELECTs. Dashboard was 23 before. The board's only duplicate field is now `analysisId`.
  Unchanged query counts are reported honestly; code reuse itself is not a speed measurement.
- Hidden-board focus checks no longer make the extra current-criteria request, and explicit
  board reload no longer waits for a preceding criteria request. Ordinary saves remain responsive.
- No prompt/model judgment changed; verification used synthetic fixtures and mock providers.
  No production operation, real paid run, real email, or local application-database mutation occurred.

The local recovery policy remains bounded: application snapshots require a migration revision,
fresh sign-in follows restoration, ordinary durable mail still uses existing lifecycle checks,
and Fly recovery remains the previously accepted snapshot policy.

### Post-push review

Pending the initial push: review the complete implementation diff, then make separate lifecycle
and simplification/latency passes. Record any valuable omissions and their resolution here before
closing the campaign.
