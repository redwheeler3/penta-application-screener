# Maintainability audit — 2026-10-04

## Purpose and baseline

This is one project-wide backlog for redundant code, unused code, obsolete explanations,
ownership, simplicity, readability, and avoidable work. It extends the completed
[reliability audit](reliability-audit-2026-10-04.md). The implementation should handle the
approved backlog and confirmed related follow-up findings in one task, followed by a final
review of the changed workflows. It should not require another request after each small batch.

Reviewed baseline: `main` at `c072ed3`, initially clean and synchronized with `origin/main`.
The audit initially changed documentation only. The follow-up removed the separate commit
approval rule and hook, recorded browser-only API support in SPEC, and inspected aggregate
production answer-format counts in SQLite read-only mode. At audit completion, no application
runtime code, database records, deployment, or provider configuration had changed. The backlog
defines the agreed scope; implementation outcomes are recorded at the end of this document.

The goal is code that an engineer can understand without knowing its development history.
Reduce unnecessary paths and misleading contracts; retain the ordering and ownership that
protect saves, authority, provenance, and permanent decisions. A smaller file alone is not a
reason to introduce a new abstraction.

## Coverage and method

| Area | Review performed | Result |
| --- | --- | --- |
| Backend runtime | Inventory of all 189 tracked Python modules under `backend/app`; AST searches for unreferenced declarations, unread parameters, identical function bodies, and import cycles; focused reads of routes, services, domain rules, schemas, and AI boundaries | Unused helpers and parameters; several misleading explanations; no resolved import cycles |
| Frontend runtime | TypeScript AST import graph from `main.tsx`, including dynamic and type imports; declaration and prop reference checks; focused reads of applicant, committee, admin, ranking, Evals, and observability ownership | No orphaned runtime modules; redundant authenticated branches, repeated eval configuration, unnecessary reads, one unused prop/type |
| Styles | Reference inventory for selectors across the tracked UI, followed by inspection of dynamic class construction and responsive/print rules | Eight unused class families confirmed; shared controls live in a feature stylesheet |
| Tests and fixtures | Traced production candidates through tests, eval CLIs, and fixture tooling; inspected assertions for eligibility, judge results, tiering, request scopes, and shared test support | Some tests exercise a separate unused implementation; preserve their behavioral coverage while removing that path |
| Local scripts and recovery | Read Windows and Bash setup/dev/backup/restore/reset wrappers and the current backup service | Duplicated generated Python commands, quoted-argument failures, bare-filename inconsistency, and missing native exit checks |
| Ops and build | Read watchdog runtime/configuration and build/dependency/style entrypoints; checked suspected unused entrypoints against configuration | No recommended operational redesign or dependency removal |
| Current documentation | Compared owners and claims with code, checked documented source paths, generated OpenAPI without starting the application lifespan, and compared its paths with the API map | Current source paths resolve; API and architectural descriptions need reconciliation |
| Recent work | Read relevant commits since October 1 and current reliability/architecture documentation; revisited captured scoring plans, consumed-result references, request scopes, and cancellation/receipt boundaries | Preserve these fixes; simplify obsolete callers and explanations around them |

The frontend graph covered 129 non-test TypeScript source/declaration files. Only
`testSetup.ts`, `testSupport.ts`, and `vite-env.d.ts` were outside the runtime import graph;
these have explicit test/compiler roles. The watchdog's `FlyWatchdog` export is referenced by
its deployment configuration and is not dead code.

Searches are candidate generators, not deletion proof. Dynamic CSS classes, framework
callbacks, ORM mappings, CLI entrypoints, migrations, and retained data readers received
separate checks. The audit inventories the entire tracked source tree and reads the relevant
owners; it does not claim that every source line received equal manual scrutiny or that no
undiscovered issue remains. Private business files, secrets, raw applicant content, provider
judgment, visual behavior, and production changes are outside this review. The explicitly
approved production aggregate inspection is documented below.

## Recommended backlog

Priorities describe implementation order and benefit, not security severity. All fifteen
packages are worthwhile. Small signature/comment edits should accompany their owning package
rather than becoming a succession of trivial standalone commits.

