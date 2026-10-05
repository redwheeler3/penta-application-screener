# Comprehensive project audit — 2026-10-05

## Recommendation

I recommend addressing **twelve confirmed findings in six work packages**, ordered below.
The highest priorities are binding actions to the page's intended identity, enforcing expiry
independently of background purge, and reconciling saves with overlapping detail reads.
There is also an AI age-snapshot consistency gap, a ranking navigation race, unnecessary
maintenance writes, and a selected-household editor mismatch. Three follow-up passes added
late cookie-response interference, removed-member influence, omitted rank configuration,
a guest-copy/selection race, and lost personal priorities during shared consolidation.

This is an audit and recommendation phase. Runtime code remains unchanged. The previous
implementation was pushed successfully: `origin/main` advanced from `75e0032` to
`0d1ccf8`. This document replaces the completed audit from October 4.

Reviewed baseline: clean `main` at `0d1ccf8`. The recent fixes are incorporated into this
review, rather than treated as untouchable. R01 and R02 identify composition gaps in those
recent changes. Their intended ownership boundaries remain useful.

The extension below reviewed clean `main` at `32eded2`. Commits since `0d1ccf8` changed
documentation only, including the confirmed submission-time age policy. The three extra passes
and nine new isolated reproductions did not modify runtime code or call production/providers.

## Findings at a glance

| ID | Priority | Finding | Evidence |
| --- | --- | --- | --- |
| R05 | First | A stale tab can act on a replacement session's account or application | Real-authentication HTTP fixtures plus the session hook |
| R03 | First | Expiry is not consistently enforced before reads, authentication, selection, and email work | Four isolated retention/maintenance reproductions |
| R01 | First | A delayed detail read can overwrite a newer acknowledged save | Two actual navigation/note interaction reproductions |
| R06 | Next, preserve valid caches | Resubmissions can change age evidence without invalidating affected cached evaluations | Changed age input with unchanged source/cache identity |
| R02 | Next | A superseded ranking read can redirect away from a successfully loaded board | Actual ranking and navigation hooks |
| R04 | With R03 | A no-work closeout sweep takes a write lock and commits for every applicant | Instrumented SQL/commit counts |
| R07 | With R01 | Selected-household notes look editable but the server rejects their saves | Actual detail component and HTTP boundary |
| R08 | With R05 | A late expired-session response can erase a newer login cookie | Controlled response ordering with real auth and a cookie jar |
| R09 | First, with R05 | Removed members still influence shared AI pools, kept axes, and proposals | Actual access removal followed by shared-input queries |
| R10 | With R06 | Result-affecting fan-out and consolidation settings are omitted from currentness | Fingerprint/currentness tests and changed pair nomination |
| R11 | With lifecycle guards | Guest pre-review can recreate a private copy/access link after selection | Separate request sessions with selection at the copy boundary |
| R12 | First | Consolidation can erase another member's working priority | Both early and late materialization of that member's view |

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

### R06 — Keep submission-time ages and invalidate only changed evidence

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

**Confirmed policy — 2026-10-05:** calculate ages at submission time. A submission that is simply
sitting there keeps its calculated ages and remains cacheable across birthdays. An explicit
resubmission recalculates ages; if evidence consumed by a pass changes, an affected cache miss is
acceptable and supplies the more accurate submission-time age. This supersedes the earlier
overbroad prohibition on misses after identical-answer resubmission. Runtime repair is pending.

**Recommendation:** retain the latest-submission age reference used by intake and deterministic
eligibility. Fingerprint the actual submitted evidence consumed by each AI pass, including its
relevant normalized values, so cached evaluations match that evidence. Keep `raw_row_hash`
truthful to its raw-source meaning. Share evidence builders with prompt construction to prevent
the input and cache contracts from drifting.

Do not put the current date, submission timestamp, or version ID alone in the cache key. A newer
submission receipt with unchanged answers and unchanged calculated evidence remains a hit.
Reverting to earlier answers still requires comparing the newly submitted evidence with the
earlier evaluation, rather than assuming the raw-answer hash proves age equality.

Keep prior evaluations tied to the snapshots they analyzed. Preserve equivalent-provider reuse,
matched dimension identities, prior result provenance, and returned-usage accounting. Apply the
same evidence contract to ranking freshness and captured work during concurrent resubmission.

