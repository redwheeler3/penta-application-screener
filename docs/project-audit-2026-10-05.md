# Follow-up project audit — 2026-10-05

**Status: complete after four passes.** Baseline: clean `main` at `deb2ea1`, following the
completed twelve-finding audit. This report recommends work; runtime implementation has not changed.

## Recommendation

I recommend addressing **seven finding groups in five implementation packages**, plus the small
owner-specific cleanup below. Start with applicant restoration: a valid signed-in applicant can
currently be shown a false session-expired page on startup. The other substantial findings concern
cached-result lifetime, zero-cost cache adoption, authority at administrative commit, proposal
acknowledgements, and expiry in opening summaries.

| ID | Priority | Recommendation |
| --- | --- | --- |
| F01 | P1 | Bind applicant restoration follow-ups to the application response that was accepted. |
| F02 | P2 | Make session-mismatch recovery repeatable within a long-lived applicant client. |
| F03 | P1 | Keep a retained consumer's valid cached result when its original producer is purged. |
| F04 | P1 | Allow Screen to adopt cached results when no new model work is needed. |
| F05 | P1 | Recheck administrative authority under the write boundary before shared changes and final decisions. |
| F06 | P2 | Preserve proposal drafts until acknowledgement; persist Add/Remove intent instead of replacing stale lists. |
| F07 | P2 | Respect expiry in opening summaries and batch their selected-household reads. |

P1 here means a normal workflow can be blocked, paid reusable work can disappear, or a permanent
administrative action can commit after authority changes. These are repository-grounded findings,
not claims that an incident occurred in production.

## F01 — Applicant restoration uses the pre-restoration identity for its follow-up

Owners: [applicant persistence](../frontend/src/applicant/useApplicantPersistence.ts:90),
[restore sequence](../frontend/src/applicant/useApplicantPersistence.ts:271),
[pending-copy read](../frontend/src/applicant/useApplicantPersistence.ts:326),
[server identity contract](../backend/app/api/applicant/dependencies.py).

The initial application GET deliberately bootstraps identity. `restoreApplication` reads the
application correctly, dispatches its ID, and then calls `restorePendingCopy`. That follow-up
still closes over the API created when the original render had `applicationId === null`.
It sends `X-Penta-Identity: applicant:none` while the cookie identifies the application just read.
Updating React state does not replace an already-running function's captured client.

A reproduction through the real API factory and request layer captured `applicant:none` after
accepting application 7. A second reproduction enforced the real server comparison and observed
`session_expired` even though that same application remained signed in. This can also miss the
pending-copy decision that the server requires before further saves. Explicit link-target changes
use the same restore sequence, so they need the same ownership fix.

**Recommend:** derive the follow-up client from the accepted response ID and carry it through the
restore sequence. Validate known-target responses as today. Do not wait for a React render or use
whatever identity happens to be live later. Add a thin integration test at the actual request
boundary; the current API-factory mock returns identical mocks for every identity and hid this fault.

**Regressions:** initial existing-session load, guest-link claim, account-switch link, same-account
renewal, pending-copy presence, and a cookie change after the main read but before the follow-up.

**Latency:** no extra request or synchronization is needed. This removes spurious recovery work.

## F02 — Mismatch notification is permanently latched after the first failure

Owners: [identity client](../frontend/src/api/client.ts:29),
[applicant lifecycle recovery](../frontend/src/applicant/useApplicantPersistence.ts),
[email workflow](../frontend/src/applicant/applicantEmailFlow.ts).

`identityClient` sets `mismatchReported` on its first 409 `session_changed` and never resets it.
Applicant APIs are memoized by application ID, so a recovery into the same application keeps that
client. Lifecycle refresh uses a separately constructed client, which does not reset the original.

The direct failure/success/failure reproduction emitted only one mismatch notification. A full
hook/request-layer reproduction then changed the cookie away from the application, recovered the
original application, and changed it again. The first email-change attempt entered
`session_expired`; the second only set an email error while leaving the page in `idle`.
Server identity checks still rejected the action: this is a recovery/affordance problem, not a
confirmed write to the wrong application.

