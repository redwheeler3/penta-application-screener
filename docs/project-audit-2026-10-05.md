# Comprehensive project audit — 2026-10-05

## Recommendation

I recommend addressing **seven confirmed findings in five work packages**, ordered below.
The highest priorities are binding actions to the page's intended identity, enforcing expiry
independently of background purge, and reconciling saves with overlapping detail reads.
There is also an AI age-snapshot consistency gap, a ranking navigation race, unnecessary
maintenance writes, and a selected-household editor mismatch.

This is an audit and recommendation phase. Runtime code remains unchanged. The previous
implementation was pushed successfully: `origin/main` advanced from `75e0032` to
`0d1ccf8`. This document replaces the completed audit from October 4.

Reviewed baseline: clean `main` at `0d1ccf8`. The recent fixes are incorporated into this
review, rather than treated as untouchable. R01 and R02 identify composition gaps in those
recent changes. Their intended ownership boundaries remain useful.

## Findings at a glance

| ID | Priority | Finding | Evidence |
| --- | --- | --- | --- |
| R05 | First | A stale tab can act on a replacement session's account or application | Real-authentication HTTP fixtures plus the session hook |
| R03 | First | Expiry is not consistently enforced before reads, authentication, selection, and email work | Four isolated retention/maintenance reproductions |
| R01 | First | A delayed detail read can overwrite a newer acknowledged save | Two actual navigation/note interaction reproductions |
| R06 | Next, preserve caches | Identical-answer resubmissions recompute age evidence while cached evaluations retain an earlier snapshot | Changed age input with unchanged source/cache identity |
| R02 | Next | A superseded ranking read can redirect away from a successfully loaded board | Actual ranking and navigation hooks |
| R04 | With R03 | A no-work closeout sweep takes a write lock and commits for every applicant | Instrumented SQL/commit counts |
| R07 | With R01 | Selected-household notes look editable but the server rejects their saves | Actual detail component and HTTP boundary |

### R05 — Bind requests to the identity their originating page expects

Owners: [committee session](../frontend/src/hooks/useSession.ts),
[applicant lifecycle](../frontend/src/applicant/useApplicantPersistence.ts),
[HTTP client](../frontend/src/api/client.ts),
[committee authentication](../backend/app/api/dependencies.py),
[applicant authentication](../backend/app/api/applicant/dependencies.py), and authenticated actions.

Browser cookies are shared between tabs on the same host. A successful account switch in one tab
changes the credential used by another tab's next request. The existing account-keyed workspace
and request generations protect transitions observed by that React tree; they cannot establish
which identity a changed HTTP cookie will resolve to.

The committee session hook loads identity initially and has no focus/visibility/session-change
revalidation. An isolated hook reproduction changed the next auth response from member A to B,
then dispatched focus and visibility events. The visible user remained A, with only the original
auth request made.

Two HTTP reproductions used real authentication dependencies and synthetic sessions:

1. Read committee identity A, replace the request cookie with identity B, and send the private-note
   request that an older A page sends. It succeeds and creates a note owned by B.
2. Read applicant A, replace the applicant cookie with B, and send the current bodyless
   `POST /applicant/application/withdraw`. It succeeds and withdraws B; A remains active.

Both identities are legitimately authenticated. The missing contract is the page's intended
identity. Applicant visibility refresh also compares working revisions without comparing the
returned application ID (lines 510–536). Revisions are per application: equal revisions do not
establish that two responses describe the same household. Email matching on ordinary applicant
saves does not protect the bodyless withdrawal action.

**Recommendation:** bind account/application-owned requests to the existing user or application
ID captured by their page and enforce that expectation on the server before using the credential
for an action. Apply the boundary consistently to authenticated reads, writes, destructive
actions, logout, and paid work; keep bootstrap/public/session-switch routes deliberately defined.
Use a captured request context rather than a mutable global identity that old callbacks could
silently inherit. Add cross-tab notification and/or revalidation for prompt UI recovery, and check
application IDs before merging lifecycle responses.

Keep the existing account teardown guards. On identity mismatch, stop work and dispose or freeze
the stale workspace; never transfer its private data or queued actions to the replacement account.

