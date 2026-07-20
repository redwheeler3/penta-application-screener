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

### Quality Flags (AI) — `app/api/quality_flags.py`

See [ai-screening.md](ai-screening.md) for the full pipeline behind these.

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/quality-flags/estimate` | Projected cost + how many applications would be analyzed vs. cached. | Login |
| POST | `/quality-flags/run` | Run the AI quality-flag pass; streams NDJSON progress, then a summary. | Login |

### Screening — `app/api/screening.py`

The Screen step: one AI pass that flags quality issues on eligible applicants. Every runnable job follows `POST <job>` + `GET <job>/estimate` (the estimate is a sub-path of the run it prices).

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
