# Batched discovery — October 7, 2026

**Status: B01–B14 implemented and verified. Discovery baseline: `28d74b7`.**

Three passes finished on this baseline before implementation. Each pass used three subagents
with rotated assignments plus coordinator review. The combined findings are verified and deduplicated;
the final docket distinguishes existing defects, incomplete/recent fixes, and product decisions.
No finding quota applies. The completed earlier work remains in
[the prior audit](project-audit-2026-10-06-follow-up.md).

Jeff authorized B01–B14 on October 7; they are implemented as one coordinated batch. D01 and D02
are declined: preserve the private-save wording and the intentional review summary of fields most
likely to contain mistakes. SPEC now describes those choices explicitly. The findings below retain
the discovery evidence; they are not a list of unresolved defects. No push or production changes
are authorized for this batch.

## Implementation results

| Items | Result |
| --- | --- |
| B01–B03 | Public sign-in capability uses unfiltered opening phases; both guest collision paths share recovery persistence; initial application and session-bound comparison arrive together in one response |
| B08–B09 | Submission-only completeness gate preserves partial/native/synthetic readers; a validated answer/opening/account/history-cutoff snapshot owns review admission, including chosen-copy and email-intent paths |
| B04/B05/B11 | Unscoped dashboard remains available after opening-list loading; print priorities belong to acknowledged ranking; detail captures member state before criteria/scores and removes the later hidden refresh |
| B10 | Successful detail reads renew note permission evidence; recovery is an explicit retry, and an older opening denial cannot overwrite newer evidence |
| B12–B13 | New tiers use unique existing IDs, duplicate-ID requests are rejected; only writes to the same owning record share a pending queue, with exact-tail cleanup |
| B06–B07 | Expired application retries stop before credential generation; expiry is expected cancellation in admin reports; unsubmitted application deletion receipts record draft actionability |
| B14 | Existing field editor adds explicit Text/Number/Boolean/Object/List creation, retaining strict fixture validation |

The initial applicant load removes a serial request. Independent opening writes no longer inherit
another opening's pending save. No AI prompt/model/cache changes, extra provider calls, migrations,
background pollers or broad database locks were added. The collision path writes a recovery copy
only when needed, and the no-opening dashboard uses its existing endpoint.

Runtime changes total **316 added / 94 removed lines, net +222** (excluding tests and documentation).
That includes one cohesive publication-validation module. Its conditions belong to new publication;
shared answer models remain appropriate for partial and retained data. The small extra transient
state has named purposes: accepted print priorities and permission evidence from a successful detail
read. There is no generic queue/state-machine framework.

Test review removed 35 duplicate cases exercising the same inherited submission validator twice;
the field inventory is tested once, and actual guest/authenticated HTTP tests prove both boundaries.
The startup-client test now proves one coherent read; the obsolete delayed second-read expectation
was replaced with delayed application/copy admission. Existing copy-choice and storage-protection
scenarios were retained and updated to the new response contract.

Final integration review found no actionable regression or excessive abstraction in the combined
diff. A selected-in-another-opening note hypothesis was rejected after tracing actual visibility:
the ordinary detail query excludes that household; retained detail is explicitly read-only. No
additional capability field or broader permission change was needed.

Chrome verification reused the signed-in local tab without reload. A new unsaved Boolean metadata
field rendered as a checkbox. Added control rows measured a 4.39 px gap, stayed on one line and
showed no clipping; the temporary case was cancelled without saving. Native print/drag behavior
and real provider judgment were not exercised; coherent print DOM and async sequences have
component/hook coverage.

Final coordinated checks: **1,308 backend tests passed, one platform-specific skip; 462 frontend
tests passed; frontend build, ESLint, Ruff and whitespace checks passed.** The backend suite was
rerun after removing the duplicate inherited-validator cases. Build directories retained inherited
permissions. No temporary probe files remain. The combined diff received coordinator review and an
independent source review; neither identified an actionable remaining integration issue.

| Commit | Items |
| --- | --- |
| `26e57c8` | B01/B02/B03/B08/B09: applicant access, recoverable copies, coherent restore, publication and review admission |
| `e7076fd` | B04/B05/B10/B11/B12/B13: committee dashboard, coherent reports, note recovery, tier identity and record-owned queues |
| `af582f7` | B06/B07: email retry retention and accurate deletion reasons |
| `949189b` | B14: explicit typed eval field creation |