| ID | Priority | Work package | Expected effect |
| --- | --- | --- | --- |
| M01 | First | Separate the full-Rank scoring projection from captured-plan pricing | Fewer estimator branches and redundant pool reads |
| M02 | First | Remove proven dead declarations and unused internal inputs | Less code and clearer dependencies |
| M03 | First | Replace test-only eligibility orchestration with coverage of live paths | One production eligibility implementation to maintain |
| M04 | First | Remove unused judge text-report formatters | One consumed result/presentation contract |
| M05 | Next | Trim unreachable committee auth branches | Clear authenticated workspace ownership |
| M06 | Next | Render repeated eval families from typed configuration | Less repetitive UI configuration and fewer assertions |
| M07 | Next | Load advisory/catalog data only where consumed | Fewer background requests without waiting on interactive actions |
| M08 | Next | Make resource read invalidation explicit | Remove a setter call whose only purpose is a side effect |
| M09 | Next | Remove dead styles and place shared controls with shared styles | Easier style discovery without redesign |
| M10 | First | Use one recovery CLI and check script command outcomes | Simpler wrappers and truthful recovery/setup results |
| M11 | Next | Make email and categorical-eval annotations describe real contracts | Clearer required/optional fields and shared case interface |
| M12 | Alongside changes | Reconcile current docs, UI descriptions, and comments | Readers learn the system that actually exists |
| M13 | Next | Remove unused standalone ranking reads | One coherent board contract for browser and manual tests |
| M14 | First | Repair stale manual-analysis entrypoints | Diagnostic tools read the current analysis model |
| M15 | First | Keep applicants unranked until a member chooses priorities | Committee judgment determines ranking |

### M01 — Give each scoring estimate one purpose

Owner: [dimension_scoring_cost.py](../backend/app/ai/dimension_scoring_cost.py), especially
`estimate_dimension_scoring` at line 105; [ranking/estimates.py](../backend/app/services/ranking/estimates.py).

`estimate_scoring_plan` prices the captured work that score-current execution consumes. The
older `estimate_dimension_scoring` still offers `prefer_history`, `include_coverage`, optional
pool loading, and a general `CostEstimate` containing coverage counts. Its sole production
caller is the full-Rank projection, which supplies a pool, sets `include_coverage=False`, and
reads only `estimated_usd`. No production caller chooses `prefer_history=False`.

The fallback `_per_candidate_input_tokens` nevertheless loads the eligible pool again even
when its caller supplied one. An isolated in-memory reproduction supplied one synthetic
candidate and observed one additional call to `applications_to_score`. The report existed and
the ledger had no history, exercising the real fallback estimator. No model was called.

Replace the old multipurpose API with an explicitly named full-Rank scoring projection that
receives the caller's pool and returns the value needed. Reuse that pool for the sample prompt.
Keep history-first pricing, first-run assumptions, and current-cache fallback semantics.
Preserve `estimate_scoring_plan` and its exact captured misses. Do not combine approximate
future discovery work with the exact score-current plan.

Verification: existing estimate/cap tests, history and no-history cases, empty pool, missing
report, partial/complete cache, and a query/call-count assertion that a supplied pool is reused.
Use synthetic inputs. No added synchronization or user-facing latency is expected.

### M02 — Remove declarations that no runtime caller needs

Confirmed candidates:

- `applications_needing_scores`, [dimension_scoring.py](../backend/app/ai/dimension_scoring.py),
  line 217: no production, test, CLI, or documentation caller. Captured scoring plans replaced
  the need for this additional filtering wrapper.
- `_run_exists`, [dashboard.py](../backend/app/api/dashboard.py), line 270: no callers.
- `email_delivery_failed` and `pending_draft_unavailable`,
  [problems.py](../backend/app/core/problems.py), lines 27 and 31: no emitters or consumers in
  backend, frontend, tests, or current docs.
- `EvalCaseResult`, [types/evals.ts](../frontend/src/types/evals.ts), line 95: unused broad
  union alias. Preserve the mode-correlated outcome and summary contracts that replaced it.
- `AdminSettingsPanel.onEligibilityChanged`,
  [AdminSettingsPanel.tsx](../frontend/src/components/admin/AdminSettingsPanel.tsx), line 29:
  declared and supplied but never read. Remove that prop and its unnecessary wiring, preserving
  callbacks used by the actual eligibility editors.

