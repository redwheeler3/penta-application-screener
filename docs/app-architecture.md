# Application Architecture

This document is the practical map of the current codebase. Exact HTTP contracts belong to the
generated OpenAPI document at `/docs`; product policy belongs in [SPEC.md](../SPEC.md).
Start with [README.md](../README.md) for the product and local setup, use this document to locate
implementation owners, and read the relevant SPEC section before changing behavior.
[Architecture decisions](adr/README.md) explain the reasoning behind the important boundaries.

## Runtime shape

The production deployment is one FastAPI process serving both the API and the built React SPA.
SQLite lives on a Fly persistent volume. Local development runs Vite and FastAPI separately:

```text
Applicant or committee browser
        |
        v
React / TypeScript SPA
        |
        v
FastAPI routes
        |
        +-- domain and service modules
        +-- provider-neutral email and AI adapters
        v
SQLAlchemy -> SQLite
```

The frontend never talks directly to SQLite, an AI provider, or an email provider.

## Two browser surfaces

The same frontend bundle selects its entry surface from the host in production and the query
string in development:

- committee screener: `screener.pentacoop.com` or the normal local root;
- applicant form: `applications.pentacoop.com` or `http://localhost:5173/?applicant`.

`frontend/src/main.tsx` chooses the surface. `App.tsx` owns the committee shell, while
`ApplicantApp.tsx` owns intake. Shared branding and account controls live in small components
rather than being duplicated between them.
`hooks/useCandidateActions.ts` owns committee status, note, favourite, and shortlist writes and
their view refreshes. It updates the open detail only while the same applicant and opening remain
selected; favourites and shortlist changes refresh the whole cached pool so filtered-out rows
still contribute current facet counts.
Candidate mutations acknowledge only the fields they own, merged into the loaded detail.
Writes share a queue per applicant and field group; independent fields save concurrently without
replacing unrelated state. Notes, favourites, and shortlist responses don't rebuild ranking or
load AI history. Eligibility responses compute only the current eligibility fields.

`frontend/src/styles.css` is the single ordered stylesheet entrypoint. Screen, responsive, and
print rules live with their owning surface (`applications`, candidate detail/notes, ranking,
observability, evals, feedback, and print) rather than relying on a cross-feature catch-all.
`components/ai/AIWorkspaceView.tsx` is the shared shell for the Observability and Evals tabs.

`components/workflow/WorkflowBar.tsx` owns the Screen/Rank strip and progress display.
`RankingRunConfirmation.tsx` owns the ranking cost confirmation, its heading, and the priority
between scoring missing applicants and discovering criteria. Both read run state from `useAiRuns`.
The shared NDJSON reader accepts a final event without a trailing newline and releases its reader
on completion or failure. Screen, Rank, and Evals require a summary or fatal error before treating
the stream as finished; an earlier end reports interrupted progress and preserves saved results.
Run completion and proposal restoration retain their opening generation, so an earlier run
cannot clear another opening's candidate or restore its old proposals into that workspace.

`components/admin/OpeningsPanel.tsx` owns the opening list and navigation between workflows.
`OpeningEditor.tsx` owns the editable opening draft, notification-audience preview, publication,
and updates. `OpeningDecisionPanel.tsx` owns household selection, permanent-decision confirmation,
and outcome-email queue acknowledgement. `DirectSelectionOpeningForm.tsx` owns filling a new home from
previous applicants. Draft and confirmation state live in their workflow; the list owns
the shared busy flag used to disable competing actions. Workflows report completion to the list.
Opening edits carry both the originally displayed facts and proposed changes. A conditional update
rejects stale snapshots; the response acknowledges the submitted facts, and newer typing remains
in the editor. Reloading conflicting saved facts is explicit and replaces the draft. Publication
freezes its announcement facts while that irreversible action is awaiting confirmation.

Feedback submission follows the same draft acknowledgement rule. Each composer lifetime scopes
its pending work; cancelling and reopening cannot let an older response close the new composer.
Admin resolve/reopen actions track pending state per row and release it on failure. Their database
updates apply the requested state atomically and preserve an existing resolution timestamp.