The SPEC clarification and this verification record are committed separately. No push or deployment
was performed.

**Next cadence:** after this batch's final checks/review, pause repeated whole-project discovery.
Keep ordinary usage, targeted regression tests, and focused reviews when features or ownership
boundaries change. Reported symptoms or a concrete change justify another targeted investigation;
an unchanged baseline does not need another unrestricted audit immediately.

## Coverage map

| Pass | Perspective | Applicant / identity / private copies | Committee / ranking / views | Operations / evals / lifecycle |
| --- | --- | --- | --- | --- |
| 1 | User journeys and current contracts | Complete | Complete | Complete |
| 2 | Persisted state and reported results back through their producers; adverse sequences | Complete | Complete | Complete |
| 3 | Independent challenge, supported data shapes, simplicity and uncovered boundaries | Complete | Complete | Complete |

The coordinator reviewed cross-domain consumers, confirmed evidence, checked fix interactions and
prepared one implementation plan after all passes. Source review, executed synthetic scenarios,
and existing test results are separate evidence. Temporary probes may assert current defects;
they are removed after reproduction and are not application changes.

## Boundaries

- No application implementation between discovery passes.
- No production, live database, real provider/email, deployment or push operations.
- Synthetic in-memory/component/API tests are permitted. File-backed tests use the established
  test directory without ACL repairs or new temp-root conventions.
- Existing product choices remain: submission-time age, committee-owned priorities, automatic
  valid-cache reuse, distinct discovery/scoring actions, local-only fixture editing and uncapped evals.
- Proposed remedies must identify their owner, meaningful acceptance checks, latency/complexity
  cost and deletion/consolidation opportunity. A broad rewrite is not the default remedy.

## Findings at the discovery baseline

Final docket: **13 functional/reporting findings and one worthwhile authoring improvement**, plus
two declined product proposals. Pass 2 independently reproduced B07; that is corroboration,
not an additional finding. Priority P2 means a worthwhile functional correction; P3 is a lower-impact
reporting correction. No application changes have been made during these passes.

| ID | Priority | Finding | Discovery |
| --- | --- | --- | --- |
| B01 | P2 | Closed-only openings hide returning-applicant sign-in | Pass 1 |
| B02 | P2 | Final guest-submit identity collision omits the recoverable guest copy | Pass 1 |
| B03 | P2 | Initial pending-copy uncertainty permits editing and saving | Pass 1 |
| B04 | P2 | No selected opening skips global dashboard actions and retains stale workflow | Pass 1 |
| B05 | P2 | Printing can mix optimistic priorities with accepted ranking results | Pass 1 |
| B06 | P2 | Expired application access-link retries bypass the retention check | Pass 1 |
| B07 | P3 | Scheduled private-application deletion records the wrong retention reason | Pass 1, independently repeated in pass 2 |
| B08 | P2 | Publication accepts incomplete answers required by the form | Pass 2 |
| B09 | P2 | Save completion opens review for subsequently changed, unvalidated answers | Pass 2 |
| B10 | P2 | Opening-scoped note denial permanently blocks an otherwise writable draft | Pass 2 |
| B11 | P2 | Detail can combine criteria and priorities from different consolidation states | Pass 2 |
| B12 | P2 | Add/remove/add tier sequence duplicates an existing tier identity | Pass 2 |
| B13 | P3 | Slow saves delay unrelated writes in another opening | Pass 3 |
| B14 | P3 | Supported optional Boolean/object eval fields cannot be created in the editor | Pass 3 |

### B01 — Keep returning-applicant access available when openings close

**Evidence.** `backend/app/api/applicant/guest.py:86` sends anonymous opening states through
`applicant_openings` (`presentation.py:60`), which hides closed openings unless the applicant
participates. Anonymous callers cannot participate, so a closed-only pool returns no cards.
`frontend/src/applicant/ApplicantApp.tsx:221,328` derives access availability from those cards
and renders the unavailable screen without email or Google sign-in. An actual in-memory endpoint
probe returned `canStartApplication=false, openings=[]`; the identity service still admitted an
existing participant, and a rendered UI probe confirmed missing access controls. Pass 3 independently
confirmed Google/email access succeeds for a closed-undecided participant but is unavailable for
archived-only openings. Previously emailed links still work. The closed-card filter traces to
`6953801`; its authenticated behavior is intended.