Also remove unused inputs from internal helpers: `db`/`user` in `build_settings_response`,
`db` in `committee_opening` and `current_prompt_version`, and `request` in
`_complete_google_sign_in`. These parameters falsely suggest database, identity, or request
dependencies. Keep auth-enforcing FastAPI route dependencies and provider/protocol signatures.

Verification: repeat repository reference checks after the edits, run the affected backend
suite/linter and frontend lint/build, and inspect the diff for accidentally removed imports or
authorization dependencies. No new tests that merely prove deleted wrappers are needed.

### M03 — Stop maintaining a separate eligibility path solely for tests

Owner: [eligibility/evaluation.py](../backend/app/services/eligibility/evaluation.py),
`effective_status_for` at line 96 and `_member_override` at line 84.

`effective_status_for` has no production caller. Tests in `test_eligibility.py` and
`test_opening_scoped_workflow.py` use it to assemble one member's status via separate queries.
The running app uses the bulk eligible-pool readers and list/detail eligibility presentation.
This duplicates orchestration and can keep tests green while the real presentation drifts.

Preserve the valuable assertions for pet-source attribution, muted flags, opening-specific
rules, and overrides. Redirect them to the live eligible-pool and eligibility-response paths,
then remove the unused helper and its private query. Keep the shared pure `effective_status`
policy and bulk readers.

Verification: source attribution in real response assembly as well as eligible-set membership;
opening isolation; strict/lenient member rules; overrides; absent, empty, and populated AI
findings. This should reduce production code rather than introduce a new test-only service.

### M04 — Remove the abandoned judge text presentation

Owner: [evals/judge.py](../backend/app/evals/judge.py), `format_stability` at line 256 and
`format_report` at line 273; `tests/test_eval_judge.py`.

Only tests call these formatters. The API/UI consumes structured results, and the checked-in
eval and bake-off CLIs do not import the text presentation. Several tests already assert the
meaningful marker/agreement fields and then repeat the assertion against an unused string.

Delete the formatters and string-only assertions. Where a formatter currently supplies the
only assertion, assert the underlying agreement, tally, stability marker, or cost instead.
Preserve contested-case, disagreement, flip, and grading coverage. Keep active eval CLIs and
their independent human-label audit.

### M05 — Let the authenticated workspace read as authenticated

Owner: [CommitteeWorkspace.tsx](../frontend/src/CommitteeWorkspace.tsx), lines 183, 190,
225, 274, 332, and 534; [App.tsx](../frontend/src/App.tsx).

`App` mounts a workspace only for a non-null user and keys it by account ID. The workspace
prop is non-null, but old `if (!user)` effects and conditional account/feedback rendering remain.
An extra fragment also keeps the main workspace unnecessarily indented.

Remove those unreachable branches and the fragment; correct ownership comments that still
attribute workspace state to `App`. Keep opening-null guards, role checks, the account key,
unmount cancellation, and separate authentication/workspace state lifetimes. Existing branding
components provide sufficient reuse; do not add another layout framework for the two short headers.

Verification: signed-out/auth-conflict screens, account switching, sign-out failure, and the
existing workspace disposal tests; frontend lint/build. No visual redesign is intended.

### M06 — Use typed configuration for repeated eval controls

Owner: [AIWorkspaceView.tsx](../frontend/src/components/ai/AIWorkspaceView.tsx), lines 128–204.

Five pass tabs repeat the same `RunnableEval` markup, paired run/stability modes, keys, row
labels, and `as RunMode[]` assertions. Variation is configuration, not a different workflow.

Describe those five families in a small typed configuration and render their common controls
once. Preserve each family key, both history keys, labels, descriptions, ordering, and run costs.
Keep Invariants and Judge visibly distinct, including Judge's background editor, grouping,
cross-pass editing, and add restrictions. Do not build a generic plugin/registry framework.
Use type-checked values instead of assertions where inference can prove the configuration.

Verification: each family restores both modes, changing family remounts its case workspace,
Judge keeps its distinct controls, and call estimates still attach to the correct mode.
Existing eval lifetime tests remain necessary. Rendering should gain no network dependency.

### M07 — Avoid requests for hidden features

Owners: [AIWorkspaceView.tsx](../frontend/src/components/ai/AIWorkspaceView.tsx), line 43;
[App.tsx](../frontend/src/App.tsx), line 12; [useEmailDeliveryStatus.ts](../frontend/src/hooks/useEmailDeliveryStatus.ts).