**Recommend:** make mismatch signalling repeatable after recovery. Keep deduplication with the
lifecycle owner while it is already paused, rather than suppressing future events forever in a
request client. Ensure all action paths interpret `session_changed` consistently.

Related latency cleanup: the committee intake refresh interval remains installed while its
workspace is frozen (`CommitteeWorkspace.tsx:239`). Stop those background reads while paused;
they cannot refresh the old identity successfully. Do not automatically cancel already-paid AI
work as an incidental part of this cleanup.

**Regressions:** two mismatch/recovery cycles, email request and cancellation, queued saves,
multiple simultaneous failures, focus recovery, and no recursive mismatch-triggered read loop.

**Latency:** no new model work or ordinary-request serialization; fewer futile paused-page reads.

## F03 — Producer retention controls another application's cached result

Owners: [result ownership](../backend/app/db/models.py:849),
[selected references](../backend/app/db/models.py:888),
[consumption](../backend/app/ai/result_selection.py),
[purge](../backend/app/services/applications/purge.py:89).

`ApplicationAIResult.application_id` identifies the original producer and cascades on producer
deletion. `ApplicationAISelection.result_id` also cascades when that result disappears. A later
application may legitimately reuse that content-addressed result, but its reference does not
protect the result from its producer's retention deadline.

The reproduction used native canonical answers across withdrawal/reapplication. Adult ages
changed between the two submission dates, but screening does not consume adult ages: the two
screening keys were provably equal. The retained consumer selected the producer's result.
Purging the expired producer left the consumer application present but removed its result and
selected reference. A supplemental native/schema-valid run let the real screening helper adopt
that cached result with zero provider calls, then repeated the purge and lost the reference again.

This loses reusable paid output and consumed findings from a still-retained application. It is
also the point where original-producer provenance and data-retention ownership currently disagree.

**Recommend:** decouple result lifetime from the producer alone. Preserve original provenance
and costs; retain valid selected results that a retained consumer still needs; delete output
when no entitled retention owner remains. Design and test the migration before changing the FK.
Do not copy output into duplicate billed-result rows, salt cache keys with new application IDs,
or retain every orphaned result indefinitely.

**Regressions:** one/multiple consumers, producer-first and consumer-first purge, different
retention deadlines, replaced/stale selected references, score and screening kinds, restore,
original provenance, result IDs, and unchanged cost history.

**Latency:** primarily a schema/lifecycle correction. It avoids repeat model calls after purge;
ordinary saves must not wait for model work or a full-table cache sweep.

## F04 — Valid cached screening cannot be adopted as zero-cost work

Owners: [Screen no-op guard](../backend/app/api/screening.py:139),
[estimate/cache reuse](../backend/app/ai/analysis.py),
[dashboard](../backend/app/api/dashboard.py),
[confirmation](../frontend/src/components/workflow/WorkflowBar.tsx).

Cache presence and consumed-reference presence are different. A withdrawal/reapplication can
have a valid cache key but no `ApplicationAISelection` for its new ID. The existing screening
helper can attach reused results, but the endpoint refuses to invoke it when `to_analyze == 0`.
The confirmation also offers only Close for that estimate.

The actual HTTP reproduction returned one cached result and zero missing model calls, while
the dashboard said `screened: false`. Starting Screen returned 409 `unchanged_pool`, left the
consumer unselected, and made no provider call. Rank is then disabled for this one-app pool.
The failure repeats with a validated `ScreeningReport`. Score-current already distinguishes
`cachedToRefresh`; that is the useful sibling pattern.

**Recommend:** distinguish model misses from cached results that still need to be applied.
Expose a zero-cost reuse operation, validate current input/lifecycle at commit, attach the
references, and refresh derived views. Keep the true no-op guard when both kinds of work are empty.

**Regressions:** all-cached new consumer, stale/missing selected reference, mixed fresh/cached
pool, input change before commit, withdrawn/selected/expired target, zero provider calls and cost,
and restored dashboard/Rank readiness.