**Remedy/owner.** Separate returning-user access from the public list of selectable openings in the
existing public response and entry UI. Derive a public sign-in capability from unfiltered published
open/closed states; keep inactive closed cards hidden and new applications closed. SPEC 191–204
explicitly disables sign-in when no published opening is open or closed, so always-present sign-in
would be an unintended product change. Do not add another availability request or expose
applicant-specific participation publicly.

**Acceptance.** Closed-only, open-plus-closed, upcoming-only and archived-only configurations;
existing email and Google identities; new-applicant restrictions and the no-active-opening entry
policy preserved.

**Cost/complexity.** No additional network request; stop inferring authentication availability from
filtered opening cards. Existing defect, not introduced by this discovery batch.

### B02 — Preserve the guest copy at the final identity-collision boundary

**Evidence.** `backend/app/api/applicant/guest.py:111–139` preserves a collision copy during the
pre-review check. The final submission branch at `:216` only sends an application-bound link.
Reproduced: precheck succeeds, another tab creates the same-email application, then the original
guest submits. The existing application remains unchanged, but there are zero recovery drafts and
the sent link has no `applicant_draft_id`. Answers remain only in the original browser tab.

**Remedy/owner.** Both collision entrypoints should use the existing `save_collision_copy` and
draft-bound access-link flow. Consolidate this duplicated identity handling; preserve selected,
withdrawn, retention and email-change authority checks. Convert canonical to working answers
explicitly if necessary; do not corrupt dates by using an inappropriate dump representation.

**Acceptance.** Precheck/final-submit race; recovered comparison contains exact guest answers and
opening choices; neither copy is published without choice; selected and expired identities remain
restricted; pending draft revocation and request throttling continue to apply.

**Cost/complexity.** One recovery-draft write on the exceptional collision path, no ordinary-submit
round trip. Existing omission in sibling collision paths.

### B03 — Admit the initial application and pending-copy state together

**Evidence.** `frontend/src/applicant/useApplicantPersistence.ts:301–354,632,647` applies an editable
application before the separate pending-copy lookup completes. A real-hook probe made that lookup
fail: `pendingCopy=null`, phase error, but `canEdit` and `openingsLoaded` remained true and save reached
the server. A save while the lookup is pending can also invalidate the comparison read.

**Remedy/owner.** The persistence restore owner must not interpret unknown comparison state as
confirmed absence. Prefer accepting application and comparison together; investigate including the
session-bound comparison in the existing application response to remove the serial read rather than
adding more blocking flags. Preserve later storage snapshots and explicit reconciliation recovery.

**Acceptance.** Slow, failed, malformed, absent and present comparisons; no save/review until
authoritative state is known; retry restores access; session switch and newer browser edits cannot
be overwritten; explicit copy-choice failure stays recoverable.

**Pass 3 recovery challenge.** A successful explicit copy choice already returns the exact accepted
application. Likewise, authoritative absence after a stale/not-found choice intentionally restores
the saved copy using captured browser storage and skips another comparison lookup. Do not apply an
initial-load gate so broadly that it strands those completed choices or adds redundant requests.

**Cost/complexity.** This closes an existing uncertainty interval. If bundled in the application read,
it removes a round trip. If kept separate, editing must wait for the already-required second read;
record that latency explicitly. No speculative cache or second persistence owner.

### B04 — Load the unscoped dashboard when no opening is selected

**Evidence.** Backend `app/api/dashboard.py:62,103` already supports an absent opening and global
admin actions. Frontend `api/dashboard.ts:12`, `hooks/useDashboard.ts:42,55` and workspace refresh
gates skip that request. Actual hook probes: initial null makes zero requests and remains loading;
switching a previously loaded opening to null retains its old ready workflow and coverage. Global
empty-opening/delivery warnings disappear; this does not make every admin panel inaccessible.
The null gate traces to `3da249c`.

**Remedy/owner.** Let the existing dashboard client/hook/workspace request the supported unscoped
response. Settle empty workflow and global actions through the same owner; no separate endpoint,
poller or duplicated admin-action loader.

**Acceptance.** Initial empty system, final opening disappearing, null-to-opening navigation,
late prior-opening response, failed unscoped request and retry; global warnings remain available.