The Observability family fetches the eval catalog even though only Evals consumes its call
counts. The top-level committee `App` also starts cached-status and provider-refresh requests
for the email-delay advisory even when authentication restores a user directly into the
workspace, where that advisory is not rendered. `ApplicantApp` starts the same work at mount,
but only its `ApplicationEntry` branch receives the advisory; authenticated form/review states
do not consume it.

Load the catalog only for the Evals family. Scope committee email-advisory work to the access
surface that displays it, preserving background refresh, cached-first guidance, and cancellation.
Apply the same ownership to applicant entry, respecting the existing phase/opening/guest guards
that decide whether that entry is visible. Keep controlled previews independent of runtime
status requests. Do not change retry policy or make sign-in
await provider reporting.

Verification: request counts for authenticated committee entry and Observability; catalog
availability in Evals; cached warning while refresh is pending; switching to access starts
the advisory; leaving its owner cancels the request. This is avoidable work, not a claimed
end-to-end latency benchmark. Inputs and navigation must remain immediately usable.

### M08 — Name read invalidation explicitly

Owners: [useFetchResource.ts](../frontend/src/hooks/useFetchResource.ts),
[useEligibilityRules.ts](../frontend/src/hooks/useEligibilityRules.ts), line 54.

Before an eligibility write, `resource.setData(current => current)` means “invalidate older
reads.” The setter also marks the resource ready, so its intent is hidden in a state-update
side effect. Its comment describes server acknowledgements while callers also use it for drafts.

Expose a narrowly named read-invalidation operation and call it at the write boundary.
Keep accepted mutation data newer than outstanding reads, preserve current typing, and retain
the same opening scope. Make the setter's documented responsibilities truthful. Do not replace
these hooks with a general cache library or combine every draft workflow into one engine.

Verification: pending GET followed by write, failed save preserving draft, typing during save,
and opening changes. Preserve the regressions that motivated request invalidation.

### M09 — Delete unused CSS and give shared controls a shared home

Confirmed unused class families, with no tracked markup or dynamic construction:

| Stylesheet | Remove |
| --- | --- |
| `admin.css` | `.text-danger-button` |
| `applicant.css` | `.applicant-device-status`, `.review-next-step`, `.field-success`, including descendant/responsive rules |
| `applications.css` | `.app-tabs` |
| `observability.css` | `.observability-subsection`, `.observability-subsection-title`, `.cost-muted` |

Shared `.subtabs`/`.subtab` controls and `.panel-hint` currently live in
`observability.css` but are used by admin, eligibility, and Evals surfaces. Move the shared
rules, including responsive behavior, to the existing common stylesheet ownership. Keep
feature-specific overrides with their feature and preserve import/cascade order. Remove the
contradictory admin comments describing pill tabs and only two sections.

Do not delete dynamically constructed role, phase, status, source, fit-band, saved-view,
column-count, print-column, or tier-badge selectors. The initial token scan flagged these,
but manual tracing confirmed their use.

Verification: build/lint plus a diff/cascade review; compare representative shared controls
at desktop/mobile widths if rule movement could alter precedence. No restyling or large CSS
framework adoption is recommended.

### M10 — Simplify recovery wrappers and propagate failures

Owners: root `backup-db.ps1`/`.sh`, `restore-db.ps1`/`.sh`, `setup.ps1`, `reset-db.ps1`, `dev.sh`,
and [services/backup.py](../backend/app/services/backup.py), `main` at line 380.

The service already has a Python module entrypoint, but shell wrappers independently build
Python source containing user-provided tags and paths. A tag such as `Jeff's-check` or a path
under `Jeff's Workspace` creates an unterminated Python string. This was reproduced with
`ast.parse` only; no backup or restore was executed. Sanitizing a backup filename inside the
service cannot fix source parsing that fails before the service runs.