Eval run controls and case editing live in `components/evals/RunnableEval.tsx`. `EvalCaseList.tsx`
owns case navigation; `EvalResults.tsx` owns result details and historical run markers.
`evalResultPresentation.ts` defines the shared case-status and summary rules. The HTTP boundary
keeps mode and payload correlated in both streamed summaries and saved runs. Case renderers
receive outcomes derived from those whole-run contracts without a mode/payload type assertion.
Saved-run history reads use `useRequestScope`; starting a new eval invalidates earlier history
requests so a late initial response cannot overwrite the new run's results.
Each eval family has its own mounted workspace. The case editor owns its draft, pending save,
and inline error; it closes only when the current draft still matches the acknowledged submission.
Fixture saves are ordered because responses contain the full case list. Accepted saves invalidate
earlier fixture reads, and an earlier editor's completion cannot close a newer case editor.

`hooks/useSharedSettings.ts` keeps the accepted server configuration separate from its editable
draft. Save completion acknowledges the submitted snapshot and preserves edits made while the
request was in flight. Older settings reads cannot roll back a completed save.
`hooks/useEligibilityRules.ts` applies the same acknowledgement rule to both eligibility editors.
Each draft belongs to its opening and rule kind; save and reset share one busy state, and a late
response from an opening the member has left cannot change the current editor. Private-note
autosaves run through a serial queue in `CandidateNotes.tsx`; even a revert waits for earlier
writes before comparing against the last acknowledged server value.
Superseded drafts waiting in that queue are skipped; a save already sent must finish before the
latest draft is sent. Committee-note saves preserve any newer text typed while saving.

Applicant persistence is orchestrated by `useApplicantPersistence.ts`; `applicantPersistenceState.ts`
defines its state, defaults, and typed partial updates. Each workflow updates related fields in
one patch beside the operation that owns them; functional patches read the latest state when needed.
`frontend/src/applicant/types.ts` defines the applicant form and answer contracts;
`applicationDraft.ts` owns draft defaults, household calculations, residence-history filtering,
and conversions between editable drafts and saved or submitted answers.
`applicantSaveFlow.ts` owns saving, review preparation, submission, and return-link requests;
email changes and session exit live in `applicantEmailFlow.ts` and `applicantWithdrawalFlow.ts`.
Save completion acknowledges the draft snapshot captured before the request, so edits made
while saving remain unsaved. Save actions read one live state reference at request boundaries;
the captured request snapshot remains the acknowledgement baseline when the response arrives.
Applicant save responses capture their answers and revision before commit. Submission also
stages its confirmation in that transaction; the outbox delivers after the response, so provider
latency cannot turn another tab's later revision into the earlier save's acknowledgement.
Email-identity refreshes use the same application read scope; saves and session exit invalidate
older identity responses before they can restore cleared fields or falsely flag this browser's save.
Rejected network requests and unreadable acknowledgements report an unconfirmed action and
release busy controls while retaining drafts and the last acknowledged revision. Writes are not
retried automatically; retries use the existing revision checks. Recovery belongs to the workflow
that owns the action, so a late failure cannot restore errors into an exited session.
Captured writes also belong to an applicant session generation. Sign-out, withdrawal, a credential
switch, and draft discard end that generation before awaiting network replies, so a late save,
email change, or reconciliation cannot repopulate the exited application. Committee sign-out
clears its user only after the server confirms success; failures retain the session and report an error.
Committee link inspection and exchange have a retryable connection state; retry checks the link
again before deciding whether to exchange it or offer an account choice. Sign-in requests are
ordered, and resetting the form invalidates older responses. Access-allowlist writes hold their
busy state through response parsing and preserve invitation drafts edited during a request.
Vacancy support actions belong to the accepted exact-email lookup. Editing that address invalidates
pending work and hides its actions; deletion uses the accepted subscription's email.
Subscription saves upsert atomically on normalized email while preserving first consent. Each
prepared opening email captures the current matching request's consent timestamp; acceptance
deletes the subscription only if that timestamp still matches, preserving updates and re-subscriptions
made during provider I/O. Pending list-only notices no longer matching the requested unit sizes are
cancelled; application notices continue independently and consume only a matching subscription.

## Applicant intake

