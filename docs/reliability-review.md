# Reliability review and completion

Use one audit-and-fix task for reliability cleanup, with one issue list and a final
review of the complete workflows. A passing regression for one reported bug does
not finish a concurrency change: inspect its related actors, resource boundaries,
failure paths, and callers before committing.

## Review by contract

| Workflow | Contract to check | Faults to inject |
| --- | --- | --- |
| Applicant saves and submission | A response acknowledges its captured answers and revision; permanent decisions constrain edits | Delayed responses, newer typing, other-tab saves, selection or withdrawal during a request |
| Browser draft storage | Consent controls every write; clearing cannot resurrect data or erase newer work | Queued saves, clear/re-opt-in, old exit/new sign-in, quota or unavailable storage, leaving during debounce |
| Committee access | Authority and last-admin/seed-admin constraints hold through the mutation commit | Cross-removal and cross-demotion, stale loaded users and roles, concurrent invitations |
| Opening lifecycle and email | A permanent outcome and its notification intent agree; retries remain independently actionable | Duplicate confirmation, stale audience, cancelled credentials, preparation/provider failure |
| AI inputs and cache selection | The prompt, cache identity, displayed output, and provenance refer to the same captured work | Content/settings changes, mixed hits/misses, switching back to cached settings, failed candidates |
| Run ownership and transport | Stopped or superseded work cannot commit; cleanup releases only its acquisition | Lease expiry/replacement, disconnect before body, send failure, silent provider, queued worker calls |
| Spending and metrics | Known usage survives downstream failures; cache units and provider replies remain distinct | Returned reply followed by validation/storage error, partial retries, whole-phase failure, historical unknown measurements |

For each finding, record a reproducible trigger, the violated contract, the owner
of the fix, and the regression that proves it. Keep unknown provider billing and
irrecoverable historical measurements explicit; do not replace missing facts with
inferred precision.

## Finish the task

1. Map the affected read/write owners and related workflows before editing.
2. Fix verified defects at their ownership boundary. Add abstractions only for a
   real shared responsibility; avoid unrelated refactoring or new product policy.
3. Run the original reproduction and its neighbouring matrix cells. Exercise the
   real boundary where appropriate: two database sessions, ASGI transport, browser
   events, and incomplete provider replies, rather than only helper functions.
4. Measure meaningful waiting costs: request/query counts, transaction duration,
   and whether derived refreshes unnecessarily block the UI. Protect saves and
   permanent decisions while keeping derived views responsive.
5. Run the required suites, linters, build, migration preservation tests, and diff
   checks before committing. Apply additive migrations in place; never reset data
   or start development servers as part of the review.
6. Perform a fresh review of the resulting workflows. Fix confirmed related gaps
   within the authorized scope in the same task, then recheck affected cells.
7. Stop after the agreed scope has no remaining reproducible, material findings in
   the final review. Report coverage and limits. A clean review is evidence, not a
   guarantee that software contains no undiscovered bugs.

Commit and push authority remains task-specific under `.clinerules`. A single
comprehensive task can authorize multiple focused commits and a final push; it
does not create standing authority for future tasks. Product decisions, destructive
operations, and external actions still require their appropriate authorization.

## This round's regression coverage

The browser tests cover consent lifetimes, cross-tab clearing, later sign-in data,
serialized writes, delayed acknowledgements, quota/denied reads, and the actual
leaving-page warning. The access tests run concurrent removal/demotion combinations
in separate SQLite request sessions. Accounting tests exercise failures during
decomposition, post-reply processing, matching, scoring storage, and best-effort
consolidation; migration tests preserve existing ledger rows and leave historical
cache units unknown. These augment the existing save-revision, lifecycle, cache,
lease, and real ASGI disconnect regressions.