**Latency:** a short persistence operation replaces an unnecessary analysis or blocked workflow.
No new input identifier is needed: cache key, application ID and selected reference already exist.

## F05 — Administrative admission is not rechecked at shared-write commit

Owners: [shared settings](../backend/app/api/settings.py:78),
[committee-default rules](../backend/app/api/settings.py:175),
[opening decisions](../backend/app/api/openings.py:281),
[selection service](../backend/app/services/openings/selection.py:95),
[existing guarded pattern](../backend/app/services/auth/allowlist.py).

`require_admin` checks authority when the dependency resolves. Shared settings/default-rule
writers and permanent opening decisions then use the admitted actor without a fresh authority
check under their writer boundary. Allowlist mutations already do the latter.

Two request-session reproductions loaded an admin actor, committed its demotion in another
session, and then continued the admitted operation. One committed shared rules; the other
confirmed a permanent selected-household decision. The tests reproduce the gap between
admission and mutation; they do not claim that a newly admitted member can call an admin endpoint.

**Recommend:** extend the existing locked-admin pattern to administrative mutations. Recheck
active authority after acquiring the relevant write boundary and before making permanent changes
or staging side effects. Review shared settings, default rules, publication/update/direct fill,
selection/no-selection and admin mutation endpoints together. Avoid a blanket lock around reads,
provider I/O, or every ordinary member action.

**Regressions:** demotion/deactivation after admission, actor changed while waiting for a writer,
allowed unchanged actor, existing idempotent retries, no partial decision or queued notice,
and preserved application/opening lock ordering.

**Latency:** an authoritative DB recheck in an existing write transaction; no network/provider wait.

## F06 — Proposal handling loses rejected drafts and concurrent Add intent

Owners: [composer](../frontend/src/components/ranking/RankingView.tsx:55),
[proposal queue](../frontend/src/hooks/useRanking.ts:265),
[endpoint](../backend/app/api/ranking/shortlist.py),
[member state](../backend/app/services/ranking/member_state.py:143).

There are two related failures:

1. `submitDraft` calls a void callback and clears the input immediately. A rejected save removes
   its optimistic chip after the board reload. The rendered request-layer reproduction entered
   a criterion, received `run_in_progress`, and ended with neither the text nor its chip present.
2. The UI offers individual Add/Remove operations, but the API persists a complete array captured
   by that tab. Two tabs starting from `[Existing]` can both get successful saves while the second
   list `[Existing, Second]` removes the first tab's acknowledged addition.

The per-field writer lock preserves unrelated tier/flag fields but cannot infer Add intent from
an old complete list. The current same-tab queue likewise cannot protect another tab.

**Recommend:** return an acknowledged outcome to the composer and retain text on failure, clearing
only the exact submitted draft on success. Persist narrow Add/Remove intent under the existing
run/member-state guards. Use the existing deduplicated proposal text; do not mint proposal IDs or
introduce a generic merge engine. Keep rejection of edits during a live full Rank, because its
inputs have already been captured.

**Regressions:** rejection/offline save, edits typed during acknowledgement, duplicate Add, two-tab
Add/Add and Add/Remove, stale analysis, live run, independent tier/flag writes, and account change.

**Latency:** retain optimistic feedback and short ordered writes; no model wait or full-page blocking.

## F07 — Opening summaries bypass expiry and perform one selection query per row

Owners: [opening summary](../backend/app/api/openings.py:84),
[opening selection response](../backend/app/api/openings.py),
[catalog read](../backend/app/services/openings/catalog.py),
[retention predicate](../backend/app/services/applications/retention.py).

The retained-detail endpoint now respects the first unavailable Pacific date, but opening
summaries load the selected `Application` directly and return its name/ID without that predicate.
A selected fixture at its retention boundary still appeared by name in the opening list before
physical purge. This is an administrative metadata surface, not public exposure.

The same owner issues a selected-participation query for every opening, and loads a full
application blob just to obtain a selected name. Instrumentation on 100 synthetic archived
openings with no selected household measured **101 SELECTs**. There is no production timing claim.

