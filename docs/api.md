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
