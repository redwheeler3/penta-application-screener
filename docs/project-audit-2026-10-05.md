# General project audit — 2026-10-05

**Status: approved implementation complete.** Audit baseline: clean `main` at `f20ff82`, two authorized implementation
commits ahead of `origin/main`. This audit replaces the completed report; its history remains
in Git. The findings below describe that baseline; the implementation record reflects
the user's subsequent decisions and the current fixes.

## Decisions and implementation record

- **A04 deferred by the user.** No new synthetic-source gate or nested quote scrubber was
  implemented. The privacy finding remains documented; unconditional safety claims were
  corrected as documentation cleanup, without changing that export policy.
- **A06 / D03:** local editing only. Hosted cases/briefs/invariants and eval run controls remain;
  hosted mutation controls are omitted and the API refuses file writes. Committed local edits
  reach hosted evals through a manual deployment. Git push alone does not deploy.
- **D01:** Evals and Observability are admin-only, including the ranking audit endpoints.
  Ordinary member screening/ranking remains available, without the operator discovery
  narrative in current/board responses. Local fixture writes recheck admin
  authority before touching files.
- **D02:** evals remain deliberately uncapped. No engineering budget, spending cap or new
  cost-tracking subsystem was added. The existing spend/call-count confirmation remains.

| Item | Implementation status |
| --- | --- |
| A01 | Displayed boards refresh within the same analysis through the existing intake/focus owner; pending edits/live discovery retain ownership; settings trigger free adoption/background reads. |
| A02 | Shared nested family contracts validate saves and readers; cases/baselines share UTF-8 I/O, short file locks and atomic publication. Regressions cover Unicode and Windows open-reader replacement. |
| A03 | Missing scores/ranges are nullable in live and saved JSON, render without crashing, and retain failure reasons. |
| A04 | Deferred; source/quote safeguards remain unchanged. |
| A05 | Export vectors use the source opening cohort/criteria. Provenance uses captured configuration and selected producers; missing/mixed history remains unknown without new identifiers or migrations. |
| A06 | Local-only corpus mutation capability is enforced and exposed in the catalog; deployment ships the committed corpus. |
| A07 | Uncertain direct-selection acknowledgements preserve facts, refresh openings in the background and require review before retry; definite refusals remain editable. |
| A08 | Approved motivation helper already committed in `2861ab0`. |
| A09 | Unused unbound applicant interfaces removed, factory aliases clarified, manual-test clients explicit, obsolete CLI instructions and documentation corrected. |

The new implementation adds no model calls, blanket synchronization layer, database IDs or
migration. Normal saves do not wait for derived-view refreshes. A visible board gains one
background board read on the existing intake interval, replacing its ID-only focus read;
hidden boards keep the inexpensive focus check. Uncertain decisions reconcile in the
background. Eval schema/export work stays on operator paths.

Implementation commits:

- `976bf5b` — eval contracts, fixture scope/provenance, local editing and admin boundaries.
- `5fc28da` — same-analysis displayed-board refresh and live/pending-work ownership.
- `0975b78` — truthful direct-selection acknowledgement recovery.
- `f0e1308` — remove redundant unbound applicant API entrypoints.
- `d59b857` — one fixture-file lock for mutation ordering and Windows handle lifetime.

The file I/O consolidation also uses a single lock per existing fixture path for both
read/modify/write and Windows handle lifetime; there is no separate family-lock registry.

## Scope and method

Cover the whole application, tests, migrations, operational scripts and current documentation
for readability, correctness, reliability, redundancy and simplicity. Include latency,
cache/display/readiness agreement, applicant and committee journeys, and recent changes.

1. Inventory and ownership: module graph, dead/redundant code, names, shared contracts and docs.
2. Backend behavior: transactions, authority, lifecycle/retention, cached results, AI/cost streams,
   email delivery, recovery and operational boundaries.
3. Frontend behavior: complete journeys, scopes/acknowledgements, background refresh, editable
   drafts, action affordances, request counts and UI/backend agreement.
4. Consolidation: reproduce credible findings using synthetic data, cross-check siblings,
   distinguish confirmed defects from optional improvements, verify baseline and finish report.

## Findings

Four review passes and baseline checks are complete. The findings below have
been reproduced or checked against their actual consumers. Priorities describe the
consequence if the path is exercised; they do not assert that a production incident occurred.