**Recommend:** batch selected-household metadata with the opening read, selecting only needed
columns and applying current retention. Preserve non-identifying permanent decision facts when
household data is unavailable. Apply the same boundary to the selection/detail summary response.
Avoid introducing an opening cache or another background sweep.

**Regressions:** selected expiry before purge, future/indefinite retention, already-purged household,
no-household decision, ordinary active candidates, and bounded query counts across large archives.

**Latency:** fewer queries and no unnecessary applicant JSON loads; no additional model work.

## Worthwhile cleanup to include with those owners

- **Make protected request ownership explicit in tests and APIs (F01/F02).** Protected modules
  export both a client factory and default unbound functions; `useCommitteeApi` silently returns
  those defaults outside a provider. The browser guard fails closed, but isolated tests use that
  fallback and miss real binding. Prefer a required protected client/context, with deliberate
  public/bootstrap calls and explicit manual harness construction. Keep state/math unit tests;
  add a small set of real-factory/request-boundary tests rather than rewriting all tests.
- **Correct stale documentation/comments.** SPEC still says “R06 cache repair pending” at its
  age invariant and describes override staleness by timestamps; runtime uses reason-code/flag-category
  fingerprints. The Screen guard's “nothing uncached means identical output/no-op” comment misses
  selected-reference adoption, and refers to a Rank no-op gate although full Rank is intentionally
  allowed. Correct these descriptions with their fixes, not another wholesale SPEC rewrite.
- **Capture metadata is useful, even where not rendered.** Discovery/consolidation configuration
  is available in audit endpoints but not displayed by the current frontend traces. A compact
  “configuration used” detail could help operators. This is optional presentation, not a missing
  persisted record or a reason to remove the capture.

## Approved policy: older consumed findings after resubmission

Keep the last consumed findings active until the committee explicitly runs Screen again.
The amber workflow indicator is the freshness signal; do not add applicant-level labels,
identify which applicant triggered staleness, or introduce additional input metadata for display.
Preserve history and human overrides, keep ages frozen at submission time, and do not automatically
rerun AI. This is intentional eventual consistency, separate from F03/F04.

## Implementation packages

1. **Applicant identity/recovery:** F01/F02, real-factory boundary tests, paused-page read suppression,
   and proportional API ownership cleanup.
2. **Cached-result applicability and lifetime:** F03/F04, migration/provenance verification and
   zero-cost screening adoption, preserving the approved amber-only freshness policy.
3. **Administrative commit authority:** F05 across shared/admin mutations, using the existing guard.
4. **Proposal intent and acknowledgement:** F06 frontend recovery plus narrow server operations.
5. **Opening summaries:** F07 expiry semantics and the measured query cleanup in one owner.

Documentation corrections accompany these packages. The cache-lifetime package deserves the
most design/verification care; the applicant startup fix should land first. Multiple cohesive
commits make this reviewable without another sequence of small suggestion rounds.

## Passes, coverage and rejected threads

1. **Request/session pass:** read bootstrap, credential exchange, captured clients, mismatch
   signalling and recovery. Reproduced F01/F02 through real API factories and mocked HTTP responses.
2. **Persistence/cache pass:** followed references through reuse/purge, no-work Screen gating,
   role changes and permanent decisions. Used real SQLAlchemy/FK behavior and the real HTTP guard.
3. **Intent/maintainability pass:** followed proposal failures and multi-tab payloads; measured
   opening reads; checked expiry metadata, owner sizes, substantial exact duplicates and imports.
4. **Consolidation pass:** checked sibling safeguards, rejected overbroad fixes, repeated both cache
   failures with schema-validated screening output, removed probes and verified the unchanged baseline.

The tracked inventory contains **200 Python app/scripts** and **131 non-test frontend TS/TSX files**.
Reference/graph scans cover that inventory; manual review concentrates on these full workflows
and the recent fixes. The largest owners remain ORM models (1,127 lines), applicant persistence
(668), AI engine (570), committee workspace (540), email outbox (534), dimension scoring (527),
and ranking pipeline/TierList (525 each). File size alone does not establish a needed split.

