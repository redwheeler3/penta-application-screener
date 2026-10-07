# Audit fixes: behavior changes

This describes the 30 work items implemented in the local commits `af8aab4` through `a279f77`.
They have not been pushed or deployed. The before/after descriptions refer to the faulty paths
found during testing; they do not claim every issue occurred in production.

The [production retention preview](retention-preview-2026-10-07.md) found all 233 existing
application deadlines correct. No production date repair is currently indicated.

## Applicant access and editing

| Item | Before | After |
| --- | --- | --- |
| X07 — Email access | An old access link could regain access after an address change; a cancelled email-change link could restart the cancelled change. | Renewal and redemption respect the current authorized identity. Cancelled/completed changes stay closed. Legitimate expired-link recovery and queued delivery retries remain available. |
| X11 — Address history | An archived opening could demand older address history that the form hid or removed. | Required history follows the openings shown on the form. Archived participation remains intact. |
| X12 — Repeated submission | A second submit could fail after the first succeeded and replace the success confirmation with an error. Related writes could also overlap. | One conflicting applicant mutation runs at a time; submit is disabled while working. Old responses cannot disturb a newer session. Local edits made during a save remain protected. |
| X18 — Choosing between copies | Choosing the saved application could restore a third remembered browser draft. A lost acknowledgement could expose the wrong copy as editable. | The accepted whole copy is adopted directly. Uncertain recovery keeps the comparison available and blocked until resolved, preserving newer browser storage. |
| X19 — Incomplete imported records | Saving before answering new employment/housing questions could erase known manager or landlord contacts from the private copy. | Known references survive incomplete private saves and reopening. Submission still applies its intended validation and removal of irrelevant fields. |
| X26 — Availability and email refresh | With an email change pending, competing refreshes could discard current opening/edit permissions. A rejected locked save also failed to refresh them. | One refresh reconciles identity and availability while preserving unsaved answers and strict revision checks. A lifecycle rejection updates the controls or leaves a retryable error. |

## Retention and cleanup

| Item | Before | After |
| --- | --- | --- |
| X09 — Withdrawal before a decision | Withdrawn participation could miss the final decision's deadline update, leaving the record without an expiry. | Final decisions refresh retention for all durable participation, including withdrawal. Outcome emails still go only to the appropriate active recipients. |
| X10 — Private draft deadlines | Changing openings could leave an obsolete deadline. Claiming an empty-selection draft could lose the deadline altogether. Closing the last fallback opening could also produce an indefinite hold. | Creation and private selection changes maintain the deadline together. Email/Google claims and empty selections receive an appropriate finite expiry; submitted retention is kept separate. |
| X24 — Cleanup during email configuration failure | Invalid mail configuration could prevent the retention sweep from starting. | Purge runs before constructing the email sender. Email failure is recorded without blocking that cleanup. |

The periods themselves remain unchanged: drafts expire after the applicable closing date;
non-selected submitted applications use one year after the last relevant decision; selected
households use seven years after selection. Withdrawal and move-in dates do not restart the clock.

## Committee screening and ranking

| Item | Before | After |
| --- | --- | --- |
| X08 — Criterion consolidation across openings | Consolidation elsewhere could move a member's priorities onto keys absent from the report they were viewing, effectively zeroing those priorities. | Priorities follow identities owned by the particular report, including an intermediate survivor in a longer merge chain. Other openings' intent remains intact. |
| X13 — Coverage after consolidation | A run could report everybody scored, then replace a criterion with an older one whose consumed scores were incomplete, dropping applicants from the board. | Valid reusable survivor scores are adopted together with the merge. Missing/stale survivor coverage defers the merge and preserves the scored criterion. The audit distinguishes confirmation from an applied merge. |
| X20 — Another member's first ranking | A workspace opened before any ranking existed could fail to expose criteria another member subsequently created. | Observing that first analysis offers the existing Reload action. |
| X21 — Interrupted screening | A connection/body error could leave the list or open detail showing old findings despite some results already being saved. | The affected views reconcile committed results after an uncertain interruption, while still reporting that completion was not confirmed. |
| X25 — Selected households | List/detail controls offered override, favourite and shortlist writes that the server would reject. | Those actions are read-only for selected households. Evidence, badges and read-only notes remain visible, with the correct ordinary or retained-view navigation. |

## Navigation and administrative views