**Cost/complexity.** One existing-endpoint request in a state currently skipped. No additional request
on normal opening navigation. Existing defect.

### B05 — Print priorities and ranking from the same accepted state

**Evidence.** `frontend/src/hooks/useRanking.ts:239` updates tiers optimistically; weights and
candidates change only on acknowledgement (`:246–250`). `components/ranking/RankingView.tsx:214`
prints optimistic tiers beside accepted candidates, and its print buttons remain enabled. Actual
hook-to-view probe deferred an A-to-B priority write: the printed priorities named B while scores
and order still used A. `window.print` was invoked. Native browser printing also reads the DOM.

**Remedy/owner.** Render print-only priorities from the exact acknowledged ranking snapshot.
Keep the interactive editor optimistic. Capture accepted tiers from the acknowledged request,
not whichever newer edits happen to be visible. Disabling app Print buttons alone is insufficient.

**Acceptance.** Pending, successful, failed, uncertain, queued and superseded priority changes;
application buttons and native print use a coherent report; ordinary typing remains responsive.

**Cost/complexity.** No request or server wait. Keep this accepted report slice with the existing
ranking state rather than create a parallel print store.

### B06 — Apply retention before rebuilding application access-link retries

**Evidence.** `backend/app/services/email/outbox.py:287` dispatches magic-link retry handling before
the application retention guard around `:322`; `_build_magic_link_retry` at `:458` checks drafts but
not linked applications. An abandoned pre-midnight attempt can be recovered by the next ordinary
write's outbox drain before daily maintenance runs. In-memory reproduction created a fresh token
and one captured email for an application whose deadline was today. Redemption still rejects the
expired application: this is an unwanted credential/email, not an access bypass.

**Remedy/owner.** Reuse retention eligibility before generating credentials or sending application
access/email-change retries. Treat expiry as expected cancellation, not an admin delivery failure.
Preserve draft, targetless and committee invitation behavior.

**Acceptance.** Expired application access and email-change attempts create no token and call no
sender; current applications, eligible drafts and committee invitations continue normally;
post-write recovery and daily maintenance agree.

**Pass 3 sibling challenge.** Non-magic application retries already cancel with `ApplicationExpired`,
but that code is absent from `EXPECTED_FAILURE_CODES`. Actual queue-status/delivery-issues reads
therefore advertise routine expiry as an actionable delivery failure. Include the existing code in
expected cancellation classification and verify both admin surfaces. This belongs in B06's same
retention/cancellation correction, not a separate finding count.

**Cost/complexity.** Local check against already loaded state; no new network work. Existing retry
ordering gap. Reuse lifecycle policy rather than duplicate date calculations.

**Trigger qualification.** Daily maintenance normally purges expired applications before draining
the queue; their pending mail then cascades away. This finding concerns post-write recovery before
that purge, concurrent lifecycle work, or a drain crossing midnight after its purge—not every normal
next-day quota retry. The in-memory drain probe exercises that reachable boundary directly.

### B07 — Record the actual retention policy for private-application deletion

**Evidence.** `backend/app/services/applications/purge.py:94–108` classifies only selected versus
other applications. A never-submitted claimed `Application` record is therefore journaled as `one_year`
despite a close-anchored draft deadline. Actual deletion probes in two independent passes confirmed
the journal reason; deletion timing and restore exclusion were correct. Classifier traces to
`fecde3ba` (August 26).

**Remedy/owner.** Pass the already-loaded application into the existing classifier and distinguish
unsubmitted state before selected/submitted rules. Reuse the established draft-actionability reason.

**Acceptance.** Private, submitted unsuccessful and selected deletion reasons match their policy;
explicit deletions and restore exclusions remain unchanged.

**Cost/complexity.** No extra request; the private branch can avoid the selected-participation query.
Reporting correction only—no date migration or production backfill is proposed.

### B08 — Validate completeness at publication, while preserving partial saves

**Evidence.** Both submission routes use `SubmitApplicationRequest.answers: CanonicalApplicationAnswers`
(`backend/app/schemas/applicant/contracts.py:138`). That shape does not enforce required primary
name/phone/address/essays or complete employment/income for a present co-applicant. Actual in-memory
ASGI calls returned guest **201** and authenticated **200**, persisting versions with required answers
blank. The form and SPEC require them. B09 supplies an ordinary-browser trigger, not just a manually
constructed request. Missing validation predates the October work (August 23–24).