I would leave these alone:

- Submission-time ages, positive-weight/unranked behavior, frozen dimension definitions,
  captured identity headers, narrow receipts, provider-neutral cache identities, result IDs/costs,
  lease fencing, explicit AI confirmation, and existing short write guards.
- Tier/proposal rejection during full Rank: the shared run lock already closes the hypothesized
  mid-run proposal-loss path. F06 repairs the rejected draft, not that guard.
- Per-input caches and semantic fingerprints: do not salt them with dates/new applicant IDs merely
  to repair missing reference adoption. Score-current already has `cachedToRefresh` handling.
- Imported-answer readers and manual diagnostic entrypoints. Stored records/tests still use them.
- The cohesive ORM registry, a wholesale router/service split, a new global state machine,
  generic caching/merge infrastructure, formatting churn, or a strict-typing sweep.
- Apparent frontend runtime orphans: the reachability exclusions are type/declaration files and
  test setup/support. No proven unused application module or substantial exact duplicate Python
  function body emerged. These checks do not establish that every possible duplicate is absent.

## Verification and limits

- **13 distinct temporary synthetic probes passed:** five frontend and eight backend, including
  the stale-output characterization and opening query-count measurement. Two cache cases were
  additionally repeated with validated `ScreeningReport` data; the native lifetime case also used
  the real cache-consumption helper. Harness errors were corrected
  before accepting evidence; probes assert current faults and are not fix regressions.
- Probes and temporary inventory scripts were removed. Runtime/source tests remain unchanged.
- Full baseline: **932 backend tests passed**, one existing POSIX-only skip; Ruff passed.
  **272 frontend tests passed**; ESLint, TypeScript and production build passed.
- Python import graph has no cycles, including deferred imports. Frontend runtime reachability
  produced only the expected type/declaration and test-harness exclusions described above.
- Checked build/cache directories retain inherited ACLs. The established pytest-temp exception
  was not altered. No dev server was started or page reloaded.
- No production inspection/deployment, local application DB modification, real model call or
  outbound email was needed. Findings use synthetic data, source evidence and real local plumbing.
- This is not an assertion of exhaustive bug absence or production latency. Query counts and
  control-flow reproductions are evidence; implementation still needs regressions that prove fixes.

## Implementation progress

- F01/F02: restored-app follow-ups use the accepted identity immediately; mismatch events remain
  repeatable and the lifecycle owner deduplicates an already-paused session. Committee intake
  polling pauses with the workspace. Real request-boundary regressions cover startup, a linked
  account switch, and two mismatch/recovery cycles. Frontend build, lint and all 275 tests passed.

- F03/F04: producer provenance is independent of lifetime; retained selected consumers protect
  shared output. Purge/replacement prune affected unowned results, and restore migrates before
  deletion replay. Screen estimates distinguish cached work needing adoption and allow explicit
  zero-cost application. Regression coverage includes deletion order, multiple consumers,
  replaced references, historical-snapshot restore, and an actual HTTP zero-provider run.

- F05: one administrative write-authority owner now rechecks active admin status under the
  existing SQLite writer boundary. Shared AI settings, committee-default rules, allowlist,
  opening creation/update/permanent decisions, feedback administration and vacancy support
  writes use it. Two-session tests demote or deactivate admitted actors before mutation and
  verify no partial decision or queued notice. All 954 backend tests passed (one existing skip);
  Ruff passed. Ordinary reads and provider I/O remain outside this boundary.

- F06: proposal writes apply narrow Add/Remove intent to the locked current state; the full-list
  replacement endpoint is removed. The composer waits for acknowledgement and retains rejected
  or newer draft text. Cross-tab Add/Add and Add/Remove, duplicate intent, failed acknowledgement
  and typing during a save are covered. All 956 backend and 279 frontend tests passed, with Ruff,
  ESLint and build passing. Existing run guards and optimistic chip feedback are preserved.