| Item | Recommendation | Evidence | Priority |
| --- | --- | --- | --- |
| A04 | Fix committable export privacy/source checks first | Two synthetic reproductions | P1 |
| A01 | Refresh loaded boards after same-analysis shared changes | API and real-hook reproductions | P2 |
| A02 | Validate nested eval cases and publish fixtures atomically | API/loader reproduction; baseline writer inspection | P2 |
| A03 | Handle missing eval scores as nullable values | API, persisted JSON and renderer reproductions | P2 |
| A05 | Scope fixture vectors and use truthful provenance | Two synthetic reproductions | P2 |
| A06 | Make hosted corpus editing policy explicit | Image, mount and route configuration | P2 / decision |
| A07 | Reconcile uncertain direct-selection outcomes | Real component reproduction | P2 |
| A09 | Remove redundant unbound applicant interfaces and obsolete instructions | Runtime reference and consumer review | P3 |
| A08 | Improve motivation helper | User approved; implemented in `2861ab0` | Complete |

### A01 — Refresh the displayed ranking when shared inputs change (P2)

`frontend/src/hooks/useRanking.ts` checks whether the latest analysis ID changed. Scoring
against retained criteria, screening, eligibility changes and other shared changes can alter
the board without creating an analysis. The workspace's intake refresh updates applications,
dashboard and cached-result references, but does not reload an already displayed board unless
this client's cache adoption reports a change. Another client's completed work can therefore
leave the board stale until navigation or reload, even while counts/readiness elsewhere update.

**Evidence:** a synthetic API probe changed the board from one to two scored applicants with
the same analysis ID and `refresh_cached_results == False`. A hook probe then supplied that
updated board: the focus check kept the old one-scored board and made no second board request.
Settings saves also refresh the dashboard without immediately reconciling displayed scores
and selected cached outputs; distinguish that bounded background delay from the indefinite
same-analysis issue.

**Recommendation:** give the displayed board one clear refresh owner. Reconcile on relevant
focus/intake/settings events using the existing board endpoint and request scopes. Preserve
pending member edits and live-run ownership. Avoid a second revision identity or a global
state framework. Cover same-analysis score updates, screening/eligibility changes, purge,
settings changes with matching cached results, pending writes and account/opening switches.
**Latency:** background reads only; reuse or replace the current ID-only check and avoid
fetching hidden boards. Do not block saves or add model calls.

### A02 — Validate eval cases before publishing them (P2)

`backend/app/evals/case_store.py` validates the top-level envelope, but not the nested shapes
required by each family's loader. The structured editor allows removal of nested fields.
A normal edit can therefore save a case which breaks subsequent catalog loading/runs.

**Evidence:** removing `given.dimension.high_end` from a valid synthetic scoring case was
accepted with HTTP 200; the actual `load_golden` reader then raised `KeyError('high_end')`.
This is not a path-traversal issue: fixture files are allowlisted and replacement is atomic.

**Recommendation:** perform family-aware, side-effect-free validation before atomic publish,
using the same contracts as the consuming loaders. Return a useful field error and retain the
prior file on rejection. Test nested required fields/types and valid cases for all families.
Keep the flexible editor; do not create a parallel generic schema/validation framework.
Also bring baseline recording through the same small atomic-file publication primitive:
`fixture.record` uses `Path.write_text` directly, so concurrent invariant reads can encounter
a truncated/incomplete JSON file. Case saves already use a flushed temporary file and atomic
replacement; preserve that design and share the publication boundary, not a generic store.
**Latency:** small local validation on explicit operator saves; no applicant-path cost.

### A03 — Represent missing eval scores as absence throughout (P2)

`backend/app/evals/scoring.py` uses NaN for a missing model score. An all-missing scoring
stability run yields NaN bounds, which serialize as null in the response but are stored as
nonstandard JSON in the eval run. `frontend/src/components/evals/EvalResults.tsx` assumes
numeric bounds and calls `toFixed`, crashing the results view on that real response shape.

**Evidence:** two mock empty scoring reports produced HTTP 200 with null range bounds;
SQLite `json_valid(result)` was zero. Rendering the exact response shape threw at `toFixed`.
Consistently missing output being marked stable is a separate consistency measurement, not
proof of correctness; do not redefine stability to disguise the missing score.

**Recommendation:** use nullable finite scores/bounds in the producer, persisted JSON and
frontend contract; show a concise missing-score state and retain each failure reason. Do not
substitute zero. Cover all-missing, partially missing, valid and saved-history cases.
**Latency:** none; simplifies an inconsistent data contract.

### A04 — Enforce the actual data boundary for committable eval exports (P1)

`backend/app/evals/fixture.py` calls its output PII-safe. It drops top-level narratives and
top-level `why_it_differentiates`, but retains nested discovery dimensions in the matching
audit, including the same applicant-quoting field. Removing names/IDs does not make model
prose safe to commit. Baseline recording has no synthetic-source gate.