**Regression coverage:** delayed note debounce, queued and in-flight writes, same-origin tab
switch/sign-out, focus while revalidation is pending, equal revisions across different
applications, withdrawal/discard/email-change actions, and manual API requests.

**Latency:** comparing the expected ID with the already-authenticated identity needs no additional
database lookup or provider call. Client recovery can be asynchronous; server fencing must be
effective even before a focus refresh finishes.

### R03 — Enforce retention expiry independently of physical purge

Owners: [application scope](../backend/app/services/applications/scope.py),
[applicant authentication](../backend/app/services/auth/applicant.py),
[link access](../backend/app/services/applications/access.py),
[retained reads](../backend/app/api/applications/routes.py),
[direct selection](../backend/app/services/openings/direct_selection.py),
[notifications](../backend/app/services/openings/notifications.py),
[outbox](../backend/app/services/email/outbox.py), and
[maintenance](../backend/app/services/maintenance.py).

Expiry checks differ between these owners:

- Applicant authentication rejects missing, withdrawn, or selected applications, but not expired
  applications. A session issued before expiry still authenticated after the one-year purge date.
- The selected-household branch of the retained administrator read has no retention-date check.
  A synthetic selected household past its seven-year purge date returned HTTP 200.
- Ordinary committee scope and direct selection use `retention_due_on >= today`, while purge uses
  `retention_due_on <= today`. The same due-day record was readable/selectable and purgeable.
- Maintenance queues closeout notices and drains the outbox before purging. A synthetic expired,
  unsuccessful household received a captured outcome email and was then deleted in the same pass.
  No real email was sent.

This makes expiry depend on when the background job reaches physical deletion. A slow retry batch,
maintenance failure, or first request after inactivity can leave expired data usable beforehand.

**Recommendation:** give retention one explicit availability contract, used by both SQL readers
and application/auth/action checks. Reject expired records before returning or mutating them,
resolving links, selecting a household, or preparing email. Handle an expired identity encountered
during guest/reapplication flows deliberately so old data cannot be revived merely because purge
has not run. Perform expiry cleanup before outbound work, with send-time eligibility rechecks.

Use the existing purge boundary: the Pacific purge date is the first unavailable day. Preserve
the concurrency guarantees that recheck retention under the writer lock; an extension completed
while the record was still available must survive a later sweep.

There is an existing due-day selection/purge regression
(`test_selection_after_sweep_read_preserves_new_retention`) that allows selection on the purge
date. Reconcile it with the chosen boundary explicitly, rather than silently changing its
meaning. Preserve the race test with a record whose original retention is still valid, and add
the due-day rejection case.

**Regression coverage:** before/on/after expiry for applicant sessions and links, ordinary and
retained committee reads, direct selection, pending copies, reapplication, queued notices, and
a delayed maintenance pass. Include concurrent extension/withdrawal/selection and multi-opening
retention. Keep separate one-year and seven-year fixtures.

**Latency:** date checks can use existing loaded records/query predicates. They need no provider
wait or global transaction around network work. Purging before retries also removes obsolete work.

### R01 — Reconcile acknowledged saves with overlapping reads of the same applicant

Owners: [navigation](../frontend/src/hooks/useNavigation.ts),
[private drafts](../frontend/src/hooks/usePrivateNotes.ts), and
[candidate acknowledgements](../frontend/src/CommitteeWorkspace.tsx).

The recent change correctly separates navigation from narrow save acknowledgements, so an old
applicant's save cannot cancel a request for another applicant. However, detail loading clears
the selected application immediately (navigation line 82), and acknowledgements only patch an
already selected application (lines 199–201).

A reproduction through the real note editor, writer, and navigation hook:

1. Open applicant 7 with note `Original`; edit and send `Confirmed new text`.
2. Leave the editor, then start reopening the same applicant before its save completes.
3. Complete the save. There is no selected detail to patch, and the unobserved confirmed draft
   is released.
4. Return the older detail response captured before the save. The reopened editor displays
   `Original`; another edit submits that obsolete text as its new baseline.

A second reproduction acknowledged an eligibility override while the same applicant's detail
was loading. The late response displayed the old status.

The note is initially saved correctly on the server. The risk is that the stale editable display
then causes the member to overwrite it.

