# Application Architecture

This document explains how the current local MVP is organized, how the frontend works, how the backend works, and how the two communicate.

The application is intentionally simple right now. The goal is to keep the code readable while the product shape is still changing quickly.

## Big Picture

The app has two local development processes:

1. A FastAPI backend running at `http://127.0.0.1:8000`
2. A Vite React frontend running at `http://127.0.0.1:5173`

The frontend is what the user sees in the browser. The backend owns authentication, database access, Google API integration, deterministic screening rules, and later AI integration.

The frontend and backend communicate over HTTP. When authentication is involved, they also share a signed session cookie issued by the backend.

## Frontend

The frontend lives in `frontend/`.

Current important files:

- `frontend/package.json`: npm scripts and frontend dependencies.
- `frontend/vite.config.ts`: Vite configuration.
- `frontend/src/main.tsx`: React entrypoint. It mounts the app into `index.html`.
- `frontend/src/App.tsx`: Current top-level application UI.
- `frontend/src/styles.css`: Current global styling and Penta-inspired palette.
- `frontend/src/vite-env.d.ts`: TypeScript support for Vite environment variables such as `import.meta.env`.

### Frontend Runtime

During local development, start the frontend with:

```powershell
cd frontend
npm run dev -- --host 127.0.0.1
```

Then open:

```text
http://127.0.0.1:5173
```

The frontend is currently a single React screen. It does five main things:

1. On load, call the backend's `/auth/me` endpoint.
2. If no user is logged in, show a Google sign-in panel.
3. If a user is logged in, fetch saved app settings.
4. If a user is logged in, show the dashboard shell with placeholder counts.
5. Let the user open the settings panel from the gear icon.

### Frontend Authentication Flow

In `App.tsx`, the app checks the current user with:

```ts
fetch(`${apiBaseUrl}/auth/me`, { credentials: "include" })
```

The important option is `credentials: "include"`. Without it, the browser would not send the backend session cookie on cross-origin requests from `5173` to `8000`.

When the user clicks "Sign in with Google", the browser is redirected to:

```text
http://127.0.0.1:8000/auth/google/login
```

The backend then redirects the browser to Google's OAuth consent flow. After Google finishes, it redirects back to the backend callback route. If login succeeds, the backend redirects the browser back to the frontend.

When the user clicks logout, the frontend calls:

```text
POST http://127.0.0.1:8000/auth/logout
```

and then clears the local `user` state.

### Frontend Styling

The current look borrows from `pentacoop.com`:

- White and very light gray page surfaces
- Green primary actions and success states
- Blue neutral/action accents
- Orange used sparingly for caution/current-opening accents
- Red reserved for future filtered-out or failure states

The app should remain dashboard-like and operational. It should not become a marketing landing page.

## Backend

The backend lives in `backend/`.

Current important files:

- `backend/pyproject.toml`: Python package metadata, dependencies, and pytest configuration.
- `backend/alembic.ini`: Alembic migration configuration.
- `backend/alembic/`: database migration environment and versions.
- `backend/app/main.py`: FastAPI app factory and middleware registration.
- `backend/app/api/`: HTTP route modules.
- `backend/app/core/`: configuration and OAuth setup.
- `backend/app/db/`: SQLAlchemy models and database session setup.
- `backend/app/domain/`: pure domain logic, including deterministic hard filters.
- `backend/app/services/`: application services that coordinate database work.
- `backend/tests/`: backend tests.

### Backend Runtime

During local development, start the backend with:

```powershell
cd backend
uv run alembic upgrade head
uv run fastapi dev app/main.py --port 8000
```

The health check is:

```text
http://127.0.0.1:8000/health
```

### FastAPI App Setup

`backend/app/main.py` creates the FastAPI app.

It currently installs:

- `SessionMiddleware`, which signs the browser session cookie.
- `CORSMiddleware`, which allows the local React frontend to call the backend with credentials.
- Auth routes from `app.api.auth`.
- Health routes from `app.api.health`.

The app uses an app factory:

```py
def create_app() -> FastAPI:
    ...
```

This makes testing easier because tests can create a fresh app instance.

### Configuration

Configuration lives in `backend/app/core/config.py`.

Settings are loaded from environment variables and local env files:

- `../.env`
- `../.env.local`
- `.env`
- `.env.local`

For this repo, the most important local file is:

```text
backend/.env.local
```

That file is ignored by Git.

The backend supports two ways to configure Google OAuth:

1. Direct environment variables:
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`
2. A downloaded Google OAuth JSON file:
   - `GOOGLE_OAUTH_CLIENT_SECRETS_FILE`

For local MVP development, the JSON file approach is simpler because Google already gives us that file.

### Database

The backend uses SQLite locally through SQLAlchemy.

The default database URL is:

```text
sqlite:///./data/penta_screener.db
```

The SQLite database file is generated locally and ignored by Git.

Alembic owns schema migrations. The current initial migration creates:

- `users`
- `admin_settings`
- `applications`
- `sync_runs`
- `screening_runs`

During MVP iteration, we are not preserving backward compatibility for local schema changes. If the local database shape changes, it is acceptable to delete the generated SQLite file and recreate it from migrations.

### Auth Routes

Auth routes live in `backend/app/api/auth.py`.

Current routes:

- `GET /auth/google/login`
- `GET /auth/google/callback`
- `GET /auth/me`
- `POST /auth/logout`

`/auth/google/login` starts the OAuth flow by redirecting the browser to Google.

`/auth/google/callback` handles Google's redirect back to the app. It exchanges the OAuth code for tokens, extracts user identity, creates or updates a local user record, stores `user_id` in the signed session cookie, and redirects back to the frontend.

`/auth/me` reads the signed session cookie. If it contains a valid active user ID, it returns a serialized user. If not, it returns:

```json
{ "user": null }
```

`/auth/logout` clears the session cookie.

### Settings Routes

Settings routes live in `backend/app/api/settings.py`.

Current routes:

- `GET /settings`
- `PUT /settings`

Settings are stored in the `admin_settings` table as one JSON value under the key `app_settings`.

Current settings:

- Google Sheet link or ID
- Unit size
- Move-in date
- Income minimum
- Income maximum

The defaults match the current planned 2-bedroom opening:

- Unit size: `2br`
- Move-in date: `2026-09-01`
- Income range: `$70,000` to `$150,000`

The settings API currently requires login. Role-specific authorization can be added when Member/Admin workflows become more complete.

When a user saves a Google Sheets link, the backend normalizes and stores the spreadsheet ID. Settings responses also include a canonical Google Sheets URL for display, plus the spreadsheet title when the logged-in user's Google token can resolve it.

### Sync And Dashboard Routes

Sync routes live in `backend/app/api/sync.py`.

Current routes:

- `POST /sync/applications`

Dashboard routes live in `backend/app/api/dashboard.py`.

Current routes:

- `GET /dashboard`

The sync route:

1. Requires a logged-in user.
2. Reads saved app settings.
3. Requires a Google Sheet link or ID.
4. Loads the logged-in user's stored Google OAuth token.
5. Fetches rows from the first tab in the configured Google Sheet.
6. De-dupes applications by normalized applicant email, keeping the last row.
7. Stores the raw row JSON and normalized fields.
8. Applies deterministic hard filters.
9. Creates a `SyncRun` record.

Google OAuth tokens are stored in the local SQLite database in `google_credentials`. This is acceptable for the local MVP because the database is ignored by Git. A future hosted deployment should move this secret material to a more deliberate encrypted store or cloud secret/token storage design.

Google Forms response sheets may repeat column labels, such as `First name`, `Last name`, and `Age` for applicant, co-applicant, and children. During import, repeated headers are made unique with suffixes like `First name [2]` so earlier columns are not overwritten.

The dashboard route returns setup state and counts for submitted, eligible, filtered-out, and needs-review applications.

### User Creation

User creation/update logic lives in `backend/app/services/users.py`.

Users are matched by normalized email address. The first user created becomes `admin`. Later users become `member`.

This is intentionally simple for MVP. Later, we can add invitations and stricter access control.

### Deterministic Hard Filters

Hard-filter logic lives in:

```text
backend/app/domain/hard_filters.py
```

This module is intentionally pure domain logic. It takes normalized application-like data and returns a result. It does not know about FastAPI, SQLAlchemy, Google Sheets, or the UI.

Keeping this logic isolated makes it easy to test, read, and change.

Current tests cover:

- Eligible 2-bedroom household
- 3 adults filtered out
- 2-bedroom household without a child filtered out
- Unclear household marked `needs_review`
- Income outside configured range filtered out
- Unclear income marked `needs_review`
- Real estate ownership filtered out
- One dog plus one cat allowed
- Extra pets filtered out

## How Frontend And Backend Communicate

The frontend calls backend routes using `fetch`.

Example:

```ts
fetch(`${apiBaseUrl}/auth/me`, { credentials: "include" })
```

`apiBaseUrl` comes from:

```ts
import.meta.env.VITE_API_BASE_URL
```

and falls back to:

```text
http://127.0.0.1:8000
```

For local development, the frontend runs on port `5173` and the backend runs on port `8000`. Because these are different origins, the backend must explicitly allow the frontend origin through CORS.

The backend currently allows:

- `http://localhost:5173`
- `http://127.0.0.1:5173`

It also allows credentials so browser cookies work across the local frontend/backend boundary.

## OAuth Login Sequence

The current login flow looks like this:

1. Browser opens `http://127.0.0.1:5173`.
2. React calls `GET /auth/me`.
3. Backend returns `{ "user": null }`.
4. React shows the login panel.
5. User clicks "Sign in with Google".
6. Browser navigates to `GET /auth/google/login`.
7. Backend creates OAuth state in the signed session cookie and redirects to Google.
8. User approves Google scopes.
9. Google redirects to `GET /auth/google/callback`.
10. Backend validates OAuth state, reads Google identity, upserts the local user, and stores `user_id` in the session.
11. Backend redirects to the frontend.
12. React calls `GET /auth/me` again.
13. Backend returns the current user.
14. React shows the dashboard shell.

It is important that the local flow consistently uses `127.0.0.1` rather than mixing `localhost` and `127.0.0.1`. Browser cookies are host-specific, so mixing them can break OAuth state.

## Current Verification Commands

Backend:

```powershell
cd backend
uv run alembic upgrade head
uv run pytest
```

Frontend:

```powershell
cd frontend
npm run build
```

Current expected backend test result:

```text
13 passed
```

## Next Architecture Step

The current feature is Google Sheets sync. The next planned feature is improving the application table and candidate detail surfaces.

Upcoming UI work will add:

- Searchable/sortable application tables
- Filtered-out reason display
- Candidate detail pages
- Admin-only raw row debug view