**Regression coverage:** sitting submissions across adult/child birthdays; resubmission with
unchanged ages/evidence; resubmission across a birthday with changed consumed ages; reverting to
earlier answers; display/eligibility/scoring date consistency; genuinely changed answers;
equivalent provider routes; partial scoring reuse; and concurrent resubmission. Assert no new
miss or fresh call for sitting/unchanged evidence, and a miss only for affected changed evidence.

**Cost/latency constraint:** no clock-driven cache expiry, automatic AI run, or blanket purge of
valid existing work. Preserve valid caches during the identity transition. Existing rows whose
input provenance is incomplete need explicit handling; do not blindly relabel them with current
ages. Only genuinely changed/invalid evidence should require a new evaluation at the next
manually confirmed analysis, with its normal cost estimate. Submission itself does not wait for AI.

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

### R08 — An old expired-session response can clear a newer credential

Owners: [committee dependency](../backend/app/api/dependencies.py),
[applicant dependency](../backend/app/api/applicant/dependencies.py),
[cookie boundary](../backend/app/api/session_cookie.py), and authentication transitions.

Both optional authentication dependencies clear the shared cookie when the supplied credential
is invalid. That deletion belongs to a response, so the browser may apply it after another
request has installed a newer credential under the same cookie name.

The reproduction held an expired committee `/auth/me` response after its authentication check.
A test-only callback then installed a fresh member B session through the real cookie helper.
An intervening `/auth/me` authenticated B. Releasing the old response delivered `Max-Age=0`;
the HTTP client's cookie jar deleted B's cookie, and its next auth read returned no user.
The new server-side session itself had not been revoked. The applicant dependency has the same
cookie-clearing pattern. This test used a cookie jar and ASGI response ordering, not a live browser.

**Recommendation:** stop arbitrary failed reads from unconditionally deleting whichever
credential is now in the browser. Return the expiry/authentication state and let explicit
authentication transitions own cookie mutation. Review logout, link exchange, withdrawal, and
other cookie-changing responses for stale completion as part of the same transition contract.
Expected user/application IDs from R05 protect action targeting but cannot by themselves prevent
an already-started response from applying a stale `Set-Cookie` deletion.

**Regressions:** expired read versus new login on both surfaces; delayed logout versus sign-in;
parallel link exchanges; legitimate expiry recovery; and account-state updates after old responses.
Keep credentials HTTP-only and host-scoped.

**Latency:** removing inappropriate cookie mutation adds no waiting to normal reads. Keep any
coordination confined to credential-changing transitions, rather than serializing all requests.

### R09 — Removed members still contribute to current shared decisions

Owners: [eligibility aggregation](../backend/app/services/eligibility/evaluation.py),
[committee criteria aggregation](../backend/app/services/ranking/analysis.py), and
[access removal](../backend/app/services/auth/allowlist.py).

Access removal marks the user inactive, removes the allowlist entry, and revokes credentials.
It deliberately keeps historical user/preferences records. Shared input queries nevertheless
iterate every `User`, every matching override, or every ranking without membership filtering.

Three reproductions removed member A through `remove_entry` while member B remained active:

- A's working axis and pending proposal still appeared in `committee_kept_keys` and
  `committee_proposed_dimensions`, despite B keeping neither.
- A's forced-eligible override still admitted an otherwise rules-filtered household to both the
  screening scope and the discovery/scoring union.
- B's own view rejected a household, but the removed A's ordinary default-rules view still
  admitted it to the shared union.

**Recommendation:** define one active committee-membership predicate and apply it consistently
to shared rulesets, override bookkeeping, kept axes, and pending proposals. Filtering only the
ruleset map is incomplete and could also leave override lookups indexing missing members.
Preserve historical preferences/attribution and intentional shared-default screening behavior;
inactive records should not silently steer a new run. Define re-admission against the same
membership contract without deleting the member's history.

**Regressions:** removal, deactivation, re-admission, invited/active members, divergent rules,
eligible/ineligible overrides, skipped runs, proposals, and zero-member/default-screening behavior.

**Latency/cost:** use query predicates or a batch membership set. Excluding obsolete contributors
can reduce paid work; it does not require extra model calls or per-app authorization queries.

### R10 — Rank currentness ignores result-affecting strategy settings