**Recommendation:** reconcile narrow receipts with in-flight reads for the same applicant and,
where applicable, opening. A read begun before an acknowledgement must not roll back that
acknowledged field. Retain only the receipts needed by outstanding reads, or supersede/refetch
the matching read. Preserve newer unsent drafts and release confirmed draft state once the
overlap has settled.

Keep unrelated-applicant navigation independent. Reintroducing blanket navigation invalidation
would restore the earlier cancellation bug. Reuse the existing applicant/opening identity and
request scope; a global cache or general state framework is unnecessary.

**Regression coverage:** save before/during/after reopening, Back/Forward, different applicants,
different openings, private notes and narrow status/favourite/shortlist/committee updates,
failed saves, and new edits during an acknowledgement.

**Latency:** receipt reconciliation adds no network wait to ordinary navigation. If a matching
read is restarted, describe and measure that extra read rather than blocking all navigation on saves.

### R06 — Stabilize age evidence without birthday-driven cache misses

Owners: [intake normalization](../backend/app/services/applications/intake.py),
[AI evidence](../backend/app/ai/applicant_facts.py),
[cache identity](../backend/app/ai/analysis.py),
[scoring plans](../backend/app/ai/dimension_scoring.py), and
[ranking freshness](../backend/app/services/ranking/freshness.py).

Intake hashes the stored canonical answers, then separately normalizes them using the submission
date (lines 119–124). Normalized fields include ages. Discovery/scoring consume those normalized
facts, and screening consumes normalized child details. The cache identity uses `raw_row_hash`;
the pool freshness fingerprint also hashes source rows without their normalized evidence.

An isolated scoring-plan reproduction used identical canonical answers normalized on May 31
and June 1. A child's age changed from 10 to 11. The actual scoring prompt changed, but:

- the per-dimension cache key stayed identical;
- the ranking-input fingerprint stayed identical;
- the scoring plan scheduled zero fresh applicants and reused the cached rationale
  `Child is 10`.

This verifies cache plumbing and stale evidence; it does not make a claim about how a live model
would score the newer input. Identical-answer resubmission across a birthday is a real path
through the current normalizer. Changes to consumed normalization code have the same exposure.

**User decision — 2026-10-05:** avoid a cache miss from this birthday issue. This replaces the
initial proposal to add normalized ages to the cache identity. No runtime change is implemented yet.

**Revised recommendation:** preserve the current source-content cache keys and existing results.
Stabilize AI age evidence for identical submitted content instead of allowing a later receipt date
to manufacture a different model input. A birthday, passage of time, or identical-answer
resubmission must not invalidate cached AI work. Returning to previously submitted content also
needs a consistent snapshot rather than a newly calculated age attached to an older cache entry.

Use the existing submission/version history to establish the age reference where its provenance
is known. Keep cached evaluations tied to the snapshot they actually analyzed; do not rewrite
their evidence or claim that a newly calculated age was used by an older evaluation. Make age
reference dates clear in the model evidence and its presentation. The exact snapshot/reference
handling must be settled before runtime implementation.

Deterministic eligibility currently evaluates ages at the latest submission date. Do not silently
freeze eligibility to an older age merely to preserve AI caching: its date policy must remain
explicit, with any intended change agreed separately. Preserve equivalent-provider cache reuse,
matched dimension identities, prior result provenance, and returned-usage accounting. Other
evidence-changing normalization corrections need separate review; this birthday repair does not
authorize a blanket cache-key change.

**Regression coverage:** unchanged answers across adult/child birthdays and repeated submissions;
reverting to earlier content; cached evaluation provenance versus displayed/eligibility ages;
genuinely changed answers; equivalent provider routes; partial scoring reuse; and concurrent
resubmission. Assert stable cache keys, cache hits, and zero fresh model calls for the birthday cases.

**Cost/latency constraint:** no birthday-driven miss, bulk cache invalidation, or automatic AI run.
Genuine answer, model, or prompt changes retain their existing invalidation behavior. Verify cache
preservation during implementation rather than relying only on a date-free cache key.

### R02 — Distinguish absent criteria from a failed or superseded read

