# Comprehensive reliability audit, 2026-10-04

Baseline: `7305f9e` on `main`. This task reviews the current implementation and
the 48 commits from October 1 through October 4 together. Existing fixes remain
part of the unified workflow contracts; history is not rewritten.

## Coverage and findings

| Area | Owners and boundaries | Review outcome |
| --- | --- | --- |
| Applicant persistence and browser drafts | Applicant workflows, revision locks, link claims, Web Locks | Reviewed; return-link revisions, discard acknowledgements and browser recovery corrected |
| Authentication and access | Browser sessions, allowlist, credential exchange, revocation | Reviewed; account workspace lifetime and sign-in authority corrected |
| Committee edits and opening lifecycle | Candidate writes, rules, ranking board, publication, decisions | Reviewed; ranking writes stay pending through complete acknowledgement; existing decision and publication fencing retained |
| Email and retention | Durable intents, preparation, provider acceptance, retries, purge | Reviewed; obsolete guest credentials, physical draft clearing and retention revisions corrected |
| AI and run ownership | Captured inputs, caches, worker pools, leases, disconnects | Reviewed; eval transport unified, preflight moved after lease acquisition, vectors publish atomically |
| Spending and operational views | Measured replies, failure records, estimates, current-result selection | Reviewed; failed single passes, criteria storage and interrupted known usage corrected |
| Settings, feedback and eval workspaces | Draft acknowledgement, resource scopes, fixture replacement | Reviewed; first settings save is atomic; existing feedback and fixture ordering retained |
| Database, deployment and operations | Migrations, backup/restore, health, watchdog configuration | Reviewed; record IDs and comparison ownership corrected; restore validates before replacement |
| Responsiveness and maintainability | Queries, awaited refreshes, transaction duration, module ownership | Reviewed; duplicated pool reads and per-dimension commits reduced; ownership clarified |

Confirmed findings will include a reproduction, owning boundary, fix and regression.
Candidates without a demonstrated material failure will be recorded separately
from defects. Checks use synthetic data and local test boundaries; production
changes and real provider judgement are outside this task's authorization.

## Confirmed fixes

- Return-link requests acknowledge the exact saved revision, even when delivery fails or another tab saves during provider I/O.
- Browser recovery acknowledgements expire when another tab replaces that applicant's stored snapshot. Other applicants' writes do not invalidate recovery.
- Confirmed server submission and session exit remain confirmed when local cleanup fails; the browser-copy warning is explicit. Unconfirmed guest discard retains its answers and retry token, and later typing survives a confirmed discard.
- Ordinary HTTP deadlines cover complete acknowledgement bodies. Successful AI streams keep their longer lifetime, remain abortable after headers and close when parsing or consumption fails.
- Committee data, drafts, toasts and pending work belong to an authenticated account's mounted workspace. Sign-out and account switching dispose that workspace; paid runs and eval requests abort with it.
- Ranking mutation queues include response parsing, preventing a board refresh from replacing optimistic state during a delayed acknowledgement.
- Eval streams reuse the worker heartbeat and HTTP disconnect cleanup used by paid runs. Cancellation discards queued cases without waiting for a silent active provider.
- Google and guest creation resolve identities under SQLite's writer. Sign-in authority is reloaded under that same boundary; stale role snapshots cannot reactivate removed access or restore a demotion.
- Opening facts and temporary copies are reloaded after acquiring the writer. Finalization, copy revocation and email changes cannot be bypassed by previously loaded ORM objects.
- Verified email changes, withdrawal and household selection invalidate associated guest copies. Queued delivery cannot issue a fresh old-address credential from an obsolete copy.
- Full Rank and Screen check finality and spending policy after acquiring the run lease. Failed preflight releases its acquisition.
- Screening, score-current and post-reply criteria storage failures retain known spending. Interrupted HTTP cleanup records already-returned usage in an expense-only session after rolling back result work and releasing the lease. It cannot duplicate a completed ledger.
- A candidate's complete score vector and consumed references commit together. A storage failure rolls the entire vector back.
- AI failure logs contain operation and exception class, without provider traceback text or model-produced criterion keys.
- Retention-driven working-copy changes advance the revision once, preserving stale-save detection without changing the retention policy.
- Concurrent first shared-settings saves use the same atomic upsert pattern as eligibility rules.
- Integer database IDs never reuse deleted identities. The migration preserves existing IDs and reserves future allocation above the legacy range, within JavaScript's exact integer range. Temporary comparison deletion detaches its reference and preserves application authentication.
- Explicit temporary-copy and never-submitted-profile deletion leave non-identifying deletion facts. Restore preserves allocation counters, applies the newest deletion bounds, migrates a staged project snapshot and verifies integrity/foreign keys before replacing live data. Ambiguous legacy identity matches fail before replacement.

