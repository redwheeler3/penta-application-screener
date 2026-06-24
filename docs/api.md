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

### Quality Flags (AI) — `app/api/quality_flags.py`

See [ai-screening.md](ai-screening.md) for the full pipeline behind these.

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/quality-flags/estimate` | Projected cost + how many applications would be analyzed vs. cached. | Login |
| POST | `/quality-flags/run` | Run the AI quality-flag pass; streams NDJSON progress, then a summary. | Login |

### Screening — `app/api/screening.py`

The **Rank chain** (milestones 6–8) and the deterministic ranked shortlist (milestone 8). Rank is one button that runs essay summary → find criteria → score, back-to-back; the cap is enforced once over the combined cost. The individual sub-passes are not exposed as endpoints (the committee never runs them alone); `screen_essays` / `discover_patterns` / `screen_dimension_scores` are the underlying passes. Ranking itself is pure math over the cached scores — no model call. See [ai-screening.md](ai-screening.md).

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/screening/rank/estimate` | Combined projected cost of the Rank chain (essays + criteria + scoring), with a per-pass breakdown. Approximate — criteria/scoring scale with essay output. 409 if no eligible applicants. | Login |
| POST | `/screening/rank/run` | Run the full chain. Streams NDJSON: a `phase` line per pass, `progress` lines for the per-candidate passes, then a `summary`. Cap enforced once over the combined cost (402 if over). 409 if no eligible applicants. | Login |
| GET | `/screening/current` | The current run's criteria + summary, or null if the chain has never run. | Login |
| GET | `/screening/ranking` | The deterministic ranked shortlist: candidates ordered by weight-normalized fit, each with a relative band, the shortlist line, and the live above-line count. 409 before criteria exist. | Login |
| PUT | `/screening/shortlist-line` | Move the shortlist line for the current run (`{"shortlist_size": n}`). A reading aid — never removes anyone. 409 before criteria exist. | Login |