The explicit-target PowerShell restore path also fails to resolve an advertised bare backup
filename against the backups directory, whereas its interactive path and Bash wrapper do.
Windows setup relies on `$ErrorActionPreference = 'Stop'` for native commands without checking
their exit codes. Native error-action propagation is false in the reviewed shell. Reset waits
for migrations but does not inspect the process exit code before reporting completion.
Backup/restore commands likewise need truthful success/failure propagation.
The Bash dev launcher also uses `kill 0` for exit cleanup: that signals the entire current
process group, which can include unrelated caller work when the launcher has no separate
job-control group. Cleanup should identify the services it owns rather than rely on that
launch-environment assumption.

Extend one recovery CLI with ordinary argument parsing for backup/tag, list/latest, and restore
selection. Pass arguments as data from thin shell wrappers. Share selection/path resolution
where useful, retain explicit restore/reset confirmations, and check every required native
command's outcome. Limit dev cleanup to its owned service lifetimes, including their workers.
Correct obsolete reset/setup descriptions of current data and sign-in options.

Verification: parser/path tests using synthetic names, quotes, spaces, and missing files;
failure injection for commands; temporary synthetic databases for service preservation tests;
isolated launcher-process tests that leave an unrelated sentinel process running.
Do not run an actual local reset or restore, prune the user's backups, or start a server.
This changes local tooling, not application request latency or production operation.

### M11 — Make small shared contracts truthful

Owners: [email/retry_intents.py](../backend/app/services/email/retry_intents.py), line 6;
[email/transactional.py](../backend/app/services/email/transactional.py), line 63;
[evals/_categorical.py](../backend/app/evals/_categorical.py), line 22.

`MagicLinkRetryIntent` declares `remember_device` and `initiating_session_id` as required,
but the queued committee-invitation producer omits them and the consumer deliberately reads
defaults. Make required/optional fields reflect the emitted and consumed JSON, or consistently
emit the complete declared shape. Retain credential-free intents and the invitation flag.

`CategoricalResult.case` is annotated `object` and then reads `.expected` with an ignore;
grading also relies on `.key` and `.contested`. Name that small shared case interface so the
reader can see the required fields. Keep the real pass-specific case dataclasses and graders.
Do not attempt to generalize continuous scoring, flag sets, and categorical verdicts into one
universal grading engine, or add a repository-wide typing migration to solve two local contracts.

Verification: queued invitation defaults and ordinary applicant/committee retry metadata;
categorical expected/contested behavior and response serialization. No persistence migration
or provider call is needed for annotation cleanup.

### M12 — Reconcile explanations with current behavior

Concrete corrections to include, checking sibling descriptions in the same pass:

- `docs/app-architecture.md`, lines 324 and 381: score/screen readers use
  `ApplicationAISelection` references to consumed results, not newest-row/timestamp selection.
- `docs/api.md`, line 50: `/applicant/application/revert` is absent from generated OpenAPI.
  Include the current pending-copy and coherent board contracts; reconcile the important
  email-delivery, feedback, eligibility, note, saved-view, and selection routes. OpenAPI remains
  the exact schema source; the document should explain current workflows and ownership.
- `AIWorkspaceView.tsx`, line 134: scoring evals use deterministic band/confidence assertions;
  an additional rubric judge does not run there. Judge is its own label-audit workflow.
- `services/eligibility/evaluation.py`, lines 3–7: shared findings are interpreted under each
  member's rules and disabled checks; the machine verdict is not the same for everyone.
- `types/observability.ts`, lines 27–29: expense is known returned usage, not a promise of an
  exact provider bill. Update “completed run” comments where failed attempts are also returned.
- `services/cost_report.py`, lines 48–50, and observability schema comments: non-cacheable
  passes use configured providers when they run; some phases can be skipped. “Always call
  Bedrock fresh” is inaccurate.
- `api/ranking/run.py`, line 91: discovery fans out; it is not one call.
- `ai/analysis.py`, line 391: the worker pool uses cancellation-aware `wait(FIRST_COMPLETED)`;
  describe completion-order delivery without naming the obsolete `as_completed` mechanism.
- `evals/reproduce.py` and `evals/paths.py`: replace references to nonexistent `live_*.py`
  owners with current module names. Correct stale history-key and workspace-owner examples.
- `README.md`, lines 37, 41, 43, 80, 94, and 103–107: describe the existing equal-weight
  baseline accurately, qualify cache reuse instead of promising that work is never paid for
  twice, distinguish configurable models from defaults, and describe deliberate re-discovery
  rather than claiming all no-op reruns are refused. Status/source filters replace the stated
  separate “AI Flagged” bucket. Preserve human decision authority and explicit model-cost limits.