Applicant-facing routes live in the `backend/app/api/applicant/` package, grouped into guest,
access-link, and authenticated-application workflows. Application-copy operations live in
`backend/app/services/applications/intake.py`. `applications/access.py` owns access-link inspection
and claims, draft reconciliation, identity collisions, and edit guards. Applicant route
`presentation.py` owns HTTP response serialization. Browser credentials and Google identity claims
live in the `services/auth/` package.

An `Application` has two meaningful representations:

- its private working answers in `working_answers`; and
- its committee-visible submitted fields plus immutable `ApplicationVersion` history.

Saving a draft changes only the working copy. Submitting validates the answers, publishes them
onto the committee-visible columns, records a version, and updates the selected
`ApplicationParticipation` rows. Committee pool queries require an opening and read only its
submitted participants, so private drafts cannot accidentally enter screening.
Applicant save, submit, and authenticated return-link requests check the working revision with a
conditional database update that holds the write lock through the working-copy save and commit.
The check therefore covers overlapping requests as well as an already-stale browser tab.
Private-copy reconciliation carries the displayed application revision and the guest draft's
saved timestamp. Both copies are checked under the application write lock before either is
chosen or discarded; a changed comparison is refreshed without replacing local form edits.
Email confirmation reloads answers under that lock and merges the verified email into the
current working copy, preserving concurrent saves and advancing their revision.

Openings are independent records. Their dates derive upcoming, open, and closed phases; a permanent
committee decision archives an opening. Applicants can join open openings, withdraw from open or
closed openings, and cannot change archived participation. The committee selects one opening as its complete workspace;
archived openings remain selectable while they retain a non-selected applicant. A selected
household remains visible in the opening where it was selected, but neither enters its AI pool nor
keeps that opening in the selector by itself.
Opening decisions take a database write lock and refresh the opening before reading participants.
A competing decision cannot replace an archived outcome; repeating the same decision is idempotent.
Household selection and withdrawal first acquire the same application write lock and reload its
lifecycle, preventing both from succeeding concurrently. Selection then locks the opening in that
order. Committee metadata writes use the application lock through their short check-and-write
transaction, also preventing duplicate first private-note and favourite inserts. These locks never
span email or AI network calls.
Decision outcomes and due closeout-email intents commit together. The HTTP acknowledgement
returns the updated opening list and queued count before provider I/O; the existing outbox runs
in the response background task. Acceptance updates the ledger and participation notification
markers together. Repeated decisions find the same intents and do not send duplicate notices;
daily maintenance rechecks eligibility before staging outstanding closeouts and draining the outbox.
Retention sweeps first collect due record IDs, then recheck each application's retention date
under the same application lock before recording and performing deletion. Draft deletion uses
a conditional write to recheck expiry or resolution, so an opening extension or renewed draft
can make a previously selected record ineligible for cleanup.

Submitted applications flow directly into the database and become available to the committee.
The committee client refreshes its lightweight application and workflow reads on focus, on
visibility return, and every 60 seconds while visible.

## Authentication and sessions

Committee members may use identity-only Google OIDC or an emailed magic link. Applicants may use
identity-only Google OIDC or an emailed magic link, while new applicants may also continue as
guests. Both authenticated applicant routes end in the same revocable `BrowserSession` keyed by
`Application.id`. Applicant and committee access use separate host-only cookies so both identities
can coexist safely.

Session policy is implemented server-side: sessions expire after 7 days of inactivity or 30 days
in total. Any valid session may perform the actions authorized for its identity and role; there is
no separate recent-sign-in window.

The access allowlist gates committee sign-in regardless of identity provider. Google provides
identity only; it has no access to application data. Adding a new allowlist entry creates or
reactivates its committee user and queues a role-specific invitation in the same transaction.
The outbox issues its magic link and sends it after the response. Role changes do not resend
invitations, and delivery failure does not roll back access.

## Transactional email boundary

Email templates and delivery orchestration are provider-neutral. Templates are grouped by
recipient journey under `services/email/templates/`; `layout.py` owns the branded primitives
used by applicant, access, and opening messages. `services/email/sender.py` translates `OutboundEmail` into
SocketLabs requests at the final adapter boundary.

`EMAIL_DELIVERY_MODE` has three values:

- `capture`: retain messages in memory and perform no network I/O;
- `development`: deliver through SocketLabs only after a fail-closed exact-domain check;
- `production`: normal transactional delivery.

Development delivery permits exactly `jeffo.net` and `pentacoop.com`. The adapter validates its
sender, reply-to, and every To/CC/BCC address before invoking SocketLabs. Subdomains and lookalike
domains do not match.

Every provider attempt is reserved in `EmailDelivery` before network I/O. Temporary provider and
quota failures retain a small semantic retry intent, not the rendered body. Credential intents are
rebuilt with a fresh, immediately usable token for each attempt; an unsuccessful attempt revokes
that token. A newer credential request supersedes an older queued one for the same identity and
purpose.
Email-change retries retain the destination and initiating session of the original request.
Cancelling an email change discards its queued confirmations and revokes its unused credentials
in one transaction, while other application email intents remain available.
`services/email/retry_intents.py` defines the credential-free JSON shapes shared by initial sends,
opening notifications, and the outbox worker. The ledger stores those same shapes as JSON.
Initial sends and retries reserve attempts atomically. The existing attempt timestamp supplies a
10-minute lease and the captured attempt counter guards completion. Each message receives a fresh
claim timestamp. Outbox workers claim an intent before
rebuilding its credential, commit that credential before network I/O, and cannot overwrite a
cancelled intent or a newer attempt's outcome with a late provider response.

Accepted deliveries clear any targetless recipient address from the application ledger. An accepted
list-only vacancy delivery is deleted with its consumed subscription. Queued and unexpectedly failed
deliveries retain enough routing information for the admin-only Email Delivery report to show the
recipient, attempted time, message kind, state, attempts, and error code. Terminal list-only vacancy
failures are deleted after 30 days. The report excludes expected cancellations and never stores
rendered bodies or credentials.

Ordinary application traffic claims a durable once-per-Pacific-day maintenance lease in a response
background task. The pass queues due unsuccessful notices, retries queued mail, performs due
application-retention deletion, and deletes expired list-only vacancy failures. Health checks, static
assets, and CORS preflight requests do not trigger it.
Administrators see queued, provider-quota-blocked, and recent unexpected failure counts in the
action banner. SocketLabs, not the application, owns bounce, complaint, suppression, plan
reporting, and account notifications.

## Committee workflow

The visible workflow has two paid steps:

1. **Screen** runs the per-application integrity pass.
2. **Rank** discovers criteria, decomposes them, matches prior identities, scores applicants, and
   consolidates duplicate dimensions.

`backend/app/api/dashboard.py` reports whether the selected opening has submitted applications and
whether each AI stage is current for that opening. Coverage is content-addressed: an applicant edit
changes its content hash and makes only affected results stale. Rules, eligibility decisions,
Shared shortlist membership, analyses, tiers, workflow state, and AI cost attribution all use the
same selected opening. Private favourites and notes remain application-wide, while canonical
dimension history and matching caches remain shared so equivalent work can be reused. Attributed
committee notes are also application-wide and shared with every committee member; neither private
nor committee notes enter AI inputs.

The frontend holds the few-hundred-row committee list in memory and derives search, sorting,
facets, favourites, and opening filters locally. Server reads remain the source of truth after
mutations.

`frontend/src/hooks/useRequestScope.ts` guards async reads against superseded requests, changed
resource scope, and unmounting. Application lists, workflow state, ranking boards, and candidate
detail navigation use that boundary. Background refresh failures preserve the last successful
data within the current workspace. Tier and proposal writes share a serial queue in `useRanking.ts`;
queued writes retain their opening and analysis scope, and only the latest edit's response updates
its optimistic display. A write for an opening the member has left cannot update the new workspace.
Every ranking mutation invalidates older board reads. A failed save waits for already-queued
edits to settle, then reloads the displayed board or the current-run metadata if no board is loaded.
Backend edits hold the run-lease row from the policy check through commit, so Rank cannot start
between checking the current analysis and saving a tier or proposal. Member JSON is reloaded
under the writer lock before merging independently editable fields. First eligibility-rule saves
use atomic upserts on their existing member/opening identity.
`GET /ranking/board` captures one member view and returns its criteria, ranking, and tiers together.
Lightweight current-run reads do not replace the criteria of a displayed board independently.
Concurrent first reads that create the same member view return the winning record rather than
failing on the uniqueness constraint. Run leases return their user and acquisition timestamp;
release matches both, so an expired run cannot release a same-user replacement.
Ranking score assembly reads the newest result per applicant and criterion in one query, using
row ID to break equal timestamps. It fetches only the fields used by ranking and preserves criterion
order for the deterministic calculation.
Candidate details capture their analysis, parsed criteria, and latest score/provenance rows once.
The pure candidate score snapshot is reused in the pool calculation; that applicant's score rows
are excluded from the second read. The trace loads current rows without old history or narratives.
This prevents a newer analysis or score result from being attributed to previously displayed values.

