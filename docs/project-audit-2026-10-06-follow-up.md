# Follow-up checks and a convergence plan — 2026-10-06

**Status: checking complete; runtime fixes not started.** Clean `main` baseline at
`c99f418`, after C01–C12. This round deliberately follows operation sequences and
recovery boundaries rather than treating another broad source read as sufficient.

## Findings

### R01 — A populated historical migration calls a newer schema (P2)

Migration `1c2d3e4f5a6b` imports current runtime configuration/provenance helpers to
assign analyses when several openings exist. Those helpers now load selected AI
results through `application_ai_selections`, a table created by a later migration.

**Reproduction:** build the schema at `f0a1b2c3d4e5`, insert two synthetic application
openings and a submitted application/participation, then upgrade to head. It fails
with `sqlite3.OperationalError: no such table: application_ai_selections`. The same
two-opening database without the application takes the empty-pool path and upgrades,
which explains why empty-schema coverage did not expose it.

**Recommendation:** historical migrations must use their own revision's schema,
not mutable current ORM/services. Keep the one-opening preservation rule and use
revision-local queries for any safe disambiguation. Leave genuinely ambiguous old
analyses unscoped rather than inventing ownership. Add a populated multi-opening
upgrade regression and an old-snapshot restore regression. No compatibility shim
or database reset is needed. This affects upgrading/restoring that older shape,
not ordinary requests against the already-current database.

**Anchors:** `backend/alembic/versions/1c2d3e4f5a6b_opening_specific_workflow.py:303`;
`services/ranking/provenance.py`; `services/applications/screening_results.py`.
**Latency:** migration/recovery work only.

### R02 — Eval receipts have no lifecycle beyond their first refresh (P2)

The recent reconciliation protects an exact unrecorded receipt while handling the
history request made by that summary. It does not retain that receipt's provenance
for subsequent actions. Current validity also comes from history rows, so an empty
history cannot certify or expire a delivered result after a fixture edit.

**Reproductions:** two controlled hook sequences with synthetic results:

1. Stored A=0.1; run produces A=0.8, but telemetry fails. Its immediate history
   refresh correctly preserves 0.8. A subsequent free `refreshHistory()` replaces
   it with the older stored 0.1 despite unchanged inputs/model/prompt. Brief or case
   saving reaches the same reseeding path.
2. With no stored history row, an unrecorded passing score 0.8 is displayed. Change
   the case's expected minimum to 0.9 and call the real case setter. Empty history
   returns before validity reconciliation, so the old result remains current/passing.

**Recommendation:** give delivered receipts an explicit view-owned lifecycle until
superseded, invalidated by actual input/config changes, or disposed with the view.
Current input/config metadata must be obtainable independently of whether history
exists. Keep one clear rule for choosing stored versus delivered outcomes, preferably
as a small pure reconciliation function with sequence tests. Reuse existing run IDs,
fingerprints and mode/case identity; avoid another persistent result store or generic
workflow engine. Editorial note changes should retain valid results; label changes
should expire them. Do not trigger model work automatically.

**Anchors:** `frontend/src/components/evals/useEvalRunner.ts:63` (`loadLastRuns`,
empty-history return, reseeding); `setCases` and `refreshHistory` callers.
**Latency:** use the existing reads and local reconciliation; no synchronous model wait.

### R03 — Restore can revive revoked or already-used credentials (P2)

Restore preserves deletion facts and database identity high-water marks, then copies
the snapshot's other tables into the live database. A snapshot taken before a session
was revoked contains that session with `revoked_at` unset. Restoration can therefore
undo the revocation while the original credential is still within its lifetime.
Successful logout intentionally retains the HTTP-only cookie so a late response does
not clear a newer sign-in; server-side revocation is consequently the security boundary.

**Reproduction:** in an isolated file-backed database, create an allowlisted synthetic
member/session, take a snapshot, revoke the session, and verify authentication fails.
Restore the snapshot and authenticate with the same credential. It succeeds. A one-time
committee link consumed after that snapshot is also redeemable again after restore.
Both were rejected immediately before restoring. No real
credential, applicant data, email or production database was involved.

**Recommendation:** before publishing a restored snapshot, invalidate restored session
credentials and review the corresponding one-time-link/retry-intent recovery rules.
Fresh sign-in after recovery is preferable to reviving logged-out credentials. Apply
this in the isolated prepared database so a failed restore cannot alter the live one.
Keep FK/audit identities intact and cover restored credentials through actual auth
helpers. Ordinary application latency is unaffected; recovery requires reauthentication.

**Anchors:** `backend/app/services/backup.py:143`; `api/auth.py:123`;
`services/auth/passwordless.py` authentication/revocation.

### Q01 — Define what restoration is allowed to roll back

The same synthetic restore sequence also restores the text and active state of a note
deleted after the snapshot. This is an observed consequence of point-in-time restore,
but the intended policy for ordinary note edits/deletions needs an explicit decision.
Do not silently promise that every ordinary edit survives recovery.