- Remove milestone/backstory shorthand such as `D9` where present-tense purpose is clearer.
  Preserve useful rationale for isolation, cache identities, explicit acknowledgements, and
  independent judgment. Do not rewrite AI prompt bytes as a cosmetic comment task.
- The retained-form renderer comment assumes a one-year lifetime. Describe its supported
  stored data rather than a removal date; production includes a selected-household record.

Generated OpenAPI had 113 method/path pairs. The handwritten map includes grouped routes,
query examples, and differing placeholder names; these are not automatically dead endpoints.
The comparison was used to verify concrete discrepancies, not to treat every literal mismatch
as a missing API. That local OpenAPI inspection did not start an application lifespan,
read real data, or invoke a provider. The subsequent production inspection is recorded below.

Verification: regenerate/read current OpenAPI and trace the described behavior to its owner;
check current paths and prompt hashes if touching prompt-adjacent comments. Historical ADRs,
case studies, migrations, changelogs, and dated audit evidence intentionally describe history.

### M13 — Remove standalone ranking reads

The user confirmed that the application API is browser-only except for our own manual tests.
No external compatibility requirement remains for `GET /ranking` or `GET /ranking/tiers`.
The runtime browser reads `/ranking/board` for these values, and manual tests can do the same.

Remove those two GET handlers and the now-unused `TiersResponse` schema. Preserve
`RankingResponse`, which is nested in the board and returned by tier mutations. Retarget
ranking/tier integration tests to the board response, keeping coverage of ordering, bands,
weights, defaults, stale analyses, permissions, and saved tier state. Keep the `/current`
read and audit endpoints used by the browser, and the tier/proposal mutations.

With the empty-path ranking GET gone, review whether the common `/ranking` prefix can move
to the package router instead of being repeated on each child. Update current API/schema
descriptions in the same batch. Verify generated OpenAPI has the intended remaining routes
and that actual browser loads and manual test calls use the coherent board contract.

### M14 — Repair the manual-analysis entrypoints

Further tracing of manual-test support found three confirmed stale model imports:
`scripts/analyze_convergence.py:33`, `scripts/decompose_drift.py:121`, and
`scripts/harvest_golden_cases.py:89` import `RankingRun`, which no longer exists. They also
read its removed `criteria` blob; the current owners are `Analysis.dimension_report`,
`Analysis.rank_inputs_fingerprint`, and the separate `AnalysisAudit` row. `harvest_golden_cases`
also references the removed run name. AST validation of model imports confirmed all three
missing imports without executing the tools against applicant data or invoking providers.

These are documented diagnostic workflows, not code to delete merely because the browser
doesn't call them. Update their readers to the current owners, scope analysis sequences to
the selected opening, and remove their obsolete schema-cleanup notes. Preserve the existing
pure drift/overlap/candidate algorithms and privacy boundaries; applicant-content exports
must retain synthetic-data restrictions. Do not restore a `RankingRun` compatibility alias.

Verification must exercise CLI entrypoints with synthetic in-memory or temporary data,
including absent audits and multiple openings. The existing pure `find_drift` test does not
exercise the stale import inside `main`, which explains why that tool can pass its helper
tests and still fail when invoked. Add a static/import smoke check for current script model
references so dormant entrypoint paths receive coverage.

### M15 — Rank only after a member chooses priorities

D01 is approved. Remove the all-Ignore uniform-weight fallback. Criteria remain at zero
until placed in a working tier. With no positive criterion, return absent rank, aggregate fit,
and fit band. The Ranking tab keeps criteria controls and a persistent notification box,
but hides applicants, the View selector, and both Print buttons. Applications remains the
general review surface; the notice focuses only on choosing priorities.
Selecting a criterion starts ranking; clearing all working tiers restores the unranked state.

Preserve cached scores, their evidence and provenance, favourites, shortlist membership,
opening/member scope, and the existing weighted mathematics. Reweighting makes no model call
and adds no refresh or synchronization requirement. Candidate details continue to show only
contributions from criteria the member has actually chosen; raw traces remain available.