## Responsiveness

Confirmed mutations release their UI controls before refreshing derived views. A completed Rank
starts one coherent board read and a dashboard refresh in the background, without first awaiting
another `/ranking/current` read. Passive stale-analysis checks wait for that board refresh so our
own completed run doesn't appear as another member's update. Applicant sign-out likewise clears
the confirmed session before refreshing public openings.

An offline SQLite comparison on 2026-10-03 used 150 synthetic applicants and 15 criteria, five
samples per operation, and excluded authentication lookup, network, and browser rendering.
Compared with the preceding code, the board fell from 34 to 20 SELECTs (median 46.5 to 35.0 ms);
a private-note save fell from 42 to 4 SELECTs (39.3 to 3.0 ms). These are local diagnostic results,
not production latency guarantees. Regression tests enforce one score query across criterion counts
and prevent metadata mutations from rebuilding the full detail.
The application list batches selected-household IDs in one read. A subsequent five-sample comparison
with 150 synthetic applicants reduced that list from 158 to 9 SELECTs (median 46.1 to 11.9 ms),
with authentication lookup, network, and browser work excluded.
A latest-score trace comparison used 15 criteria with 50 synthetic result versions each.
Loading only the current rows reduced materialized results from 750 to 15 and the five-sample
median trace read from 12.3 to 1.8 ms, with identical output. This excludes network and UI work.

Eval case and judge-brief writes share a short lock per fixture in the API process, covering the
entire read/modify/write. JSON is published through a flushed UTF-8 temporary file and atomic
replacement; a failed replacement leaves the old fixture intact. This matches the single-process
deployment. A separate CLI or another API process editing the same fixture would need shared
coordination. Judge-brief acknowledgements clear only the submitted draft, preserving later edits;
different passes can save independently.

## Eligibility and status

`backend/app/domain/hard_filters.py` is pure deterministic policy. It accepts normalized
application facts and a `RulesConfig`; it knows nothing about FastAPI, SQLAlchemy, or React.

Eligibility is computed on read rather than stored as a final verdict:

```text
submitted fields + current member rules + cached AI findings + member override
                                    |
                                    v
                       effective status and source
```

Structured-field reasons attribute to Rules. Pet limits attribute to AI because the screening
pass first extracts pet facts from free text. A member's explicit override is sticky and is never
overwritten by a later machine calculation.

`backend/app/services/applications/screening_results.py` loads only the latest screening row for each requested
application, using the row ID to break equal timestamps. Eligibility and list presentation derive
flags and pet facts from those same rows in one query; candidate details use the same loader for
their screening trace. An absent result means unscreened, an empty flag list means screened clean,
and missing pet facts remain unknown.

## AI boundary and caching

`backend/app/ai/provider.py` defines the application-facing provider contract. Model catalog
entries identify vendor, route, model, and reasoning support. Downstream screening and ranking
code does not branch on Bedrock versus direct APIs.

Each pass owns:

- a structured output schema;
- a derived prompt version;
- a model and applicable reasoning level;
- a cost estimate;
- a content-addressed cache identity;
- stored reasoning and usage trace.

Application cache keys depend on semantic model identity, prompt version, reasoning level, and
application content—not on an equivalent provider route. Ranking freshness adds the eligible
pool and every rank-chain pass identity.
Screening and dimension scoring capture their cache keys alongside the model inputs before calls
start. Result persistence uses those captured keys, so an applicant edit during a run leaves the
answer attached to the content actually analyzed and keeps the newer content uncached.
Full Rank and score-current capture the eligible pool's fingerprint before AI work begins and
persist that original identity. An edit or new applicant during a run keeps Rank out of date.
Dimension scoring carries each applicant's input, cache keys, pending dimensions, and cached
scores in a named `ScoringPlan`; worker calls read its captured input without touching the ORM.