**Remedy/owner.** Put publication completeness in the shared submission boundary. Do not tighten
shared `AddressAnswers`/`EssayAnswers` used for private partial answers and empty Google drafts.
Do not globally tighten canonical ingestion: two of the 100 committed synthetic records contain
incomplete present co-applicants. Retained/legacy reads and synthetic ingestion remain separate from
new publication. Optional additional information, photo, pets, absent co-applicant and inapplicable
references remain optional. Do not invent stricter contact formatting.

The final sibling inventory must guide the publication validator, not just the essay reproduction:
primary person fields; present co-applicant person/relationship/employment/income; each present
child's name and date of birth; current and required prior residence fields and move-in dates;
ownership choices; applicable landlord/reference details; employed adult job/company/start and
manager details; self-employed job/business/start without manager details. Unemployed adults need
no employment detail, zero income remains valid, and street line 2 is optional. Preserve the existing
date/history rules and current-renter/previous-residence conditions; do not make inapplicable fields
required. This inventory is derived from the actual form, not a new questionnaire policy.

**Acceptance.** Both submission routes reject blank/whitespace required fields and incomplete present
co-applicants without committing a version; partial saves, retained imports, synthetic loading and
optional fields still work. One shared publication rule, not per-route copies.

**Cost/complexity.** Negligible local validation, no provider or network work. This boundary is simpler
than treating a frontend-required attribute as the sole publication guarantee.

### B09 — Bind review admission to the validated answer/opening snapshot

**Evidence.** `frontend/src/applicant/ApplicantApp.tsx:134–138` validates before awaiting preparation
and save, then opens review unconditionally on success. Real App + persistence + API-client probe:
start Save and review from valid answers; hold the PUT; clear the required Why co-op essay; release
the older save. The invalid newer answers appear in review and Submit sends the blank essay. The
PUT contained the earlier valid essay. Existing save acknowledgements correctly retain edits as dirty;
the defect is the separate review transition. Preexisting August behavior.

**Remedy/owner.** Require the current answers and opening choices to match the reviewed snapshot,
or revalidate before transition. Preserve edits and remain in the form when preparation was
superseded. Also challenge the guest preparation and post-access review entrypoints.

**Acceptance.** Answer and opening changes during each await, unchanged success, failure and
session/lifecycle changes; no later input silently inherits earlier validation. B08 is still necessary
because publication is an independent server boundary.

**Pass 3 sibling challenge (source trace).** `useApplicantPersistence.ts:256` sets `reviewAfterAccess`
from a submit intent; `ApplicantApp.tsx:76` opens review before copy choice settles. An incomplete
saved copy chosen afterward can reveal review without form validation. A submit intent is navigation
context, not proof that the actual chosen answers are complete. Cover saved/guest choices, incomplete
saved answers and copy-recovery responses under the same review admission rule. This is a sibling
acceptance requirement, not a second independently executed reproduction or another finding count.

**Cost/complexity.** No new request and no editor-wide freeze. Keep transition ownership in the
existing review flow instead of introducing another save queue.

### B10 — Scope note denial to the authority that actually failed

**Evidence.** `frontend/src/hooks/usePrivateNotes.ts:56,72` stores an opening-scoped 404 as
application-wide `draft.blocked`; `CandidateNotes.tsx:168` then offers a read-only draft and discard.
Actual bound-client probe: A returns 404, B would accept, but opening B and explicitly flushing makes
no B request. Actual in-memory route confirms A denies after withdrawal while B saves the same
applicant's note. The existing 409 recovery test never enters this 404 state. The blocked guard traces
to `6795c9a` (October 5), before the October 6 reverted-write fix.

**Remedy/owner.** A freshly loaded writable detail may restore explicit retry under its current
opening. Keep application-owned draft text and the existing ordered writer; scope permission evidence
to the opening that supplied it. Do not blindly replay on navigation or elapsed time.

**Acceptance.** A withdrawal with B active; all-opening withdrawal; expiry and selected/read-only
contexts; same-opening renewed availability; late A failure after B opens; retry uses B/current text.

**Cost/complexity.** Reuse the successful detail read; no extra request or draft store. Recent incomplete
recovery coverage, not a reason to remove account-owned unsaved-note protection.

### B11 — Capture the coherent ranking view before assembling applicant detail