I recommend separating ordinary recoverable application history from facts that must
remain effective after rollback: credential revocations, application erasure, consent
cancellation and access removal. The existing application-deletion ledger covers one
part of this already. Decide whether note-deletion receipts also belong in that group.
Do not preserve every operational table blindly; doing so can create inconsistent
foreign keys and mixed generations. Production recovery-policy changes need approval.

## Why repeated audits are still producing findings

The earlier audits were broad, but many regressions exercised one corrected operation
and its immediate response. Subsequent operations and data-dependent recovery branches
were not always included. R02 is a concrete case where the recent fix was incomplete;
the existing test covered the first refresh, not the receipt's later lifetime. R01
distinguishes an empty schema from a populated historical schema. R03 crosses from
revocation into restoration, spanning two otherwise locally correct services.

Some implementation changes also introduce new states that deserve a fresh review.
That is a reason to test the resulting contracts across operations, rather than keep
adding branches and then call a green suite comprehensive. Test count is not evidence
that these specific paths are covered. I should report the covered invariants and
remaining boundaries explicitly when closing a campaign.

## A better next step: one bounded stabilization campaign

### 1. Start with a contract matrix

Before editing, record each protected invariant, its authoritative state and its
operation sequence. This is a coverage map, not a new runtime framework.

| Area | Invariant to preserve | Required sequence coverage |
| --- | --- | --- |
| Applicant drafts | An acknowledgement cannot erase newer answers or another consent lifetime | save/submit → delayed body → other-tab write → cleanup → focus/logout |
| Committee notes | A create attempt is replayable; deleted text does not return through ordinary retry | create → lost acknowledgement → edit/delete → retry → application purge/restore |
| Eval results | Valid delivered output survives unrelated refreshes; changed inputs stop counting current | run → persistence success/failure → second refresh → other mode → note/label/config edit → remount |
| Opening decisions | Finality and selection exclusion survive competing actions | choose → withdraw/select elsewhere → delayed commit → retry → refresh |
| Authority/consent | An earlier grant cannot defeat later revocation without an explicit recovery policy | issue → revoke/remove/cancel → queued work → restore → replay |
| Historical schemas | Upgrade uses the schema present at that revision and preserves genuine data | populated prior revision → multi-opening upgrade → restore → application reads |
| Shared identities | Every consumer compares the same semantic identity | write/run → serialization → SQL filtering → UI lookup, with Unicode/quotes/backslashes |

### 2. Add targeted sequence tests using the existing tools

Use pytest/Vitest and the existing synthetic DB/API/hook fixtures. Start with two
actors, two resources, two modes and a small set of representative identity values.
Vary delivery order and failure point explicitly: headers/body delay, 503, malformed
acknowledgement, failed persistence, resource/account replacement and restore.
Check the invariant after each operation, not only the last response.

Use deterministic bounded schedules or seeded operation lists where combinations are
useful. No new test dependency is required to begin. Avoid the Cartesian product of
every UI state; choose interactions from the contract matrix and expand when a witness
reveals another meaningful boundary. Test the actual API/storage boundaries, not a
second copy of implementation logic.

For each confirmed defect, first show that the regression fails against the old
behavior, then fix it and keep the invariant assertion permanently. Temporary witness
probes must not become tests that enshrine the defect as expected behavior.

### 3. Review each fix through its whole impact

After a fix, revisit all consumers of the changed state: retries, deletion, refresh,
restore, rendering and error handling. Prefer fewer competing state representations
and a named pure decision function when that makes correctness easier to inspect.
Inspect removed guards or deliberately perturbed ordering in isolated tests to verify
the regression actually detects the failure. Do not introduce global locks or caches
just to make schedules disappear.

### 4. Define completion before starting

The campaign can include confirmed in-scope follow-ups without another authorization
for each small batch. Ask only about actual product choices, material latency tradeoffs,
destructive operations and production changes. Commit coherent tested groups.

Close after the agreed high-risk matrix is covered, full checks pass, and two closure
passes from different perspectives find no additional actionable P1/P2 issue. One pass
walks user/API sequences; the other starts from persistence, recovery and invariants.
Use a fresh reviewer for the final pass when available and authorized. This reduces
iteration; it cannot guarantee that every possible future defect is gone.

Keep minor cleanup separate from release-blocking correctness and do not restart the
whole campaign for a speculative naming preference. Record unresolved product decisions
and excluded scopes, including A04, instead of representing them as completed work.

## Verification and scope

- Baseline backend: **1,072 passed, one existing platform skip**; Ruff passed.
- Baseline frontend: **329 passed**, TypeScript/build/ESLint passed.
- Watchdog: **nine passed**, TypeScript passed.
- Temporary focused probes confirmed two eval sequence defects, the populated migration
  failure, session/one-time-link revocation rollback and the note-deletion restore consequence.
  Their passing assertions reproduce current behavior; they are not fixes.
- No real model call, email delivery, production inspection/change, dev-server start,
  browser reload, database reset or push occurred. All recovery probes used synthetic
  temporary databases. Runtime source remains unchanged in this checking round.

**Recommendation:** address R01–R03 as part of this bounded stabilization campaign and
settle Q01's recovery policy explicitly. Do not start another unrestricted refactor.