Separately, `backend/scripts/_harvest_common.py` trusts the analysis's historical synthetic
flag, while harvest candidates are read from current applications/results. A real applicant
can join a formerly synthetic opening after that analysis was created.

**Evidence:** a fabricated private marker in a nested discovery justification survived the
fixture serializer while the top-level narrative was removed. A synthetic-analysis probe
then added/scored a nonsynthetic application: the guard still passed and the actual scoring
harvest candidates included it. No real applicant content was exported in this audit.

**Recommendation:** require trustworthy synthetic provenance for the actual applications
and results being exported, including mixed/unknown sources, for every committable path.
Project only the structured fields needed by eval properties; remove applicant-derived
quotes/reasoning throughout audit trees. An old analysis flag or opaque numeric index is not
sufficient proof. Prefer a synthetic-only export policy to an unreliable prose scrubber.
Review existing committed fixtures for provenance separately, without publishing applicant
content. Test nested markers, mixed pools, later arrivals and unknown source provenance.
**Latency:** operator-only reads/validation; no normal applicant or committee latency.

### A05 — Make eval fixtures faithful to their declared source (P2)

`fixture._build_provenance` pairs the Nth analysis with the Nth Rank ledger. Failed Rank
attempts can create ledger rows without an analysis, breaking that relationship. It also
reads today's prompt versions instead of the configuration captured with the analysis.
Its comment claiming the metrics code uses the same correlation is obsolete.

`build_fixture` reads global selected score vectors without restricting them to its declared
analysis/opening/criteria. A fixture described as one Rank can contain unrelated dimensions
and applicant columns.

**Evidence:** a failed ledger followed by a successful analysis attributed the failed model
to the fixture. A separate selected score for an unrelated applicant/criterion appeared in
the fixture's vectors despite that criterion being absent from its dimensions.

**Recommendation:** scope fixture inputs explicitly; derive provenance from captured
configuration and actual persisted source relationships. Mark unavailable history unknown
instead of guessing from row positions or current modules. If a ledger relationship must be
stored, use the existing analysis ID. Preserve legitimate global vectors used by production
consolidation; fix the export boundary rather than changing their semantics everywhere.
Test failed/cancelled preceding runs, changed prompts, multiple openings and historical scores.
**Latency:** bounded operator queries; reduced fixture size and no new normal-path waits.

### A06 — Clarify where versioned eval corpus edits are durable (P2; policy choice)

Eval case/baseline mutators write under `backend/eval-data`. The image includes that directory,
but Fly mounts only the runtime data directory. Hosted edits therefore do not update Git and
are replaced by a new image. The editor's instruction to commit the saved file applies to
local development, although the editing affordance is also available when hosted.

**Evidence:** `backend/app/evals/paths.py`, `Dockerfile`, `fly.toml` and the editor/save routes;
this is a configuration consequence, not an observed production loss.

**Recommendation:** keep the versioned corpus as the source of truth. Make hosted corpus
editing read-only unless there is an explicit export/review/commit workflow. Avoid a second
database-backed copy of the corpus. Confirm whether hosted editing is actually desired
before choosing the UI/API policy. Test that local editing remains available and hosted
mutators cannot imply durable success. **Latency:** none.

### A07 — Reconcile uncertain acknowledgements for direct selection (P2)

`frontend/src/components/admin/DirectSelectionOpeningForm.tsx` reports “Could not fill that
opening” after transport or successful-response parsing failures, with no list reconciliation.
The server may already have committed that permanent decision. Its sibling decision panel
already explains uncertain outcomes more accurately. Backend selection uniqueness prevents
duplicate selection, but does not make the failure message truthful.

**Recommendation:** classify a lost acknowledgement as unconfirmed, refresh the scoped
opening state, and ask the operator to review it before retrying. Preserve the submitted
facts while reconciling. Avoid adding new IDs or a general retry framework.
**Evidence:** a real component probe supplied HTTP 200 with an incomplete response body;
the form reported the definitive failure, reopened confirmation, and did not reconcile the
opening list. This proves acknowledgement handling, not an observed production incident.
**Latency:** a read on an exceptional path, not a successful save.

### A08 — Applicant motivation helper (approved small copy change)

The motivation field's helper asked how the household would contribute, duplicating the
separate skills question. The user selected: “Share what you’re looking for in a home and a
co-op community.” That change was implemented separately from the audit findings.

The approved one-line change is committed as `2861ab0`; no other runtime finding has been
implemented in this audit phase. The field key and stored-answer contract are unchanged.

