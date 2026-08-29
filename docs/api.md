# API Reference

The backend is a FastAPI app, so the **authoritative, always-current API reference is auto-generated from the code**:

- **Interactive docs (Swagger UI):** `http://localhost:8000/docs`
- **Raw OpenAPI spec:** `http://localhost:8000/openapi.json`

Both reflect the live routes and Pydantic request/response schemas, so they never drift from the code. Use them as the source of truth for exact field shapes, query parameters, and status codes.

This page is just a **map** — a one-line index of every endpoint so you can see the whole surface at a glance. If it ever disagrees with `/docs`, `/docs` is right.

## Endpoint Index

Unless noted, endpoints require a logged-in committee user through the opaque server-side session
cookie. Core review surfaces are available to every committee member; access management, shared
configuration, committee defaults, Observability, and Evals require an admin.

### Auth — `app/api/auth.py`

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/auth/google/login` | Start the Google OAuth flow (redirects to Google). | Public |
| GET | `/auth/google/callback` | Verify Google identity and issue a committee browser session. | Public |
| POST | `/auth/magic-link` | Request an allowlist-gated committee sign-in email. | Public |
| POST | `/auth/magic-link/consume` | Consume a committee link and issue the same browser session used by Google. | Public |
| POST | `/auth/magic-link/inspect` | Inspect a committee link and identify a conflicting active committee session without consuming the credential. | Public |
| POST | `/auth/magic-link/regenerate` | Request a replacement for a recognizable stale committee link without asking for the address again. | Public |
| POST | `/applicant/access-links/inspect` | Inspect an applicant link without consuming it, including cross-session conflicts. | Public |
| POST | `/applicant/access-links/open` | Consume a valid applicant link with its switch and remembered-device choices. | Public |
| POST | `/applicant/access-links/regenerate` | Email a replacement for a recognizable stale applicant link. | Public |
| GET | `/applicant/auth/me` | Return the current application identity, if any. | Public |
| POST | `/applicant/auth/logout` | Revoke the current applicant session. | Public |
| GET | `/auth/me` | Return the current user, if any, and whether email sign-in is enabled. | Public |
| POST | `/auth/logout` | Revoke the current committee session. | Public |

### Applicant intake — `app/api/applicant/` (package)

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/applicant/openings` | Return published openings and whether a guest may begin an application. | Public |
| POST | `/applicant/submissions/check` | Before guest review, require email access when a current application already owns the address. | Public |
| POST | `/applicant/submissions` | Publish a completed guest application and email confirmation with future access. | Public |
| POST | `/applicant/drafts` | Save an incomplete private pending draft and request its access link. | Public |
| DELETE | `/applicant/drafts` | Discard an unclaimed pending draft using a body-held credential. | Draft token |
| POST | `/applicant/access-links/request` | Safely start or return to an application and email its access link without revealing which path occurred. | Public or applicant |
| GET | `/applicant/application` | Read the authenticated working application. | Applicant |
| PUT | `/applicant/application` | Save the authenticated private working copy. | Applicant |
| POST | `/applicant/application/revert` | Replace private edits and pending opening choices with the last submitted application. | Applicant |
| POST | `/applicant/application/withdraw` | Withdraw from every opening, remove ordinary applicant access, and revoke applicant sessions and links. | Applicant |
| POST | `/applicant/application/email-change` | Email a confirmation link for a new primary address. | Applicant |
| DELETE | `/applicant/application/email-change` | Cancel an unconfirmed primary-address change. | Applicant |
| POST | `/applicant/application/submit` | Publish the validated working copy and update explicit participation in the selected openings. | Applicant |

### Openings — `app/api/openings.py`

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/openings` | List configured openings, derived phases, and active submission counts. | Admin |
| POST | `/openings/preview` | Count the current notification audience and show message variants plus current/projected SocketLabs usage. | Admin |
| POST | `/openings` | Open applications immediately and atomically queue the confirmed notification audience. | Admin |
| POST | `/openings/previous-applicants/search` | Search retained, available previous applicants by name or email without exposing them to ordinary workflows. | Admin |
| POST | `/openings/direct-selection` | Atomically create a filled opening and select one previous applicant without queueing email. | Admin |
| DELETE | `/openings/{id}/direct-selection` | Remove a directly filled opening before move-in and restore the applicant's prior scope and retention. | Admin |
| PUT | `/openings/{id}` | Update an application-intake opening, including an archived historical record. | Admin |

### Vacancy notifications — `app/api/vacancy_subscriptions.py`

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| POST | `/vacancy-subscriptions` | Add or replace one address's complete unit-size selection without revealing prior state. | Public |
| GET | `/vacancy-subscriptions/report` | Return active total, overlapping bedroom counts, and monthly consent distribution. | Admin |
| POST | `/vacancy-subscriptions/admin/lookup` | Look up one exact normalized address with first-subscription time, current-update time, and source. | Admin |
| PUT | `/vacancy-subscriptions/admin` | Add or replace one exact address with an audited request source. | Admin |
| POST | `/vacancy-subscriptions/admin/delete` | Delete one exact address and record a PII-minimized audit event. | Admin |

### Health — `app/api/health.py`

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/health` | Liveness check. | Public |

### Settings — `app/api/settings.py`

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/settings` | Read the shared AI settings and supported model catalog. | Login |
| PUT | `/settings` | Save the admin settings. | Login |

### Dashboard — `app/api/dashboard.py`

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/dashboard` | Read Screen/Rank availability, currentness, and cache coverage. | Login |
| GET | `/dashboard/email-deliveries` | List queued and unexpectedly failed email attempts. | Admin |