Verification: domain ordering/null fields with zero weights, unchanged positive-weight math,
HTTP transitions from unranked to weighted to unranked, and UI disappearance/reappearance
of rank numbers and bands. Update old baseline tests instead of retaining a compatibility path.

## Decisions and changes not recommended by default

### D01 — All-Ignore ranking policy

At the audit baseline, `weights_from_tiers` returned uniform `1.0` weights when no dimension had a
positive placement. `SPEC.md` describes that baseline, and
`test_tier_weighting.py` explicitly tests empty/no-tier fallback. This is not a new confirmed
calculation bug; it conflicts with the README's claim that all unactivated suggestions are inert.

An isolated synthetic calculation confirmed that replacing `1.0` with zero is not equivalent.
All-zero weights yield fit `0.0` for everyone. The current ranker then sorts by applicant ID;
because tied fits share the first candidate's band, every candidate receives “Strong fit.”
All criterion impacts are zero, although the underlying score explanations remain stored.
The `1.0` fallback supplies an initial equal-weight ranking before members choose priorities.

Resolved: the user approved zero weights and an explicit unranked state, hiding the ranking list, View/Print controls, rank numbers,
and fit bands until at least one criterion has positive weight. All-Ignore means that no
criterion influences ranking. Implement this under M15; stored AI scores remain available.

### D02 — Standalone ranking read endpoints

The app now reads `/ranking/board` for coherent criteria/ranking/tiers and still reads
`/ranking/current` for lightweight checks. `GET /ranking` and `GET /ranking/tiers` have no
current frontend runtime caller, but are documented HTTP surfaces with direct integration tests.

Resolved: the user confirmed browser-only support plus our own manual tests. Remove these
redundant reads and retarget manual/integration tests under M13. This does not remove routes
or metadata still consumed by the browser.

### Retained-form data — production inspection

The user confirmed that the external form is permanently retired. On October 4, a production
SQLite connection opened with `mode=ro` and `PRAGMA query_only=ON` returned these aggregate counts:

| Check | Count |
| --- | ---: |
| Applications | 233 |
| Applications with original-form answer headings | 232 |
| Applications with native nested answers | 1 |
| Native working copies | 1 |
| Selected applications with original-form answer headings | 1 |
| Saved publication versions | 4 |
| Versions with original-form answer headings | 0 |

Answer shape does not prove original collection source: the native-shaped application could
have been edited since import. No names, addresses, answers, or credentials were returned.
Fly required explicitly approved wake-up of the existing suspended VM. The remote query
returned valid aggregates; the local CLI then reported a handle error during teardown.
No production records or configuration were changed.

The original-form detail renderer, essay extractor, and working-copy adapter remain live data
readers for these records. Keep them as a bounded retained-data responsibility while removing
any ingestion-only remnants. A native-only representation would require a separate lossless
data migration, including unknown birth dates and original answer provenance; do not fabricate
those values or rewrite production as incidental cleanup. A selected-household record also
invalidates the renderer comment that assumes all such records disappear after one year.

### Keep the boundaries that still carry requirements

- Retained imported-form readers preserve readable applicant answers. Production inspection
  confirmed their current use. Name and document them as retained-data readers, keep their
  handling out of native intake, and remove obsolete ingestion-only code when found. Do not
  infer a purge date from comments or delete support merely because the source form is retired.
- `ensure_lock_row` serves schema-only test databases; migrations seed the runtime lease.
  `app/db/base.py` is used by Alembic. These are intentional entrypoints/support boundaries.
- Stream close-before-start handling, cancellation contexts across worker resumes, lease
  fencing, consumed-result selection, complete score-vector transactions, and independent
  interrupted-spend receipts have distinct failure-path responsibilities. Keep their regressions.
- Keep applicant save snapshots, session/consent generations, request scopes, ordered writes,
  and source-specific acknowledgement merges. Their additional code protects actual data.
- Keep test fixtures, live eval tools, synthetic guards, model bake-off paths, and independent
  judgment; repair stale manual entrypoints under M14. A bake-off calling the Rank route
  intentionally exercises the real boundary;
  extracting a second orchestration path just to remove that import would reduce confidence.
- Do not split the roughly 1,100-line ORM registry merely to meet a file-size target. It has
  one cohesive schema ownership purpose. Do not replace readable domain service packages
  with tiny forwarding modules, new global state machines, caches, or dependency frameworks.