**Evidence.** `backend/app/api/applications/presentation.py:215–221` captures report/scores/trace,
then `_dimension_scores` at `:363` reconciles member state and can refresh the analysis. It applies
new tiers to the detached earlier report. In-memory actual `serialize_detail` plus real
`apply_consolidation({newer: older})`, with valid mock-generated score coverage: contributions were
`[newer]` before, `[]` during, `[older]` after. During the race, trace still claimed one scored criterion.
This is a deterministic committed interleaving, not a simultaneous-thread test.

**Remedy/owner.** Read the coherent member/analysis view first, then capture report and score rows.
Pass that captured member view into contribution assembly and remove its independent reconciliation
lookup. The board's recent snapshot repair must cover this sibling consumer too.

**Acceptance.** Consolidation on either side of capture, including resurfaced survivors; contributions
and trace agree with one complete view. Preserve selected-applicant and new-analysis score provenance.

**Cost/complexity.** Reorder existing reads; remove a hidden refresh from a presentation helper.
No broad lock or additional request. Incomplete recent sibling coverage: detached capture dates to
October 3 (`14733332`), reconciliation to October 5 (`0e336de9`). Distinct from client-side B05.

### B12 — Make the existing tier identity unique

**Evidence.** `frontend/src/components/ranking/TierList.tsx:424` uses current counts for IDs.
Rendered sequence Add twice → remove earlier custom tier → Add creates two surviving `tier-5-4`
rows. Renaming one renames both; React reports duplicate keys. Removal filters both but transfers
only the first row's criteria. Actual backend `update_tiers`/`ranking_board` accepts and persists the
duplicates. Algorithm traces to June 25 (`73415425`).

**Remedy/owner.** Allocate a unique value for the existing tier ID at creation and reject duplicate IDs
at the update boundary. No second identity or database schema is necessary. Inspect any repair need
separately rather than assuming malformed existing layouts should be silently rewritten.

**Acceptance.** Repeated add/remove/reorder/add cycles and reload; independent rename/remove;
every placed criterion preserved; duplicate-ID API requests rejected.

**Cost/complexity.** Constant-time client allocation and a small linear request validation. No extra
network call. Older ordinary editing defect, unrelated to the recent concurrency additions.

### B13 — Let unrelated opening writes proceed independently