## Recent commits incorporated

All 48 commits from `ac746c3` through `7305f9e` remain in the current history.
The audit reviews their contracts together:

| Recent work | Integration check |
| --- | --- |
| Request scopes, snapshot acknowledgement, settings/eval drafts and candidate queues | Apply the same rule to return-link saves, account lifetime, ranking acknowledgement bodies and discard |
| Applicant revisions, lifecycle locks and opening snapshots | Refresh ORM facts after the writer is acquired; retain permanent-decision and publication request identities |
| Email outbox, revocation, subscription consent and preparation isolation | Preserve conditional attempt acknowledgement and provider I/O outside the writer; close obsolete guest-copy credentials |
| Captured AI keys, current-result references, coherent boards and score-only plans | Retain input/selection identity while publishing candidate vectors atomically |
| Run acquisition, renewal, fenced commits, ASGI cleanup and queued-call cancellation | Reuse transport cleanup for evals; add expense-only interruption receipts without relaxing result fencing |
| Failed-run spending, dimension units, final counts and history-first estimates | Cover remaining failure boundaries; exclude interrupted attempts from successful-run estimates |
| Coalesced activity writes and SQLite-journal restore | Keep browsing read-only between touches; preserve monotonic allocation across restores |

## Measurements and complexity

Synthetic local measurements, excluding auth, network and provider time:

- Screening preparation for 100 applicants: 15 to 9 SELECTs; ten-sample median 9.65 to 5.32 ms.
- Persisting 20 candidates with 15 dimensions on SQLite WAL/FULL: 300 to 20 commits; three-sample median 415.56 to 194.53 ms.

No provider calls or normal-run commits are added for accounting. Interrupted
cleanup adds one short expense transaction only when usage has already returned.
Identity/sign-in locks cover validation and short writes; provider I/O remains
outside the writer. Google callback database work runs off the async event loop.

`App.tsx` owns authentication; `CommitteeWorkspace.tsx` owns account data.
`WorkStreamingResponse` owns HTTP lifetime; the run subclass adds lease ownership.
`stage_result` makes caller-owned cache transactions explicit. Hard deletion lives
in `applications/purge.py`, not the access-policy module. The large `db/models.py`
remains the cohesive schema registry: its changes are declarations and allocation
metadata, with workflow behavior kept in services. Further cosmetic splitting,
global refresh coordination and speculative caching were not justified.

## Limits

Active provider calls can finish after cancellation; queued work stops and late
results cannot commit. Usage arriving after cleanup and provider billing without a
returned usage record require provider reconciliation; cleanup does not wait for
them. Database failure during expense recording remains a recoverable operational
limitation, not evidence of zero spending. Interrupted cache-unit and latency
measurements remain unknown.

Mock and synthetic checks prove deterministic contracts and fault handling. This
task changes no prompt instructions or judgement criteria and makes no claim about
model quality, production health or measured end-to-end user latency.

## Completion

Final checks: 878 backend tests, 226 frontend tests, Ruff, ESLint and the production
build pass; the watchdog type check and 9 tests pass. Alembic reports one head,
`c83d5f917a2b`. The local migration retained a recovery snapshot and preserved the
exact existing rows across all 33 application tables, with valid foreign keys.
The closure review has no outstanding confirmed material findings in this scope.
No production deployment or real provider calls were made.

The task finishes after every area has a recorded review outcome, confirmed
in-scope defects and their related failure paths are resolved, the closure review
has no outstanding material findings, and required checks pass. Report remaining
limits and deliberate non-changes. Follow `reliability-review.md` for the method.
