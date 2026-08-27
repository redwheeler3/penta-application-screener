# Application Architecture

This document is the practical map of the current codebase. Exact HTTP contracts belong to the
generated OpenAPI document at `/docs`; product policy belongs in [SPEC.md](../SPEC.md).

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

## Applicant intake

Applicant-facing routes live in the `backend/app/api/applicant/` package, grouped into guest,
access-link, and authenticated-application workflows. Domain operations are in
`backend/app/services/intake.py`, with authentication and draft-link concerns separated into
their own services.

An `Application` has two meaningful representations:

- its private working answers in `working_answers`; and
- its committee-visible submitted fields plus immutable `ApplicationVersion` history.

Saving a draft changes only the working copy. Submitting validates the answers, publishes them
onto the committee-visible columns, records a version, and updates the selected
`ApplicationParticipation` rows. Committee queries use `committee_applications`, so private
drafts cannot accidentally enter screening.

Openings are independent records with open, closed, and archived phases derived from their three
dates. Applicants can join open openings, withdraw from open or closed openings, and cannot
change archived participation. The committee can filter the application list and ranking by
current openings; archived openings remain available only in administration and retained history.

Submitted applications are already in the database. There is no import or committee sync action.
The committee client refreshes its lightweight application and workflow reads on focus, on
visibility return, and every 60 seconds while visible.

## Authentication and sessions

Committee members may use identity-only Google OIDC or an emailed magic link. Both routes end in
the same revocable `BrowserSession`. Applicant access is email-link based and uses a separate,
host-only session cookie so applicant and committee identities can coexist safely.

Session policy is implemented server-side:

- 1 day recent-auth window for sensitive actions;
- 7 days of inactivity;
- 30 days absolute lifetime.

The access allowlist gates committee sign-in regardless of identity provider. Google provides
identity only; it has no access to application data.

## Transactional email boundary

Email templates and delivery orchestration are provider-neutral. `email_sender.py` translates
`OutboundEmail` into SocketLabs requests at the final adapter boundary.

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

Ordinary application traffic claims a durable once-per-Pacific-day maintenance lease in a response
background task. The pass retries queued mail, sends due unsuccessful notices, and performs due
retention deletion. Health checks, static assets, and CORS preflight requests do not trigger it.
Administrators see queued and provider-quota-blocked counts in the action banner. SocketLabs, not
the application, owns bounce, complaint, suppression, plan reporting, and account notifications.

## Committee workflow

The visible workflow has two paid steps:

1. **Screen** runs the per-application integrity pass.
2. **Rank** discovers criteria, decomposes them, matches prior identities, scores applicants, and
   consolidates duplicate dimensions.

`backend/app/api/dashboard.py` reports whether submitted applications exist and whether each AI
stage is current. Coverage is content-addressed: an applicant edit changes its content hash and
makes only affected results stale. The opening filter changes the committee view, not the shared
analysis pool.

The frontend holds the few-hundred-row committee list in memory and derives search, sorting,
facets, favourites, and opening filters locally. Server reads remain the source of truth after
mutations.

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

The main AI modules are:

- `screening.py`: integrity flags and extracted pet facts;
- `pool_digest.py`: bounded pool context;
- `dimension_discovery.py`: parallel candidate-dimension discovery;
- `dimension_decomposition.py`: one non-overlapping dimension set;
- `dimension_identity.py`: carry-forward matching;
- `dimension_scoring.py`: per-application scores and evidence;
- `dimension_consolidation.py`: post-score duplicate confirmation.

Orchestration is deterministic code. Models never decide which pass runs next, and ranking is
pure weighted math over cached scores.

## Data model

The central tables are:

- `applications`: identity, private working answers, current submitted representation, lifecycle,
  and synthetic provenance;
- `application_versions`: immutable submitted versions;
- `openings` and `application_participations`: vacancy configuration and applicant selection;
- `browser_sessions` and token-credential tables: revocable authentication;
- `application_ai_results`: cached per-application passes;
- `analyses`, `analysis_audits`, dimension definitions, and scores: shared Rank state;
- member eligibility overrides, notes, stars, rules, allowlist, feedback, and settings.

SQLAlchemy models live in `backend/app/db/models.py`. Alembic migrations are the only supported
way to change an existing database. Additive migrations apply in place; never delete the local
database without explicit approval.

## Synthetic local data

`test-data/synthetic-penta-application-responses.csv` mirrors the canonical built-in application
shape. `backend/app/services/synthetic_fixture.py` parses and validates every row through the same
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
- `backend/tests/`: behavior and contract coverage.

Route handlers should stay thin. Business rules belong in services or domain modules, and a rule
should have one named implementation rather than parallel frontend/backend copies whenever the
server can own it.

## Verification

Run backend checks from `backend/`:

```sh
uv run ruff check .
uv run pytest
```

Run the frontend type and production build from `frontend/`:

```sh
npm run build
```

Browser verification is reserved for interaction-heavy or visual changes. Vite HMR applies
frontend edits without reloading the page.