Owners: [freshness](../backend/app/services/ranking/freshness.py),
[criteria execution](../backend/app/services/ranking/criteria.py),
[consolidation](../backend/app/ai/dimension_consolidation.py), and the currentness badge.

The fingerprint covers source rows, prompts, models, and effective reasoning levels. It omits
`discovery_fan_out` and `consolidate_correlation_threshold`, although execution directly consumes
them. Changing either left the fingerprint identical and `ranking_is_current` true in the probe.
Dashboard and rank-estimate readers use that result for currentness.

For consolidation, a concrete vector pair had correlation 0.5. Threshold 0.9 nominated no pair;
threshold 0.4 nominated one. The analysis remained marked current despite that changed work plan.
Fan-out likewise changes the number of discovery passes rather than merely a display preference.

**Recommendation:** include result-affecting strategy controls in the captured currentness
contract and persist their relevant values/versions for an inspectable comparison. Do not mark
analysis stale merely for a spending-cap or worker-count change that leaves semantic inputs
unchanged. Keep this distinct from per-applicant score-cache validity: a changed discovery
strategy does not automatically invalidate otherwise matching cached scores.

Handle existing analyses deliberately, using known audit/provenance where available. Do not
pretend their original settings were today's values, force automatic reruns, or purge valid
per-applicant work. The submission-time age invariant remains unchanged.

**Regressions:** fan-out, consolidation threshold, prompt/model/reasoning changes, captured
settings during a run, equivalent providers, unchanged settings, and nonsemantic cost/concurrency
controls. Verify both currentness and preservation of valid score-cache hits.

**Latency:** metadata comparison is cheap. Any additional discovery remains an explicitly
confirmed action with its estimate; this is not a daily or birthday-based invalidation rule.

### R11 — Guest pre-review rechecks withdrawal but not selection under its write lock

Owners: [guest pre-review](../backend/app/api/applicant/guest.py),
[collision copies](../backend/app/services/applications/drafts.py), and selected-access policy.

`check_guest_submission` checks selection before validating openings and calling
`save_collision_copy`. The copy helper then obtains the application writer lock and rechecks
existence, withdrawal, and email identity, but not selection.

The reproduction used a household in a closed opening and a second open opening. Guest
pre-review passed its initial checks for the open opening. A separate request session selected
that household in the closed opening immediately before the copy helper took its lock.
The guest request then created a new unrevoked private copy and access link and sent a captured
email, after selection had revoked earlier applicant access. Redemption still returned
`unavailable`; the effect was a retained extra copy and a misleading credential email, not an
editable selected profile. No real email was sent.

**Recommendation:** check the full target lifecycle/identity and relevant opening facts under
the writer boundary before staging a private copy or credential. Route a household that became
selected to the existing finalized-household response/notice. Preserve the redemption guard,
and release the writer before provider waits. Extend the existing lifecycle tests rather than
adding a separate selection state machine.

**Regressions:** selection before/after the initial check and before the copy lock; withdrawal,
email change, expiry, and overlapping openings; no recreated draft/credential for a finalized
target; and the ordinary unselected collision/reconciliation journey.

### R12 — Shared consolidation loses non-initiating members' priorities

Owners: [consolidation persistence](../backend/app/services/ranking/analysis.py),
[personal tier history/materialization](../backend/app/services/ranking/member_state.py), and
[identity transformations](../backend/app/services/ranking/identity.py).

Consolidation transfers the initiating member's dropped-key placement to its survivor. A comment
claims other members heal on their next read, but `get_or_create_member_ranking` immediately
returns an existing view, and carry-forward/history lookup matches literal keys without applying
the aliases needed to inherit the dropped placement.

Two reproductions had A prioritize `keep` and B prioritize `drop`, then merged `drop -> keep`:

- B first opened the new analysis before consolidation, then reopened it afterward.
- B first opened it only after consolidation.

In both cases A retained positive weight on `keep`; B's corresponding weight became zero.
B's deliberate working priority had been lost. If it was B's only priority, the resulting view
became unranked. The second timing shows that repairing existing current rows alone is insufficient.

**Recommendation:** canonicalize personal placement/history through the merge map, preserving
each member's own highest-priority placement across the merged keys. Cover both already-created
views and later carry-forward, without mixing members' judgments. Handle alias chains, resurfaced
survivors, Ignore, flags, and independent proposal changes under the existing JSON/write-ordering
contracts. Update the inaccurate lazy-healing comment with its actual ownership.