The main AI modules are:

- `screening.py`: integrity flags and extracted pet facts;
- `pool_digest.py`: bounded pool context;
- `dimension_discovery.py`: parallel candidate-dimension discovery;
- `dimension_decomposition.py`: one non-overlapping dimension set;
- `dimension_matching.py`: carry-forward matching;
- `dimension_scoring.py`: per-application scores and evidence;
- `dimension_consolidation.py`: post-score duplicate confirmation.

Orchestration is deterministic code. Models never decide which pass runs next, and ranking is
pure weighted math over cached scores.

`services/ranking/criteria.py` runs discovery, decomposition, and matching, returning their audits,
costs, and durations with the settled report. `pipeline.py` loads prior state, streams the worker's
reasoning and stage changes, and writes the completed result on the request thread.
The criteria phase event carries `discoveryWorkers`; scoring progress carries `processed` and
`total` candidate counts. Frontend progress types distinguish those phases explicitly.

## Data model

The central tables are:

- `applications`: identity, private working answers, current submitted representation, lifecycle,
  and synthetic provenance;
- `application_versions`: immutable submitted versions;
- `openings` and `application_participations`: application-intake or direct-selection vacancy
  configuration, participation, and outcomes;
- `browser_sessions` and token-credential tables: revocable authentication;
- `application_ai_results`: cached per-application passes;
- `analyses`, `analysis_audits`, dimension definitions, and scores: opening-specific Rank runs over
  shared canonical dimension history and content-addressed scores;
- opening committee defaults, per-opening member rules and eligibility overrides, opening-specific
  Shared shortlist membership, application-wide private and committee notes, stars, allowlist,
  feedback, and settings.

SQLAlchemy models live in `backend/app/db/models.py`. Alembic migrations are the only supported
way to change an existing database. Additive migrations apply in place; never delete the local
database without explicit approval.

Ranking state is intentionally split by ownership: `backend/app/services/ranking/analysis.py`
persists the shared committee analysis, `backend/app/services/ranking/member_state.py` owns each
member's tiers and proposals, and `backend/app/services/ranking/dimensions.py` parses the stored
dimension report used by both.

## Synthetic local data

`test-data/synthetic-penta-application-responses.csv` mirrors the canonical built-in application
shape. `backend/app/services/applications/synthetic_fixture.py` parses and validates every row through the same
Pydantic schema used by intake.

The loader is deliberately narrow:

```sh
cd backend
uv run python -m scripts.load_synthetic_applications --opening-id 1 --opening-id 2
```

It requires `APPLICATION_DATA_IS_SYNTHETIC=true`, SQLite, and published non-archived openings.
Repeated `--opening-id` arguments connect every fixture applicant to each target opening. It sends
no email, is idempotent by primary email plus content/opening state, and refuses to replace an
application not already stamped synthetic.

Synthetic provenance is persisted on applications and copied onto each analysis when the entire
pool is synthetic. Evidence-harvesting tools fail closed unless the analysis carries that stamp;
filenames and email domains never establish safety.

## Configuration

Runtime secrets and host-specific behavior live in environment variables. Shared AI settings and
per-member eligibility rules live in the database. Important local-only controls include:

- `EMAIL_DELIVERY_MODE`;
- `APPLICATION_DATA_IS_SYNTHETIC`;
- provider credentials;
- session and OAuth secrets;
- frontend/backend origins.

Safe placeholders belong in `.env.example`; actual `.env.local` files are ignored.

## Where code belongs

- `backend/app/api/`: HTTP translation, dependencies, and status codes;
- `backend/app/services/`: reusable database-backed operations and external boundaries;
- `backend/app/domain/`: framework-free business rules;
- `backend/app/schemas/`: request/response and structured data contracts;
- `backend/app/ai/`: prompts, pass schemas, model catalog, providers, and costs;
- `frontend/src/components/`: visual surfaces grouped by committee feature, with reusable controls
  under `shared/`;