### A09 — Finish applicant API boundary cleanup and remove obsolete instructions (P3)

`frontend/src/applicant/api.ts` exports both a captured-client factory and a complete unbound
instance of its methods. Runtime owners already use the required captured API for protected
actions. Unbound exports such as `saveApplication`, `submitApplication`, `withdrawApplication`,
`requestEmailChange` and `reconcilePendingCopy` have no production caller. They advertise a
second way to call protected actions which the browser boundary correctly rejects. The name
`publicApi` also refers to a module/factory containing protected operations.

**Recommendation:** retain explicit public/bootstrap exports, including the application
bootstrap read and return-access-link flow; expose protected calls through the required
captured factory only. Rename the misleading import alias. Adapt tests/manual harnesses to
construct their own client, following the existing committee API pattern. This removes an
unused interface, not the underlying protected operation or the deliberate bootstrap path.

While updating export documentation, correct `.clinerules`' instruction to run
`python -m app.evals.fixture`: that module explicitly has no CLI entry point. The supported
baseline action is the local Evals tab. Fix the fixture's obsolete metrics/provenance comment
and the unconditional privacy/durability claims in `docs/ai-evals.md` as part of A04–A06.
Keep historical ADRs and migration history; they are not runtime tombstone code.
**Latency:** none; fewer misleading interfaces and instructions for the next maintainer.

## Recorded product decisions

### D01 — Operator capabilities

The UI shows Evals/Observability only to administrators, while eval routes require an ordinary
current committee user. Existing API tests explicitly use member access, so this is an
ambiguous permission contract rather than an assumed new authorization regression.

**Evidence:** a member-role synthetic API probe successfully changed an allowlisted fixture.

**Decision:** the user confirmed that Evals and Observability are admin-only. Admission now
matches that policy for all eval routes, the three observability routes and the four ranking
trace endpoints. Ordinary committee current/board/Screen/Rank access remains. Local file
writes use existing fresh admin authority checks, with no new roles.

### D02 — Paid eval spending

**Evidence:** a paid eval with the application AI cap set to zero still called the mock
provider. Eval streaming uses the shared work lifetime, but not the application run
lease/budget/ledger; cost reporting differs by eval family. The project rule says AI calls
should be observable, estimated and costed; current eval controls chiefly estimate call counts.

**Decision:** the user confirmed that engineering evals have no spending cap. The proposed
budget/cost expansion is not being pursued. Hosted admin runs retain existing call-count and
real-spend confirmation, streaming/cancellation and per-case outcomes. A regression verifies
that a zero application cap does not block a hosted admin eval.

### D03 — Hosted fixture editing

**Decision:** hosted corpus editing is unsupported and unnecessary. Local edits should ship
with the committed repository revision in the next manual deployment. The runtime database
and volume do not become another corpus source.

## Recommended implementation packages

1. Eval data contracts, truthful fixture scope/provenance and local/admin corpus boundaries:
   A02–A03, A05–A06 and D01/D03. A04 is deferred; D02 needs no implementation.
2. Display refresh ownership: A01, including settings/cache/display agreement.
3. Permanent decision acknowledgement: A07.
4. Redundant interfaces and accurate documentation: A09; complete the docs alongside the
   owner changes above so source and instructions agree. A08 is already committed separately.

Each package should be a cohesive reviewed commit with targeted regressions and existing
full checks. Existing identities, scopes, cache keys and writer boundaries should carry the
fixes. A new blanket synchronization layer would increase brittleness without addressing
these particular defects.

## What I would leave alone

- Keep submission-time age normalization, canonical cache identity, selected-result
  references, automatic cache adoption and complete-coverage readiness. Birthday changes
  alone should continue to hit the cache. Discovery provenance is useful audit data without
  determining readiness of retained scores. Keep the two distinct paid Rank actions.
- Keep last consumed findings active while new model work is needed. Amber expresses that
  freshness; do not add per-applicant stale labels or more cache-reuse confirmations.
- Keep short writer guards, work cancellation, run leases, acknowledgement snapshot checks
  and scoped reads. They have named responsibilities and protect real boundaries. Do not
  replace them with a blanket transaction/lock, an event bus or a global state framework.
- Keep per-consumer query projections where outputs/permissions differ; sharing cache-key
  identity does not require a generic cache manager. Preserve privacy-aware deletion of
  shared results and credential fencing before email delivery.
- Keep supported legacy answers for existing imported records. The retired form's ingestion
  path is not a reason to remove the data reader or invent unavailable dates of birth.