**Evidence.** `frontend/src/hooks/useRanking.ts:81,118–130` keeps a single mutation queue across
opening/analysis changes. `useCandidateActions.ts:38` omits opening from queue keys even for
opening-owned eligibility and shortlist records. Three actual-hook probes confirmed: defer A's save,
switch to B (and load B's board in the ranking probe), edit B, and B's request remains unsent until A resolves. The dependency is
measured; a 30-second delay was not wall-clock tested. `api/client.ts:9` configures a 30-second
action timeout, so that is the possible inherited wait. Ranking queue traces to September 30
(`97548870`); no introduction date is claimed for the candidate-action sibling.

**Remedy/owner.** Serialize only by the owning record. Ranking uses opening plus analysis;
eligibility/shortlist uses opening plus application plus field; applicant-owned favourites and
committee notes retain ordering across openings. Keep a map only of pending tails and remove
each entry when that exact tail settles, using the existing candidate-action cleanup pattern.
Simply resetting the queue on navigation is unsafe when returning A → B → A.

**Acceptance.** B proceeds while A is pending, but returning to A preserves A's ordering. Late
responses remain fenced; settled entries disappear; same-applicant favourites/committee notes
stay ordered across openings. Check both completion orders and failure recovery.

**Cost/complexity.** Removes unnecessary client waiting while preserving same-record guarantees.
One bounded ownership map replaces ranking's overly broad tail; candidate-action change is its
existing key. No extra requests, persistence or synchronization framework.

### B14 — Allow the editor to create supported optional typed eval fields

**Evidence.** `frontend/src/components/evals/StructuredFields.tsx:72–76` creates new object fields as
empty strings, then chooses controls from that value's type. New-case templates omit optional
`metadata.contested`. A real component interaction added it and entered `true`; the payload contained
the string `"true"`, which the actual `validate_case` rejected. The identical Boolean value succeeds.
Absent `expected.pets` objects and typed counts have the same limitation. These are supported schema
fields (`case_schema.py:110–145`), not speculative arbitrary structures.

**Remedy/owner.** Recommend a small explicit value-type choice when adding a field, or narrow
family controls for these optional structures if that is clearer. Keep the existing recursive editor
and strict validation; do not guess types from text such as `"true"`. No schema-driven form framework.

**Acceptance.** Create a contested case and pet assertion starting without those fields, save valid
Boolean/object/numeric payloads, preserve existing scalar/list/object edits and locked metadata.

**Cost/complexity.** Local UI only; no additional provider cost or request. Preexisting authoring
limitation, not an October regression: the earlier text-only field creation relied on family templates.
Worthwhile completeness improvement; it is lower priority than publication/recovery fixes.

## Product decisions

- **D01 — Declined by Jeff (October 7).** Keep the current private-save/submitted presentation.
  Do not implement the proposed private-save wording or additional state for this recommendation.
- **D02 — Declined by Jeff (October 7).** The final review intentionally summarizes fields most
  likely to contain mistakes. Preserve that summary; omitted answers still enter the submission.
  SPEC now states this explicitly. Do not expand the review or add another answer mapping.

D02 concerns which answers appear in the final preview: the current screen shows openings, names,
primary email, child count, optional photo link, abbreviated current housing/employment, and combined
income. It omits the essay answers, pets, phone/birth/relationship details, individual child details,
previous housing and ownership choices, full reference contacts, employment dates and individual
incomes. Those answers remain in the submission payload. The proposed change is a complete read-only
preview grouped like the form, with inapplicable sections omitted and the existing editing/submission
actions retained. It requires no new API call, provider work or publication policy.

This presentation decision is separate from B08/B09's publication and review-admission corrections.

## Evidence and exclusions

| Pass / domain | Executed evidence | Source-reviewed siblings / limits |
| --- | --- | --- |
| 1 applicant | Four frontend assertions; actual public-opening, identity and guest-collision memory probes | Access, private/submitted copies, browser storage, review; no real OAuth/email |
| 1 committee | Three targeted probes; 101 existing frontend tests; four-app/two-member eligibility probe | List/detail/override/member ranking/union; no native drag/print |
| 1 operations | 108 existing tests; retention/outbox memory probes | Delivery leases, lifecycle, eval outcomes and costs; no disk restore |
| 2 applicant | 86 existing frontend tests; real App save-review reproduction; guest/authenticated ASGI publication probes | Working/canonical/legacy/synthetic consumers, identity, storage, acknowledgements |
| 2 committee | 67 existing backend and 116 frontend tests; actual note-route, consolidation/detail and duplicate-tier probes | Overrides, favourites, shortlist, shared notes/settings, AI completion; no simultaneous threads |
| 2 operations | 76 existing tests; independent private-deletion reason reproduction | Deadline writers, deletion journal/restore exclusions, delivery cancellation/consent, eval histories/costs |
| 3 committee | 74 existing frontend tests and three new queue probes | Ranking/list/detail math and shared snapshots, navigation, selectors/facets, print, notes, tier IDs and actual record ownership |
| 3 operations | 45 existing backend, 56 existing frontend tests and one editor probe; independent actual outbox/purge memory probes | Shared eval grading/partial completion, histories, costs, fixture authoring, delivery cancellation/reporting and retention evidence |
| 3 applicant | 26 existing backend and 86 frontend tests; actual closed/archived identity-entry probes | Full applicable form inventory, saved/guest choice recovery, submit-intent review, identity/storage and lifecycle boundaries; no distinct new finding |

Counts overlap across passes and are not a unique-suite total. Temporary probes are removed after
recording their evidence. No provider judgment, production state, live database or browser gesture
is claimed verified by these synthetic checks.

Not promoted into new implementation work:

- Full-rank CLI synthetic-source/export enforcement: explicitly deferred earlier by Jeff. Preserve
  the limitation; another discovery pass is not permission to reverse that choice.
- Malformed persisted string `EvalRun.result`: can fail catalog parsing, but no supported writer
  producing this state was found. Unsupported-data robustness observation, not a confirmed flow bug.
- Screening aggregate mismatch in a contested case: actual UI derives individual outcomes; no
  user-visible incorrect result established. Do not add another reconciliation layer speculatively.
- Matching fixtures with multiple descriptors: present fixtures use one prior/one new; policy for
  expanded cases is not grounds for a new framework.
- Whole-dollar private-income input tolerance: potential raw numeric input inconsistency, but no
  confirmed wheel-triggered mutation or agreed fractional-income save policy. Do not quietly change it.
- Phone/date handlers assume `InputEvent.inputType`: generic synthetic DOM events may omit it, but
  no ordinary browser/autofill path was reproduced. Unconfirmed hypothesis, not a claimed user bug.
- Reconsidering terminal unsuccessful-email attempts: intentional supported retry behavior.
- Broad caching, synchronization, template rewrites or module splitting: no measured material
  latency/readability benefit established. Prefer the concrete ownership corrections above.

## Net complexity assessment

The recent protections remain worthwhile: exact save acknowledgements preserve newer input;
account-owned notes retain unsent work; same-record ordering protects persisted intent; coherent
ranking views prevent mixed results. These findings do not justify removing those guarantees.

The remaining problems are mainly boundaries that are broader or narrower than their data owner:
public access inferred from private-card filtering, note authority tied to the whole applicant rather
than the failed opening, publication relying on an earlier browser validation, and a detail helper
refreshing state after its caller has already captured part of the response. Fix those boundaries
in their existing owners. Avoid adding compensating refreshes and parallel flags at every caller.

Concrete simplification opportunities are attached to the defects rather than separate speculative
refactors: share the collision path (B02); consider one initial application/comparison read (B03);
use the supported dashboard response (B04); remove the detail helper's hidden reconciliation (B11).
Accepted versus optimistic ranking is meaningful transient state, but should have one clearly named
owner. No new persistent cache, polling loop, generic state machine or database schema is proposed.

Responsiveness should improve through B13 and potentially B03. B04 adds one necessary read when
there is no selected opening. B02 adds recovery persistence only on a collision. Other fixes are local
validation or rearrangements of existing reads/state. There is no proposed AI cache invalidation,
birthday recalculation, extra provider call, waiting for derived views before acknowledging saves,
or broad database locking. These are expected effects from the proposed design, not post-fix timings.

## Why the changed discovery method helps

Earlier passing tests often established a rule within one producer or consumer. This batch follows
the same state across the publication boundary, navigation, delayed completion, print and other
consumers. Examples: the save acknowledgement is correct while review admission is wrong (B09);
the board snapshot is coherent while detail performs another refresh (B11); existing tiers edit
correctly while delete/re-add creates duplicate identities (B12). These are missing scenarios, not
evidence that all prior hardening should be replaced.

For the implementation batch, use a small boundary checklist per changed invariant:

1. Identify the owning record and every writer, reader and presentation consumer.
2. Test one complete real boundary using supported data; avoid proving only a helper or a mocked
   facade whose contract differs from the actual client.
3. Exercise delayed completion and navigation in both directions, including returning to a previous
   owner; cover hard denial, uncertain delivery, and newly established permission separately.
4. Exercise creation/removal/recreation and absent optional shapes, not only editing full fixtures.
5. Review the proposed fix against all siblings before committing, then retain only tests that prove
   distinct user behavior. Remove tests of branches that no longer exist.

This reduces correlated blind spots. It is bounded coverage, not a promise that future audits cannot
find another defect. A new material issue discovered while implementing still gets traced through
its consumers in the same batch rather than deferred into another user-requested audit.

## Completion and implementation grouping

Pass 3 rotated every reviewer into their remaining domain. It independently reviewed supported data
shapes and action sequences, then challenged these findings and their remedies through sibling
consumers. All nine domain/pass assignments are complete. The final challenge refined expiry
reporting, review admission, public-entry policy and fix acceptance; no material candidate remains
unexamined within the recorded coverage. Explicit limitations above remain limitations.

Implementation groups: applicant access/copy recovery (B01–B03); publication/review admission
(B08–B09); dashboard/report coherence (B04–B05/B11); note authority
(B10); tier identity and independent-write responsiveness (B12–B13); email retention and journal
accuracy (B06–B07); supported eval authoring (B14). Tests should extend the
existing behavior suites and replace superseded expectations rather than accumulate one test per
historical implementation branch.

The application-code baseline stayed fixed throughout discovery. Temporary probes were removed;
only this audit, the previous audit's forward pointer, and the collaboration-rule reminder changed.
Focused test runs above support the discovery evidence. The implementation results and final
verification recorded at the beginning of this document describe the subsequent authorized batch.
