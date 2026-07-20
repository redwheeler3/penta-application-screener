# API Reference

The backend is a FastAPI app, so the **authoritative, always-current API reference is auto-generated from the code**:

- **Interactive docs (Swagger UI):** `http://localhost:8000/docs`
- **Raw OpenAPI spec:** `http://localhost:8000/openapi.json`

Both reflect the live routes and Pydantic request/response schemas, so they never drift from the code. Use them as the source of truth for exact field shapes, query parameters, and status codes.

This page is just a **map** — a one-line index of every endpoint so you can see the whole surface at a glance. If it ever disagrees with `/docs`, `/docs` is right.

## Endpoint Index

Unless noted, endpoints require a logged-in user (the signed session cookie). There is currently no admin-only endpoint — every committee member is a trusted screener, so all screening surfaces (status override, raw row, AI narrative) are open to any logged-in user. The `admin` / `member` roles exist in the data model but do not gate any route today.

### Auth — `app/api/auth.py`

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/auth/google/login` | Start the Google OAuth flow (redirects to Google). | Public |
| GET | `/auth/google/callback` | OAuth redirect target; upserts the user and sets the session. | Public |
| GET | `/auth/me` | The current user, or `{ "user": null }`. | Public |
| POST | `/auth/logout` | Clear the session cookie. | Public |

### Health — `app/api/health.py`

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/health` | Liveness check. | Public |

### Settings — `app/api/settings.py`

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/settings` | Read the admin settings (plus the resolved Sheet URL/title). | Login |
| PUT | `/settings` | Save the admin settings. | Login |

### Sync — `app/api/sync.py`

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| POST | `/sync/applications` | Import + normalize rows from the configured Google Sheet, apply hard filters. | Login |

### Dashboard — `app/api/dashboard.py`

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/dashboard` | `settingsComplete`, the submitted total, and counts grouped by `status` and `status_source`. | Login |

### Applications — `app/api/applications.py`

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/applications` | Searchable, filterable, sortable, paginated list with faceted counts. | Login |
| GET | `/applications/{id}` | One application's detail, including the raw source row and AI narrative. | Login |
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

### Insights — `app/api/insights.py`

Cross-run observability (M13 Pillars 1 + 3): spend and operational trends over every run kind (Screen, Rank, score-current). Top-level, not under `/ranking`, because they span all runs. No model calls.

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/insights/cost` | Cumulative AI spend, grouped by run. | Login |
| GET | `/insights/last-runs` | The most recent Screen and Rank runs, each with fresh spend + cache savings. | Login |
| GET | `/insights/metrics` | Operational trends across all runs: cost/tokens/latency/cache-hit/failures per run and pass. | Login |

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