| Item | Before | After |
| --- | --- | --- |
| X05 — Dashboard loading | A failed background refresh could supersede initial loading and leave the spinner stuck. | The winning request settles the loading state, including failure and recovery. |
| X06 — Expanded traces | Refreshing the same analysis could unmount an expanded trace and return it collapsed. | The trace stays mounted and expanded during refresh; failure keeps the last results with a retry message. A genuinely different opening/analysis resets it. |
| X14 — Subscription support editor | Changing only email capitalization/spacing could unlock a pending write, allowing overlapping save/delete actions and obsolete acknowledgements. | Conflicting controls remain locked until the write settles; deletion cannot erase permitted newer preference edits. Ordinary replaceable lookups remain available. |
| X15 — Feedback navigation | An applicant link in feedback used the administrator's current opening, which could fail or show the wrong context. | New feedback carries its opening/review context. Links use that context and existing access rules; unavailable older context does not grant broader access. |
| X17 — Feedback privacy | A member could supply a private-draft ID and receive its applicant name in the feedback acknowledgement. | Submission returns a narrow receipt. Unusable context is omitted while preserving the feedback text; admin name/link enrichment is limited to reviewable records. |

## Email delivery

| Item | Before | After |
| --- | --- | --- |
| X22 — Recipient diagnostics | A failed old-address security notice could be reported under the account's new address; confirmation mail could show the inverse mismatch. | Diagnostics retain the actual attempted recipient. Older records lacking that evidence show unavailable rather than guessing from the current account. |
| X23 — Retry cadence | An unrelated submission or opening action could immediately retry every old temporary/quota failure. | New notices still send promptly. Prior failures follow scheduled retry eligibility, reducing repeated work and token churn. |
| X27 — One-time notices | Two workers could send notices for different openings against the same one-time subscription before either consumed it. | Consent ownership spans deliveries and active attempts. Competing list-only notices defer; independently authorized application notices still send without incorrectly claiming list completion. New consent remains protected from an older acknowledgement. |

The email fix prevents the identified concurrent-send race. An external provider timeout after
possible acceptance still cannot provide an absolute exactly-once guarantee.

## Costs and eval/operator tools

| Item | Before | After |
| --- | --- | --- |
| X16 — Cache counts | “Uncached” could count provider replies while “cached” counted individual dimension results, producing misleading comparisons. | Cached and attempted uncached result units are comparable; provider replies remain a separate quantity. Failed attempts are included where indicated. |
| X28 — Rank estimates | Historical dollar amounts could ignore a route-price or discovery-count change. A new opening could omit matching against another opening's criteria. | Compatible historical usage is repriced for current work, including discovery count and global matching history. Estimates remain approximate rather than guaranteed ceilings. |
| X01 — Fixture identity | A case's declared family could disagree with its file/endpoint, confusing Judge and run identity. | The owning family is authoritative and conflicting metadata is rejected; the editor does not offer the conflicting choice. |
| X02 — Eval expectations | Misspelled flag categories and loosely typed pet counts could create misleading passes or failures. | Expectations validate against the supported vocabulary and require unambiguous count types. |
| X03 — Model comparisons | Incomplete/invalid repeats could appear successful or stable; known usage could be lost after an error, and compared models could receive different fixture snapshots. | Comparisons share captured inputs, retain known usage, and distinguish invalid/incomplete output from legitimate contested disagreement. |
| X04 — Copied Rank experiments | A raw database copy could omit committed data; opening and effective settings could differ from those the operator intended. | Experiments take consistent SQLite snapshots, require an explicit opening, apply effective settings, and report only their own new scoped result. |
| X29 — Failed eval case | One exception could discard the batch's other completed structured results and its history record. | Successful evidence and explicit case errors remain in an incomplete batch. Cancellation remains separate and no automatic paid retry is added. |
| X30 — Stability concurrency | Repetition count could exceed the configured worker limit even when only one worker was requested. | The request respects that limit while retaining every repetition. |

## Responsiveness and boundaries

- Choosing a reconciled copy now returns the accepted answers directly, removing a follow-up read.
- Pending-email visibility refresh uses one application request instead of two.
- Trace refresh preserves what the administrator is reading; derived views still refresh without
  an awaited completion barrier.
- Unrelated actions no longer repeatedly retry old failed emails, and unavailable selected-household
  controls no longer issue futile writes.
- Stability evals take additional waves only when their repetition count exceeds the chosen worker
  limit. An ordinary eval batch can finish its requested remaining cases after an individual failure.
- Committee judgment, submission-time age, automatic valid-cache reuse, the unranked state with no
  positive priorities, hosted fixture-edit restrictions and uncapped evals remain in place. No model
  prompt or judgment policy was changed.

Verification and the commit map are in [the implementation record](project-audit-2026-10-06-follow-up.md).
The current production preview concerns retention dates only; it does not establish which other
bug paths were previously encountered by users.