- `frontend/src/hooks/`: stateful data orchestration;
- `frontend/src/api/`: browser HTTP boundary, split by backend domain over one shared client;
- `frontend/src/applicant/`: applicant UI, draft contracts and conversions, and persistence flows;
- `frontend/src/types/`: committee-facing TypeScript data contracts;
- `backend/tests/`: behavior and contract coverage.

Service packages group related workflows under one discoverable owner:

| Package | Responsibility |
| --- | --- |
| `services/applications/` | Answers, working copies, submitted intake, access policy, retention, and committee saved views |
| `services/auth/` | Applicant and committee identity, credentials, browser sessions, allowlist, and public request limits |
| `services/openings/` | Publication, participation, selection, outcomes, vacancy subscriptions, and notification audiences |
| `services/email/` | Transport, delivery ledger, retry intents, transactional delivery, SocketLabs reporting, and `templates/` |
| `services/eligibility/` | Member rules, check descriptions, machine status, and effective eligibility pools |
| `services/ranking/` | Shared analyses, member rankings, pipeline orchestration, freshness, costs, audits, and presentation |

Cross-workflow infrastructure stays at the service root: settings, maintenance, backups, run locks,
stream workers, feedback, metrics, and cost reporting. Package initializers describe ownership;
callers import concrete modules so dependencies remain visible.

For common changes, start at the owner below and follow its imports:

| Change | Start here | Related implementation |
| --- | --- | --- |
| Applicant form fields and answer shape | `frontend/src/applicant/ApplicantFormSections.tsx` | Applicant `types.ts`, `applicationDraft.ts`, and `backend/app/schemas/applicant/answers.py` |
| Save or submit an application | `backend/app/api/applicant/application.py` | `services/applications/intake.py`, `services/openings/participation.py`, and frontend `applicantSaveFlow.ts` |
| Applicant access links and email changes | `backend/app/services/applications/access.py` | Applicant routes `links.py` and `presentation.py`, `services/auth/passwordless.py`, and `services/email/transactional.py` |
| Committee candidate actions | `frontend/src/hooks/useCandidateActions.ts` | `frontend/src/api/applications.ts` and `backend/app/api/applications/routes.py` |
| Opening publication and committee outcomes | `backend/app/api/openings.py` | `services/openings/catalog.py`, `services/openings/selection.py`, and `services/openings/direct_selection.py` |
| Eligibility and member overrides | `backend/app/services/eligibility/evaluation.py` | `services/eligibility/rules.py`, `services/eligibility/status.py`, and `domain/hard_filters.py` |
| AI ranking workflow | `backend/app/services/ranking/pipeline.py` | `app/ai/`, ranking `analysis.py`, and ranking `member_state.py` |
| Email delivery and retries | `backend/app/services/email/delivery.py` | `services/email/sender.py` for transport, `services/email/outbox.py` for retries, and `services/email/templates/` for templates |
| Retention and daily maintenance | `backend/app/services/maintenance.py` | `services/applications/retention.py` and `services/applications/purge.py` |

Ranking routes are grouped under `backend/app/api/ranking/`. The corresponding service package
at `backend/app/services/ranking/` owns the streamed pipeline, cost projections, shared-analysis
state, per-member tier state, audits, freshness, and ranked presentation.

Committee application routes live in `backend/app/api/applications/routes.py`; their list/detail
response assembly lives beside them in `presentation.py` so mutations and presentation can evolve
independently.

Route handlers should stay thin. Business rules belong in services or domain modules, and a rule
should have one named implementation rather than parallel frontend/backend copies whenever the
server can own it.

## Verification

Run backend checks from `backend/`:

```sh
uv run ruff check .
uv run pytest
```

If Windows sandbox permissions prevent access to the shared uv cache, use a workspace-local
cache. From `backend/`, resolve its path before running uv:

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location).Path '.uv-cache'
uv run ruff check .
uv run pytest
```

The cache lives at `backend/.uv-cache` and is ignored by Git. Cache directories are generated
tool data; they are separate from application source and the SQLite data directory.

Run the frontend type and production build from `frontend/`:

```sh
npm run build
```

Browser verification is reserved for interaction-heavy or visual changes. Vite HMR applies
frontend edits without reloading the page.