- Keep browser-side draft validation and authoritative server validation. Their different
  inputs and purposes justify some repetition. Keep active model routes and historical pricing
  needed to explain stored results; no dependency removal was substantiated.
- Shared button selectors have deliberate common behavior plus primary/secondary overrides;
  repeated selector names alone are not duplicated CSS. Preserve dynamic and print classes.
- Do not rewrite all formatting, generate tests for reversible cosmetic changes, or change
  prompts, retries, retention, legal copy, provider defaults, or production infrastructure as
  incidental cleanup. No large module extraction or operational redesign was substantiated.

## Implementation sequence

The complete approved backlog is the scope. Follow-up findings belong in this document with
evidence and a disposition, then in the owning implementation batch. Do not turn each batch
into a new permission cycle. Product choices, destructive actions, production changes, and
significant measured latency tradeoffs remain explicit decisions.

Suggested cohesive commits, adjustable to dependency order:

Implement the approved unranked state (M15) as its own first product-behavior commit, then
continue with the cleanup batches below. API/schema and UI contracts move together.

1. **Recovery tooling:** M10; safe argument handling and truthful command failures, with
   parser/failure tests and updated local-tool documentation.
2. **Manual analysis tooling:** M14; current model/audit owners, opening scope, and entrypoint coverage.
3. **Scoring projection:** M01; narrower estimator, pool reuse, and affected estimate tests/comments.
4. **Eligibility cleanup:** M03; tests through live behavior, removal of unused orchestration,
   and corrected per-member explanation.
5. **Eval contracts:** M04 and the categorical part of M11; preserve semantic assertions,
   remove unused formatters, make the shared case interface visible.
6. **Email contracts:** email part of M11; clarify optional/default retry metadata without
   changing delivery/credential lifetime.
7. **Frontend ownership and work:** M05, M07, M08, and unused prop wiring from M02; scoped
   reads, explicit invalidation, and simpler authenticated rendering.
8. **Eval view:** M06; typed family configuration, exact descriptions, preserved lifetime keys.
9. **Dead declarations and styles:** remaining M02 plus M09; remove verified unused pieces
   and move shared style rules without changing the cascade.
10. **Browser API:** M13; remove the unused read alternatives, preserve mutations/current reads,
   and move their behavior tests to the board contract.
11. **Documentation reconciliation:** remaining M12 and this audit's final outcomes/coverage.
   Record net code change and any deferred decisions after reviewing the complete result.

Before every code commit, run the required checks for its changed side: backend Ruff/pytest,
frontend production build, and relevant existing behavioral tests. Run frontend lint when
changing frontend code. Use narrow, meaningful new regressions for changed behavior and
preserve the comprehensive reliability regressions. Finish with full backend/frontend checks
and a fresh caller/ownership review. No real provider run is needed when prompt bytes and
model behavior are unchanged; verify that premise rather than assume it.

Measure request/pool-read counts for M01/M07 and report the results. Avoid adding awaited
refreshes, stronger serialization, or caching to a deletion/readability task. Most packages
should remove code or runtime work; small explicit contracts can add lines while removing
ambiguity. Report that tradeoff from the actual diff, without predicting a net line count.

This audit did not rerun the full test suites or claim new browser/production verification.
Its evidence consists of reference/AST/import/style checks, focused workflow reads, current
OpenAPI inspection, the synthetic estimator reproduction, and parse-only script reproductions.
The previous audit's test totals are historical evidence, not fresh results for this pass.
Follow-up verification also included a synthetic all-zero/equal-weight comparison, static
script model-import validation, production aggregate inspection, and collaboration-rule/hook
checks. Local commits now require reviewed changes and the relevant checks, not a separate
approval request; pushes and production changes retain their separate authorization boundaries.

## Implementation results

- M15: implemented zero-weight defaults and nullable rank/fit/band fields; unranked applicants
  are hidden in Ranking with a persistent priorities notice and no View/Print controls. Choosing and clearing priorities is covered
  in domain, HTTP, and UI regressions. Stored scores and weighted math remain intact.
  Checks: 878 backend tests, 227 frontend tests, Ruff, ESLint, and production build passed.
- M01–M14: pending implementation. Validation results and commit IDs will be recorded as each
  owning batch completes.
