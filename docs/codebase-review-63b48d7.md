# Codebase review of 63b48d7

November 25, 2026. Four passes produced five open findings. The household rules deserve first attention because the current defaults affect who enters committee ranking. Findings 2 and 3 concern applicant privacy.

## 1. The advertised household requirements disagree with initial screening

Opening announcement emails use a fixed sentence for each bedroom count. The committee default is copied from the previous opening, or initialized with a minimum of one child and maximum of four. The applicant's opening cards show the bedroom count, charge and dates. They omit the household requirements specified for those cards.

In isolated databases, clean fictional applications produced the following results. The first four cases went through normalization, committee application listing and the Rank eligibility union. The last case went through normalization and the same deterministic filter.

| Advertised home | Fictional household | Current result |
| --- | --- | --- |
| 1 bedroom, 1 or 2 adults | One adult, no children | Listed as ineligible for too few children and excluded from Rank |
| 2 bedrooms, 1 or 2 adults plus 1 or more children under 18 | One adult, one young child | Eligible and included |
| 3 bedrooms, 1 or 2 adults plus 2 or more children under 18 | One adult, one young child | Eligible and included |
| Same 3-bedroom home | One adult, two young children | Eligible and included |
| Same 3-bedroom home | One adult, five young children | Flagged for too many children under the default maximum of four |

Jeff confirmed that the three descriptions in the **Unit Preference** screenshot should supply the defaults and the email should use the opening's actual requirements when an admin changes them. Recommended design:

- When an admin chooses the bedroom count for a Preparing opening, prefill the household requirement. Keep the ordinary action to a quick review. Offer structured edits for exceptions, and show the resulting **Household** sentence beside the charge and dates before “Open applications.” If the bedroom count changes after a manual override, require the admin to review that override again.
- Persist the approved values on the opening. Use them for both email variants, the applicant card and the initial committee household rules. Keep the public sentence stable after publication so later mail retries describe the same vacancy. A member's private review settings must never change the announcement.
- Start with household composition as the configurable public criterion. Continue showing the existing charge and dates. Add another public criterion, such as income, only when the co-op intends applicants to rely on it and an administrator can confirm its exact wording and values. A checkbox for every internal rule would make it easy to publish private preferences by mistake.
- Jeff confirmed the one-bedroom default is **1 or 2 adults and no children**. Set both child-count bounds to zero. Verify that one or two adults with no children pass the household-size check and that adding a child fails it. For the two larger homes, “or more” implies no upper child limit unless the opening explicitly sets and discloses one. Preserve deliberate per-opening and per-member decisions when introducing defaults. Historical announcements should keep their original meaning.

Acceptance should compare exactly the same households across the public card, email, committee default and rankable pool for all three sizes. Include an overridden opening, a private member rule, the age-18 boundary, and a household above four children. Reuse the existing publication transaction and template rendering. The normal path needs no extra network request or model call. [Default inheritance](../backend/app/services/eligibility/rules.py) · [Filter semantics](../backend/app/domain/hard_filters.py) · [Email wording](../backend/app/services/openings/vacancy_notifications.py) · [Applicant cards](../frontend/src/applicant/ApplicantFormSections.tsx)

## 2. Expired applicant mailboxes remain visible in the delivery dashboard before purge

The authorized admin delivery-issues endpoint selects stored recipient addresses without applying applicant retention. A synthetic terminal delivery failure appeared while the application was retained. After moving the application onto its Pacific expiry date, the same HTTP endpoint still returned its full mailbox. After running physical purge, it disappeared. This is a separate reader from the feedback and ranking projections fixed earlier.

Use the existing protection-aware retention predicate for applicant-linked delivery details, including checking the applicable owner for draft-linked items. Preserve useful operational counts while suppressing identifying details at expiry. Test retained, protected, due-before-sweep and purged cases. Apply the check in the existing report query, without a query per delivery. [Admin endpoint](../backend/app/api/dashboard.py) · [Delivery projection](../backend/app/services/email/outbox.py) · [Retention predicate](../backend/app/services/applications/retention.py)

## 3. A failed “application unavailable” notice can keep a mailbox indefinitely

When intake is closed, the guest flow can send an unavailable notice to a mailbox with no application or draft. A terminal failure clears the retry intent but keeps the recipient. There is no applicant owner to purge, and the scheduled cleanup for ownerless failures selects only vacancy-opening mail. In the probe, maintenance completed at days 31 and 366. The failed address was still stored and returned by the issue-list service. An accepted control cleared its recipient immediately.