Owners: [ranking state](../frontend/src/hooks/useRanking.ts),
[opening refresh](../frontend/src/CommitteeWorkspace.tsx), and
[navigation](../frontend/src/hooks/useNavigation.ts).

`refreshRankingRun` returns `null` for genuine absence, stale/superseded reads, and failures.
The workspace reduces all of these to `run !== null` and calls
`onOpeningRankingLoaded`, which can navigate to Applications.

A reproduction started a current-analysis read, loaded a valid ranking board, then completed the
superseded read. The ranking hook returned `null`; the real workspace-style callback redirected
the ready Ranking view to Applications. Transient failures can produce the same false absence.

**Recommendation:** give the refresh result an explicit outcome and redirect only after a current,
successful read confirms absence. Superseded reads do nothing; failures preserve the user's view
and provide the appropriate recovery state. Keep the live-location checks introduced last round.

**Regression coverage:** ready board versus old refresh, network failure, confirmed absence,
opening changes, history restoration, and navigation to another tab while refresh is pending.

**Latency:** no additional request or serialization is required.

### R04 — Skip closeout write locks for applicants with no notice owed

Owner: [closeout notifications](../backend/app/services/openings/notifications.py),
especially `queue_due_unsuccessful_notices` and `_due_unsuccessful_notices`.

The default maintenance path first selects every submitted, non-withdrawn application. It then
takes an application write lock, reloads notice eligibility, and commits once per applicant,
including active applicants whose openings are not final and who have no notice owed.

An isolated SQL/commit counter, attached after fixture setup, measured:

| Active applicants | Notices queued | SELECTs | UPDATEs | Commits |
| --- | --- | --- | --- | --- |
| 1 | 0 | 4 | 1 | 1 |
| 100 | 0 | 301 | 100 | 100 |

These are operation counts, not production wall-clock measurements. The unnecessary updates
compete for SQLite's single writer and add work as the pool grows.

**Recommendation:** identify plausible due, unnotified, unexpired recipients in a batch read;
take the existing short writer locks and recheck eligibility only for those candidates.
Keep notice identity/idempotency, concurrency revalidation, and the separate provider wait.
Ensure any preselection cannot leave cached ORM lifecycle facts masquerading as a fresh recheck.

**Regression coverage:** large zero-work pools, genuinely due notices, concurrent decisions/
withdrawals/expiry, existing deliveries, and bounded query/write counts. Implement alongside R03.

### R07 — Make selected-household note controls reflect server actionability

Owners: [candidate detail](../frontend/src/components/applications/CandidateDetail.tsx),
[note editor](../frontend/src/components/applications/CandidateNotes.tsx), and
[candidate mutation boundary](../backend/app/api/applications/routes.py).

Ordinary review deliberately keeps selected households visible. Read-only mode is currently
controlled by the retained-review navigation path, so the ordinary selected-household view still
passes an editable note controller and exposes note composition.

The actual detail component accepted a private-note edit with `app.selected = true`.
A separate HTTP fixture verified that the same selected household could be read normally
(HTTP 200, `selected: true`) but its private-note save returned HTTP 404. Note mutations use
`_lock_mutable_application_or_404`, whose AI-actionable pool excludes selected households.

**Recommendation:** align note affordances with the existing server policy while keeping the
notes, statuses, scores, and printing fully reviewable. Handle a selection arriving during an
unsaved note explicitly: retain the draft and give the member a clear way to resolve/discard it,
rather than presenting a Retry save that can never succeed.

If post-selection annotations are desired, that is an explicit policy change to the note
endpoint's actionability, rather than a reason to broaden the AI-actionable pool. My default
recommendation is to preserve the server's current restriction and make the UI truthful.

**Regression coverage:** ordinary selected review, retained review, private/shared note actions,
selection during debounce/save, a retained failed draft, and display/print parity.

**Latency:** reading the existing selection/actionability flags does not add a round trip.

## Implementation packages and decisions

1. **Identity-bound requests (R05).** Cover both browser surfaces, shared-cookie transitions,
   server checks, and recovery. Do not stop at a focus-only fix.
2. **Save/read reconciliation and note actionability (R01/R07).** Keep the responsive, account-owned
   note writer; reconcile overlapping receipts and give blocked drafts a truthful resolution.
