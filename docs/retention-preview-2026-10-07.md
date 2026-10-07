# Production retention preview — October 7, 2026

**Result: no retention-date repair is needed for the records present in this snapshot.**
Every assessed application's stored deadline matches the corrected calculation. Nothing was
changed or deleted, and no deployment or migration was performed against production.

Snapshot: **October 7, 2026, 7:09 a.m. Pacific** (`2026-10-07T14:09:31.367594Z`).

| Record group | Count | Stored deadline | Calculated deadline | Changes needed |
| --- | ---: | --- | --- | ---: |
| Submitted, not selected | 232 | September 23, 2027 | September 23, 2027 | 0 |
| Selected household | 1 | September 23, 2033 | September 23, 2033 | 0 |
| Unsubmitted applications | 0 | — | — | 0 |
| Temporary pending copies | 0 | — | — | 0 |

These deadlines are the first day the records become unavailable, using Pacific time; physical
removal follows the maintenance schedule.

Additional checks:

- 233 applications assessed; none excluded for inconsistent or invalid retention metadata.
- No whole-profile withdrawals, missing application deadlines, or outstanding opening decisions.
- One opening exists and has a recorded decision.
- No record is currently overdue; no proposed correction would make a record overdue.
- No dates need to move earlier or later, and no deadline needs to be added or removed.

## Method and boundaries

The existing Toronto machine was suspended. It was resumed through `/health`, which does not
trigger the application's maintenance sweep. The database was then inspected directly over SSH,
without using application routes, importing the application, or invoking a purge/repair helper.

The connection used SQLite URI `mode=ro`, `PRAGMA query_only=ON`, an explicit read transaction,
and an authorizer that allowed only the required lifecycle columns and read operations. The
projection read IDs, submission/withdrawal flags, deadline dates, opening choices, participation
outcomes and opening decision/close dates. It did not read names, email addresses, answers,
notes, credentials or model output. Only aggregate results left the machine.

The preview calculation was checked against the newly implemented retention owner using seven
synthetic cases: submitted, selected, pending decision, withdrawn, empty private selection,
explicit private selection, and a closed last fallback opening. Leap-day handling, the Pacific
date boundary and exclusion of submitted records without participation were checked separately.

The remote result confirmed `query_only=1`, `connection_total_changes=0`, and a closed read
transaction. Production schema revision was `9e0f1a2b3c4d`; the local implementation has not been
deployed. No repair script was installed or left on the production machine.

This is a point-in-time check of surviving records, not a forensic claim about previously deleted
data or applicant-controlled browser copies. The potential date bugs remain worth fixing for future
activity, but they require no backfill for this snapshot. If the relevant data changes before a
later repair/deployment decision, use a fresh preview rather than applying this snapshot blindly.

The implementation and its regression evidence are in
[the comprehensive audit](project-audit-2026-10-06-follow-up.md). The user-facing changes are in
[the behavior summary](audit-fix-behavior-summary-2026-10-07.md).