**Regressions:** early/late view creation, multiple members and tier levels, survivor already
placed, dropped key in Ignore, merge chains, cross-run revival, repeat healing, and concurrent
view materialization. Cached scores and their definitions/provenance must remain intact.

**Related measured cleanup:** for two members, `committee_kept_keys` performed five SELECTs
with one historical analysis and 43 SELECTs with twenty. The tier-history query joins Analysis
but does not populate that relationship, so later report access adds lazy queries. Populate the
needed history from the existing join while touching this owner. This is query-count evidence,
not a production timing claim or a reason to introduce a cache framework.

**Latency:** canonicalization needs no model calls; batched history/alias loading should reduce
database work. Preserve short write locks and avoid rewriting all historical records on every read.

## Implementation packages and decisions

1. **Identity and membership boundaries (R05/R08/R09).** Cover both browser surfaces, shared-cookie
   transitions/responses, server checks, recovery, and active membership in shared inputs.
2. **Save/read reconciliation and note actionability (R01/R07).** Keep the responsive, account-owned
   note writer; reconcile overlapping receipts and give blocked drafts a truthful resolution.
3. **Lifecycle availability and selective maintenance (R03/R04/R11).** Establish retention and
   selection boundaries across access/action/email paths, then remove measured no-work writes.
4. **Explicit ranking read outcomes (R02).** Preserve live navigation ownership without treating
   cancellation or failure as absence.
5. **Captured AI evidence and controls (R06/R10).** Keep ages frozen between submissions,
   refresh them on resubmission, and compare changed evidence/strategy settings while preserving
   valid cached work.
6. **Personal intent through shared merges (R12).** Reconcile both existing and future member
   views through aliases, and remove the measured history-loading overhead in the same owner.

Default policy recommendations: expiry begins on the existing Pacific purge date; selected
households remain reviewable but follow the current note-write restriction. Call out departures
from those defaults as product choices. R06 follows the confirmed submission-time age invariant;
calendar passage alone must preserve hits, while changed evidence after resubmission may miss.

Small documentation corrections should accompany their owners: the architecture map still
attributes private-note writes to the opening-scoped candidate-actions hook; the ranking score
assembler's docstring names the screening router for the shortlist; the fact-view comments
overstate identifier exclusion because canonical child details also contain names/birth dates.
SPEC explicitly permits full application context in AI input. Correct the description; do not
invent a new redaction policy or change model inputs as an incidental cleanup.
Descriptions of exact recorded AI configuration should also match the controls actually
persisted; R10's captured-configuration work should close that documentation/provenance gap.

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

The original audit's baseline checks passed: **897 backend tests**, one POSIX-only test skipped, and Ruff;
**258 frontend tests**, ESLint, TypeScript and production build; **9 watchdog tests** and typecheck.
The generated API map matches all **111** documented method/path pairs.
Python import graph: no cycles, including deferred imports. Frontend import/dynamic-import
reachability left only `vite-env.d.ts` outside the application graph.

**Twenty-two temporary reproductions** (the original eight backend/five frontend plus nine
backend extension cases) verified the current faults above and were removed. They asserted
existing faulty outcomes to establish evidence; they are
not committed regressions proving fixes. SQL/commit instrumentation was separate and also
temporary. New implementation regressions must invert these expectations at the owning boundary.

The extension deliberately made three passes:

1. Authentication request/response ordering, revocation and membership aggregation, and semantic
   rank settings. Six isolated cases confirmed R08–R10.
2. Transaction-boundary selection and per-member merge/carry-forward. Three more cases confirmed
   R11 and both timings of R12, rather than merely restating the first pass's findings.
3. UI mutation/reload paths, recovery/cancellation helpers, and history-loading cost. Feedback
   reloads already use the live fetcher; search/email-key edits already release their pending UI
   state. Those apparent candidates were rejected. History SQL instrumentation identified the
   bounded owner-specific cleanup attached to R12. No further standalone high-bar finding emerged.

Runtime code was unchanged since the baseline suites, so the extension ran the new targeted
probes instead of repeatedly rerunning unrelated full suites. Test collection/harness issues were
corrected before accepting evidence; the final extension run passed all nine cases. All fixtures
were synthetic/in-memory, and no provider judged output or sent real messages.

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
