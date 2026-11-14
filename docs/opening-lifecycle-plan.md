# Two-stage opening lifecycle

Implemented 2026-11-14. Local migration applied; production deployment is not included.

## Product rules

- Creating a vacancy creates a Preparing opening with a required application deadline.
- Preparing openings are visible to administrators, not offered in applicant forms, and send no mail.
- Creation temporarily protects currently available submitted, non-withdrawn, non-selected applications. Protection is separate from participation and never enrolls applicants.
- Open applications is a separate explicit action that publishes the opening and atomically queues its previewed notification audience. The actual open date is the publication date.
- A Preparing opening can be filled from a retained applicant after interest is confirmed outside the system, or cancelled without opening applications.
- Protection lasts through the latest applicable application deadline, inclusive in Pacific time. It preserves the original decision-based retention date.
- Jeff explicitly chose to release protection when an opening ends or its deadline is shortened. Other active openings can continue protection. A record whose ordinary expiry has passed may become immediately unavailable and due for purge.
- Extending or creating an opening never revives an expired application, even if maintenance has not physically deleted it.
- Submission protects the applicant through the last relevant decision, followed by one year if unsuccessful or seven years after selection.
- Ordinary withdrawal, selected-household immutability and privacy restrictions continue to apply.

## Implementation sequence

1. Add Preparing lifecycle behavior and durable opening-to-application retention protection. Add an additive migration; preserve existing openings and applicant data.
2. Centralize effective retention checks for ORM reads, SQL scopes, authentication, mail, direct selection and purge. Serialize protection changes with the existing SQLite writer lock and recheck expiry under that lock.
3. Separate creation from publication. Give each action retry-safe identity and validate saved opening facts and notification audience before publication. Require an unelapsed deadline to publish.
4. Adapt direct selection to finalize an existing Preparing opening. Cancellation is a permanent no-selection decision without enrolling or rejecting the protected pool.
5. Update opening creation, launch preview, editing, direct selection and cancellation UI. Show the planned deadline while Preparing and actual open date after publication. Preserve stale-response and uncertain-save handling.
6. Update SPEC, collection notice and API documentation. Public privacy policy lives in the sibling penta-coop-website repository; its retention explanation must be updated before deployment.

## Verification

- Day 363 creation / Day 365 ordinary expiry / Day 400 deadline: retained through Day 400; unavailable Day 401 without submission.
- Submission before the deadline survives closure and deliberation; unsuccessful retention starts after the final decision.
- Overlapping openings, shortening, cancellation and early selection release only the applicable protection.
- Extension after expiry and creation after expiry never restore old data.
- Purge versus creation, extension, withdrawal and selection have serialized outcomes; deleted records leave no protection links.
- Preparing is absent from public/applicant opening choices and cannot accept submissions or queue vacancy mail.
- Publication is retry-safe and cannot duplicate announcements, publish an ended opening or use stale dates/audience.
- Direct selection sends no opening or unsuccessful mail, retains the selected application for seven years and revokes its access.
- Migration from populated data preserves existing state and passes integrity/foreign-key checks.
- Run backend Ruff and pytest, frontend build and relevant interaction tests; inspect the complete admin journey in the existing local Chrome tab.

## Design boundary

Use existing opening, participation, retention and outbox owners. Do not copy applicant answers or create participation solely for retention. Existing historical decisions remain immutable. No production deployment or email sending is part of local implementation.


## Verification outcome

- Backend: 1,330 passed, one skipped; 37 focused lifecycle/authority checks also passed after the final lock-order correction. Ruff passed.
- Frontend: production build passed; 23 opening-editor, publication, direct-selection and panel interaction tests passed.
- Local migration: applied in place, SQLite integrity OK and zero foreign-key violations. Populated historical migrations and restore tests passed.
- Public privacy policy: source updated in the sibling website repository; Eleventy built the paragraph into privacy.html. Existing unrelated members-page changes were preserved.
- Browser visual review: deferred because Chrome DevTools could not establish a browser connection. No development server was started.
- Source review covered release on deadline shortening/finalization, overlapping protections, expiry before extension, opt-in participation, notification retries, and immutable decisions. The purge race test verifies protection acquired after sweep discovery is honored at the locked recheck.

The protection table remains in the existing centralized schema module, alongside openings and participation; it contains only foreign keys and does not justify splitting the shared model catalog. Retention checks add a SQL existence check only when an individual record is beyond its ordinary deadline; list queries apply it in SQL. Opening changes capture the available pool under the existing SQLite writer boundary. No new AI calls or external requests are introduced by retention protection.