Extend the existing troubleshooting window to terminal, ownerless unavailable notices. I recommend the same 30-day window already used for list-only vacancy failures. Keep genuinely queued retries and applicant-owned records under their existing policies. Test the retention boundary with the normal daily job and verify unrelated records survive. This can reuse the current cleanup statement. [Guest notice path](../backend/app/api/applicant/guest.py) · [Notice creation](../backend/app/services/email/transactional.py) · [Delivery failure handling](../backend/app/services/email/delivery.py) · [Scheduled cleanup](../backend/app/services/email/outbox.py)

## 4. Paid work can start after the pool disappears or the opening is archived

The paid endpoints admit the request and return a stream. Provider work starts later. Full Rank captures the pool again in its stream, but an empty pool passes the retained-source check. With one eligible applicant at admission, withdrawing that applicant in a second database session before consuming the response produced five discovery calls containing an empty pool, one decomposition call and a successful new analysis with zero source IDs. The unchanged control scored one applicant.

In a separate sequence the admin recorded a permanent no-household decision after admission and before the first provider call. Full Rank then made seven calls and published an analysis. Screen and score-current each made one call and reported success in the equivalent sequence. All calls used the mock provider.

Check opening finality and applicable pool eligibility at the transition into paid work, and guard publication against a final decision that wins during the run. Define the ordering for an already-running job and an administrator's final decision so the result is explainable. Preserve known cost for calls already made. Reuse the opening and run ownership mechanisms with short transactions. Acceptance should cover both orderings on all three endpoints, zero calls when the decision wins before dispatch, empty Rank pools, correct receipts and lease release. [Rank admission](../backend/app/api/ranking/run.py) · [Rank snapshot and worker](../backend/app/services/ranking/pipeline.py) · [Screen](../backend/app/api/screening.py) · [Score-current](../backend/app/api/ranking/score_current.py) · [Opening decision](../backend/app/services/openings/selection.py)

## 5. A delayed read can hide a failed invariant after re-baselining

The Invariants tab loads the old result on mount and allows an administrator to re-baseline while that read is pending. In the real React component, a successful re-baseline response displayed seven dimensions and a fictional invariant breach. When the older read completed last, the display reverted to three passing dimensions and the breach disappeared. Reversing completion order correctly kept the seven-dimension result. This probe used controlled HTTP responses. The observed defect is the displayed result.

Fence the initial read when re-baselining starts, using the existing request-ordering pattern. Only the current operation should update the visible result or error. Test both completion orders and a failed write, with the confirmed result and retry state visible. No additional request or fixture write is required. [Invariant view](../frontend/src/components/evals/InvariantsEval.tsx) · [Existing request scope](../frontend/src/hooks/useRequestScope.ts)

## Coverage and limits

| Pass | Work performed |
| --- | --- |
| Applicant and committee journeys | Traced intake, opening cards and announcements, saved drafts, committee notes, eligibility rules, shortlist filtering and print projections. Rendered all three applicant cards and compared the implemented disclosures with the specification. |
| Data and reporting | Compared normalized households through rule creation, filters, committee listing and Rank scope. Traced eligibility overrides, ranking bands, cost estimates and metrics, cached scores, eval receipts, fixture editing and invariant display. Shared-pool bands are explicitly intended. |
| Failure and recovery | Exercised provider failure with owned and ownerless mail, before and after expiry, plus long-overdue maintenance. Reviewed credential lifecycle, result ownership, SQLite restore preparation and watchdog scheduling. Probed withdrawal and human finalization between paid request admission and execution. |
| Final challenge | Reversed invariant response order, retained valid household controls, compared accepted/failed deliveries and checked physical purge. Traced the Rank finding through Screen and score-current. The earlier watchdog reset established that polling resumed, but did not establish the cause of the prior alarm gap. No new watchdog defect is claimed here. |

Automated checks passed on the unchanged application baseline: **1,398 backend tests passed, one skipped**, the complete frontend suite passed, and **44 watchdog tests passed**. Ruff, frontend lint, the production build and watchdog TypeScript checks passed. Three additional temporary component scenarios covered applicant cards and the two invariant response orders. All additional data, mail and model calls were synthetic or captured.

This review did not exercise production traffic, live identity or mail providers, paid model quality, dependency advisories or physical print output. Production occurrence is unknown.