3. **Retention availability and selective maintenance (R03/R04).** Establish the date boundary
   across all access/action/email paths, then remove the measured no-work writes.
4. **Explicit ranking read outcomes (R02).** Preserve live navigation ownership without treating
   cancellation or failure as absence.
5. **Stable AI age snapshots (R06).** Preserve existing cache keys/results, settle explicit age
   reference handling, and fix identical-content resubmission without birthday-driven misses.

Default policy recommendations: expiry begins on the existing Pacific purge date; selected
households remain reviewable but follow the current note-write restriction. Call out departures
from those defaults as product choices. R06 must follow the user's cache-preservation decision;
the initial broad cache-invalidation proposal is superseded.

Small documentation corrections should accompany their owners: the architecture map still
attributes private-note writes to the opening-scoped candidate-actions hook; the ranking score
assembler's docstring names the screening router for the shortlist; the fact-view comments
overstate identifier exclusion because canonical child details also contain names/birth dates.
SPEC explicitly permits full application context in AI input. Correct the description; do not
invent a new redaction policy or change model inputs as an incidental cleanup.

## Coverage, verification, and work to leave alone

The tracked-source inventory covered **199 Python modules/scripts** (189 app modules plus ten
diagnostics), **128 non-test frontend TypeScript files** including one compiler declaration,
and three watchdog source files. Reference checks covered all tracked source; manual reads
concentrated on complete flows and their ownership/transaction boundaries.

| Area | Review and result |
| --- | --- |
| Frontend | Authentication, cookie/React ownership, application/opening selection, history, private/shared notes, candidate acknowledgements, settings/rules, publication/direct selection, applicant saves/withdrawal/visibility refresh, eval history, AI streams and cancellation |
| Backend | Auth/session/link admission, applicant identity/revision locks, intake/normalization, committee scope/mutations, retention/purge/restore, opening decisions and notifications, outbox claims/provider waits, AI planning/cache/selection/freshness/leases/spend |
| Readability/dead code | Python declaration references and nontrivial exact duplicate bodies; TypeScript runtime reachability; dynamic CSS references; largest ownership boundaries; API/doc consistency |
| Tooling/ops | Local setup/dev/recovery wrappers and diagnostic entrypoints; watchdog lookup retry, restart outcome, polling/alert lifetime and suspension policy |

Fresh baseline checks passed: **897 backend tests**, one POSIX-only test skipped, and Ruff;
**258 frontend tests**, ESLint, TypeScript and production build; **9 watchdog tests** and typecheck.
The generated API map matches all **111** documented method/path pairs.
Python import graph: no cycles, including deferred imports. Frontend import/dynamic-import
reachability left only `vite-env.d.ts` outside the application graph.

**Thirteen temporary reproductions** (eight backend, five frontend) verified the current faults
above and were removed. They asserted existing faulty outcomes to establish evidence; they are
not committed regressions proving fixes. SQL/commit instrumentation was separate and also
temporary. New implementation regressions must invert these expectations at the owning boundary.

I do **not** recommend:

- another broad service/module restructuring, global state machine, cache framework, formatter
  rewrite, strict-typing sweep, or speculative dependency migration;
- splitting the cohesive ORM registry merely because it exceeds the file-size guideline;
- removing imported-answer support: stored records still depend on it;
- deleting `ensure_lock_row` or `FlyWatchdog` based on simple reference counts: schema-only tests
  use the former, and deployment binds the latter;
- removing CSS candidates that are generated dynamically from roles, phases, columns, bands,
  saved views, or chip badges; the reviewed apparent misses all have real generators;
- undoing zero-weight/unranked behavior, complete chosen-score ranking, narrow acknowledgements,
  ordered writes, captured drafts, lease fencing, stream cancellation, coherent board snapshots,
  stable record identities, or returned-usage accounting.

No further substantial exact duplicate Python function bodies or proven unused frontend modules
emerged. Source inventory and focused workflow review do not establish that every line received
equal manual scrutiny or that every possible defect has been found.

No production VM/database inspection, deployment, schema migration/reset/restore, real model call,
or real outbound email was performed. Git publication and the requested audit document are the
durable changes in this phase.