- Keep the cohesive ORM model registry (about 1,124 lines). Its size triggered ownership
  review, but splitting related mapped definitions solely to meet a line limit adds navigation
  cost without fixing a confirmed responsibility problem. Other large owners remain below
  the architecture-review threshold.
- Do not perform a broad utility, naming, formatting, dependency-upgrade or component-splitting
  sweep. No additional runtime module deletion or repeated long Python body justified one.

## Complexity and responsiveness assessment

The earlier concurrency work is still justified: existing resource identities, shared-cache
references, writer checks and snapshots now make important ownership explicit. The remaining
problems are mostly incomplete consumer contracts and export boundaries. The remedy is to
finish those boundaries and remove redundant interfaces, not add another general-purpose
layer. A01 needs a single owner for displayed-board refresh; A02–A05 need truthful typed data
and one safe publication/export path.

Successful applicant edits/submissions and ordinary committee saves should gain no additional
network round trip from these recommendations. A01 adds or substitutes a background board
read only while relevant; A07 adds reconciliation only after an uncertain permanent action.
Eval validation/export/role/cost work stays on explicit operator actions. There is no proposed
extra AI generation, delay waiting for other members or cache invalidation on birthdays.
Engineering evals remain uncapped by the user's decision.

This audit measured request behavior and query scope through code and synthetic probes; it
did not collect production response-time percentiles. Avoid claiming a measured speedup from
code inspection. Existing lazy entry points remain useful; there is no demonstrated need
for new client caching or micro-optimizations.

## Coverage and verification

| Pass | Coverage and result |
| --- | --- |
| 1 — Inventory / ownership | Inventoried 204 Python app/script modules and 130 non-test frontend source/type modules. Reviewed owner map, current changes, long files and shared contracts. Python graph: 194 app modules, no import cycle including deferred imports. Frontend graph, including lazy imports: every runtime module reachable; nine type-only modules excluded from runtime reachability; no runtime import cycle. Exact Python body scan of functions at least ten lines found no duplicate body after docstring exclusion. These are bounded scans, not proof of zero semantic redundancy. |
| 2 — Backend / operations | Read transaction/authority boundaries, intake/publication, retention/deletion, selected caches and ranking, screening, stream lifetime/cancellation/budget, passwordless/Google access, email claims and retries, maintenance and rate limits, backup/recovery, eval authoring/export/harvest, Docker/Fly/watchdog settings and operational instructions. Followed export findings into the actual reader and live-data source. No production inspection or operation was used. |
| 3 — Frontend / journeys | Traced guest-to-authenticated submission, draft/save/reconciliation/email change/withdrawal, committee navigation and details, eligibility edits, ranking tiers/proposals/refresh/readiness/cache adoption, Screen/Rank confirmations, openings publication/permanent/direct decisions, admin controls, eval editing/live/saved results and sign-in scope. Compared sibling acknowledgement and publication patterns rather than prescribing another abstraction. |
| 4 — Reproduction / consolidation | Nine isolated backend probes and three real frontend hook/component probes passed as characterizations of the defects/contracts above. Used temporary files, isolated test databases and mock providers with fabricated markers. Removed those throwaway probes before baseline checks. Reviewed fixes as cohesive packages, explicitly separated policy choices, latency implications, approved copy and things to leave alone. |

Baseline verification passed:

- Backend: Ruff; **975 tests passed, one existing platform-dependent skip**.
- Frontend: lint, TypeScript/Vite build; **287 tests passed**.
- Watchdog: TypeScript check; **nine tests passed**.
- `git diff --check`; generated build/cache directories inspected with inherited ACLs.

The baseline passed despite the defects reproduced by the throwaway probes. Implementation
adds permanent regressions for the approved fixes, including nested family validation,
Unicode/publication concurrency, nullable live/saved scores, scoped/unknown provenance,
admin-only access and narrative projection, hosted read-only/uncapped evals, same-analysis
updates, pending/live/disposed board reads and uncertain permanent acknowledgements.

Implementation verification:

- Backend: Ruff; **1,034 tests passed, one existing platform-dependent skip**.
- Frontend: lint, TypeScript/Vite build; **304 tests passed**.
- `git diff --check`; build/cache directories retain inherited ACLs.
- No committed corpus or applicant data changed. No database migration was needed.

No production operations, real model calls, outbound emails, local database reset,
dev-server start or page reload took place. This is a repository-wide, multi-pass static
review with targeted executions, not a load test or line-by-line certification of every
module. Historical runtime findings have not been reimplemented; the previous completed
audit is recoverable in Git. Implementation commits and this report are local; no push or
production deployment took place during this implementation.