### Applications — `app/api/applications/` (package)

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/applications` | Unpaginated committee pool with opening participation and the opening filter catalog. | Login |
| GET | `/applications/{id}` | One application's detail, including its openings, raw source row, and AI narrative. | Login |
| GET | `/applications/{id}/retained` | Read a selected or direct-fill-eligible application outside ordinary committee scope. | Admin |
| PATCH | `/applications/{id}/status` | Human status override (sets `status_source = human`, which is sticky). | Login |
| DELETE | `/applications/{id}/status` | Remove a human override; recomputes status from the current findings (rules then AI) and clears human ownership. Idempotent if no override is set. | Login |

### Screening — `app/api/screening.py`

The Screen step: one AI pass that flags quality issues on eligible applicants. See
[ai-screening.md](ai-screening.md) for the full pipeline. Every runnable job follows `POST <job>` + `GET <job>/estimate` (the estimate is a sub-path of the run it prices).

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/screening/run/estimate` | Projected cost + how many applicants would be analyzed vs. cached. | Login |
| POST | `/screening/run` | Run the screening pass; streams NDJSON `progress` then a `summary`. Cap enforced (402 if over). | Login |

### Ranking — `app/api/ranking/` (package)

The **Rank chain** and the deterministic ranked shortlist. Rank is one button that runs pattern discovery → decomposition → identity-match → score → consolidate, back-to-back; the cap is enforced once over the combined cost. The sub-passes are not exposed individually (the committee never runs them alone). Ranking itself is pure math over the cached scores — no model call. See [ai-screening.md](ai-screening.md).

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/ranking/run/estimate` | Combined projected cost of the Rank chain, with a per-pass breakdown. Approximate — scoring scales with the dimensions discovery settles on. 409 if no eligible applicants. | Login |
| POST | `/ranking/run` | Run the full chain. Streams NDJSON: a `phase` line per pass, `progress` lines for the per-candidate passes, then a `summary`. Cap enforced once over the combined cost (402 if over). 409 if no eligible applicants. | Login |
| GET | `/ranking/score-current/estimate` | Cost to fill missing scores against the current criteria (no re-discovery). | Login |
| POST | `/ranking/score-current` | Score only applicants missing scores for the current criteria; streams like `/ranking/run`. | Login |
| GET | `/ranking/current` | The current run's criteria + summary, or null if the chain has never run. | Login |
| GET | `/ranking/current/{match,decompose,consolidate,fan-out}-audit` | Per-run AI-legibility audits (null on runs predating each capture). | Login |
| GET | `/ranking` | The deterministic ranked shortlist: candidates ordered by weight-normalized fit, each with a relative band. Stack-ranked — no fixed cut line. 409 before criteria exist. | Login |
| GET | `/ranking/tiers` | The current run's importance-tier layout (or the default single-tier = equal-weight layout). 409 before a run exists. | Login |
| PUT | `/ranking/tiers` | Persist a new tier layout, derive weights from it, and return the freshly re-sorted ranking. Unknown dimension keys → 422; no run → 409. No model call. | Login |
| PUT | `/ranking/seeds` | Persist pending free-text dimension proposals for the next Rank's discovery. 409 before a run exists. | Login |

### Observability — `app/api/observability.py`

Cross-run observability (M13 Pillars 1 + 3): spend and operational trends over every run kind (Screen, Rank, score-current). Top-level, not under `/ranking`, because they span all runs. No model calls.

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/observability/cost` | Cumulative AI spend, grouped by run. | Login |
| GET | `/observability/last-runs` | The most recent Screen and Rank runs, each with fresh spend + cache savings. | Login |
| GET | `/observability/metrics` | Operational trends across all runs: cost/tokens/latency/cache-hit/failures per run and pass. | Login |

### Evals — `app/api/evals/` (package)

The in-UI eval cockpit. Catalog + invariants + case reads are free (no model calls); the run endpoints stream NDJSON (`thinking` then a terminal `summary`) and persist an `EvalRun` row. Each pass is **one** run route — `?mode=stability` selects the K-repeat stability run (`k` clamped 2–10), `?case=<key>` runs a single case. See [ai-evals.md](ai-evals.md).

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/evals/catalog` | The runnable evals + spend flags/estimates (free). | Login |
| GET | `/evals/invariants` | Deterministic invariants over the baseline fixture (free). | Login |
| POST | `/evals/baseline` | Re-record the invariant baseline from the current Rank (409 if no run). | Login |
| GET / PUT | `/evals/cases/{eval_key}` | Read / upsert a pass's golden cases (validated; committed to git by hand). | Login |
| GET | `/evals/judge-backgrounds` | The per-pass judge briefs + golden case counts. | Login |
| PUT | `/evals/judge-backgrounds/{pass_name}` | Write one pass's judge brief to its golden file. | Login |
| GET | `/evals/last-run?keys=…` | The newest persisted run per key (to restore a tab); carries a `stale` flag. | Login |
| POST | `/evals/{scoring,screening,consolidation,matching,decomposition}` | Run one live pass. `?mode=stability` for the K-repeat run. Streams; spends $. | Login |
| POST | `/evals/judge` | Blind label-audit over every pass's golden cases + agreement/κ. `?mode=stability` blind-audits each case K times (persisted under `stability`). Streams; spends $. | Login |
