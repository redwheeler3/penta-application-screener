# Application Architecture

This document explains how the current local MVP is organized: the frontend, the backend, and how the two communicate.

The application is intentionally simple right now, to keep the code readable while the product shape is still changing quickly.

## Big Picture

The app has two local development processes:

1. A FastAPI backend running at `http://localhost:8000`
2. A Vite React frontend running at `http://localhost:5173`

The frontend is what the user sees in the browser. The backend owns authentication, database access, Google API integration, deterministic screening rules, and AI-assisted screening.

The two communicate over HTTP. When authentication is involved, they also share a signed session cookie issued by the backend.

## Frontend

The frontend lives in `frontend/`. The mental model:

```text
index.html
  loads src/main.tsx
    renders App.tsx
      stores browser state in React state variables
      calls the backend with fetch()
      redraws the UI when state changes
      uses styles.css for layout and visual design
```

React is the UI library: code changes state, and React redraws the matching UI. For example, `App.tsx` has state like:

```ts
const [user, setUser] = useState<CurrentUser | null>(null);
const [draft, setDraft] = useState<AppSettings>(defaultSettings);
const [dashboardCounts, setDashboardCounts] = useState<DashboardCounts>(...);
```

`user` is the current value, `setUser` changes it, and calling `setUser(...)` triggers a re-render of the relevant parts.

Vite is the frontend build tool and dev server: it serves the app locally, hot-reloads on file changes, and builds optimized static files for production.

Current important files:

- `frontend/package.json`: npm scripts and frontend dependencies.
- `frontend/index.html`: the single HTML page that loads the React app.
- `frontend/vite.config.ts`: Vite configuration.
- `frontend/src/main.tsx`: React entrypoint. It mounts the app into `index.html`.
- `frontend/src/App.tsx`: Current top-level application UI.
- `frontend/src/styles.css`: Current global styling and Penta-inspired palette.
- `frontend/src/vite-env.d.ts`: TypeScript support for Vite environment variables such as `import.meta.env`.
- `frontend/public/favicon.ico`: static favicon served by Vite at `/favicon.ico`.

### Frontend Runtime

During local development, start the frontend with:

```powershell
cd frontend
npm run dev
```

Then open `http://localhost:5173`.

The frontend is a single React screen (`App.tsx`) that has grown to cover the full review workflow. Its main responsibilities:

1. On load, call the backend's `/auth/me` endpoint.
2. If no user is logged in, show a Google sign-in panel.
3. If a user is logged in, fetch saved app settings, dashboard counts, and the applications list.
4. Show the dashboard: status/source tabs with faceted counts.
5. Let the user expand the admin settings panel (an "Edit settings" toggle, not a gear icon) and save changes.
6. Let the user sync applications from the configured Google Sheet.
7. Show a searchable, sortable, paginated applications table.
8. Open a candidate detail view: normalized fields, essays, filter reasons, AI screening flags, a private reviewer note, the raw row, and the AI narrative.
9. Run the AI screening pass with a cost-estimate confirmation and live streamed progress.
10. Let a committee member override an application's status (the human decision is sticky) or clear the override to hand the decision back to the machine.

### Vite Files

`frontend/package.json` defines the frontend project and its commands. Important scripts:

```json
"dev": "vite",
"build": "tsc -b && vite build",
"preview": "vite preview"
```

- `npm run dev` starts Vite's local development server.
- `npm run build` runs the TypeScript compiler, then has Vite create production assets.
- `npm run preview` serves the production build locally after `npm run build`.

Important dependencies:

- `react`: the UI library.
- `react-dom`: connects React to the browser DOM.
- `lucide-react`: icon library used for toolbar/button icons.
- `react-markdown`: renders the AI narrative (Markdown) in the candidate detail view.
- `vite` (devDependency): dev server and bundler.
- `typescript` (devDependency): typed JavaScript tooling.

`frontend/vite.config.ts` is small: it uses the React plugin and pins the dev server to `host: "localhost"` and `port: 5173`. The rest comes from Vite defaults.

`frontend/index.html` is the one real HTML document. Its key contents:

```html
<div id="root"></div>
<script type="module" src="/src/main.tsx"></script>
<link rel="icon" href="/favicon.ico" />
```

The `root` div is an empty mounting point that React fills in after `src/main.tsx` loads. Files in `frontend/public/` are served directly by Vite, which is why `frontend/public/favicon.ico` is available at `http://localhost:5173/favicon.ico`.

### React Entry Point

`frontend/src/main.tsx` starts React:

```tsx
ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

It finds the `root` element from `index.html`, creates a React root inside it, and renders the `App` component. `React.StrictMode` is a development helper that surfaces unsafe patterns; it may cause development-only double calls but does not change production behavior.

### App.tsx

`frontend/src/App.tsx` is currently the main UI component. It does a lot because the frontend is still young; keeping the current flow in one readable file is acceptable for now.

The top of the file defines TypeScript types that mirror the backend's JSON shapes — `CurrentUser`, `AppSettings`, `SettingsResponse`, `DashboardCounts`, `AppFacets`, `ApplicationSummary`, `ApplicationDetail`, `Essay`, `ScreeningFlag`, `ScreeningEstimateResponse`, plus the `AppStatus` / `StatusSource` / `SortKey` unions. These are compile-time help for the frontend; they do not create runtime database tables or backend models.

Next:

```ts
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
```

`import.meta.env` is Vite's way of exposing frontend environment variables. If `VITE_API_BASE_URL` is not set, the app defaults to the local backend at port `8000`.

Inside `App()`, the `useState` calls hold browser-side state (more than twenty now). The main groups:

- Auth: `user`, `isLoadingUser`.
- Settings: `draft` (the editable form values), `saved` (the persisted `SettingsResponse`, which carries the canonical Google Sheets URL and title), `isSettingsExpanded`, `isSavingSettings`, `settingsMessage`.
- Dashboard/sync: `dashboardCounts`, `syncMessage`, `syncError`, `isSyncing`.
- Applications list: `applications`, `appTotal`, `appPage`, `appPageSize`, `appFilter`, `appFacets`, `appSearch`, `appSort`, `selectedApp`. (Since M14 the list state is grouped in a `useApplications` hook, and toasts/ranking state in `useToasts`/`useRanking`; see `src/hooks/`.)
- Screening: `screeningEstimate`, `screeningRunning`, `screeningProgress`.

The first `useEffect` runs on mount and asks the backend whether the browser already has a valid login session:

```ts
fetch(`${apiBaseUrl}/auth/me`, { credentials: "include" })
```

The second `useEffect` runs when `user` changes: once a user is logged in, it fetches saved settings and dashboard counts.

The functions in `App.tsx` line up with user actions:

- `login()`: sends the browser to the backend's Google OAuth login route.
- `logout()`: calls the backend logout route and clears local user state.
- `saveSettings()`: sends the settings form to `PUT /settings`.
- `syncApplications()`: calls `POST /sync/applications`, then refreshes the dashboard and the applications list.
- `refreshDashboard()`: calls `GET /dashboard`.
- `applySettingsResponse()`: converts the backend settings response into the shape the UI displays.
- `fetchApplications()`: calls `GET /applications` with the current filter, search, sort, and page.
- `viewApplication()`: loads one application's detail via `GET /applications/{id}`.
- `toggleSort()`: changes the table sort column/direction.
- `requestScreeningEstimate()` / `runScreening()`: fetch the cost estimate, then stream the AI screening run.
- `overrideStatus()`: sets an application's status as a human decision via the applications API.
- `clearStatusOverride()`: removes a human override (DELETE), handing the decision back to the machine, which recomputes from current findings.

The bottom half of `App.tsx` returns JSX, using normal JavaScript conditions to decide what to show:

```tsx
{!user ? (
  <section className="login-panel">...</section>
) : (
  <>...</>
)}
```

If there is no user, show the login panel; otherwise show the authenticated dashboard.

### Frontend Authentication Flow

`App.tsx` checks the current user with:

```ts
fetch(`${apiBaseUrl}/auth/me`, { credentials: "include" })
```

`credentials: "include"` is essential — without it the browser would not send the backend session cookie on cross-origin requests from `5173` to `8000`.

When the user clicks "Sign in with Google", the browser is redirected to `http://localhost:8000/auth/google/login`. The backend then redirects to Google's OAuth consent flow. After Google finishes, it redirects back to the backend callback route; on success the backend redirects the browser back to the frontend.

Logout calls `POST http://localhost:8000/auth/logout` and then clears the local `user` state.

### Frontend Data Flow

The frontend does not directly read Google Sheets or SQLite. It only talks to the backend.

The normal dashboard load:

```text
Browser loads React
  App.tsx calls GET /auth/me
  If logged in:
    App.tsx calls GET /settings
    App.tsx calls GET /dashboard
    App.tsx calls GET /applications
  React stores the responses in state
  React renders the dashboard, tabs, and applications table from that state
```

The sync flow:

```text
User clicks Sync applications
  App.tsx calls POST /sync/applications
  Backend imports rows and applies hard filters
  App.tsx receives sync counts
  App.tsx calls GET /dashboard and GET /applications
  React redraws the counts and table
```

This separation matters: the frontend handles presentation and browser interactions; the backend handles trusted work — authentication, Google API calls, database writes, and screening logic.

### Frontend Styling

The current look borrows from `pentacoop.com`:

- White and very light gray page surfaces
- Green primary actions and success states
- Blue neutral/action accents (also used for the `ai` source badge)
- Orange for caution and the staleness/needs-review accents
- Red for ineligible status, flagged fields, and error toasts

The app should remain dashboard-like and operational, not a marketing landing page.

`frontend/src/styles.css` is plain CSS. It defines color variables at the top, used later via `var(...)`:

```css
:root {
  --penta-blue: #2563eb;
  --penta-green: #16a34a;
  --ink: #111827;
}
```

Main class families:

- `.app-shell`: centered page width and outer spacing.
- `.topnav` / `.topnav-inner`: app header row (note: not `.topbar`).
- `.brand-lockup` and `.brand-mark`: Penta title/icon grouping.
- `.toolbar`: right-side icon buttons.
- `.settings-panel`, `.settings-form`, `.settings-summary`, `.rules-section` / `.rules-grid`: admin settings layout and the per-rule toggle grid.
- `.app-controls`, `.filter-group`, `.app-tabs` / `.tab-button`, `.app-search`: dashboard tabs and table controls.
- `.app-table`, `.sort-header`, `.status-badge` / `.source-badge` / `.stale-badge`, `.pagination`: the applications table.
- `.app-detail`, `.app-detail-essays` / `.essay-block`, `.filter-reasons`, `.flags-panel` / `.flag` (+ `.flag-category`/`.flag-summary`/`.flag-evidence`), `.ai-narrative`, `.raw-row-section`, `.field-flagged`: the candidate detail view.
- The AI-run flow (estimate → confirm → progress) uses the shared workflow-strip classes in `WorkflowBar.tsx`, not a screening-specific family.
- `.toast` / `.toast-error` / `.toast-success`: transient messages.
- media query at the bottom: mobile layout adjustments.

(`.stats-grid` / `.stat-card` are still defined but no longer used — dashboard counts now surface as tab labels.)

When reading CSS in this project, start from the JSX class name in `App.tsx`, then search that class name in `styles.css`.

## Backend

The backend lives in `backend/`. The mental model:

```text
FastAPI app
  receives HTTP requests from the frontend
  uses dependencies to get the current user and database session
  calls service functions for app work
  uses SQLAlchemy models to read/write SQLite
  calls Google APIs when sync or OAuth needs them
  returns JSON back to the frontend
```

The backend is more complex than the frontend because it owns the trusted parts:

- login/session handling
- Google OAuth token handling
- database schema and persistence
- Google Sheets reads
- application import and normalization
- deterministic screening rules
- AI-assisted screening (screening flags + the Rank chain)
- API responses consumed by the React frontend

The backend is split into layers so each file has a clear job:

```text
app/api/       HTTP routes
app/core/      config and OAuth setup
app/db/        database models and sessions
app/domain/    pure business rules
app/schemas/   request/response data shapes
app/services/  reusable application operations
app/ai/        AI-assisted screening (provider, caching, screening + Rank passes)
```

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

### Backend File Map

`backend/pyproject.toml` defines the backend package, dependencies, and pytest configuration. Important dependencies:

- `fastapi[standard]`: web framework and local dev server support.
- `sqlalchemy`: ORM used to work with SQLite as Python objects.
- `alembic`: database migration tool.
- `authlib`: OAuth client used for Google login.
- `google-api-python-client`: Google Sheets API client.
- `google-auth`: Google credential/refresh support.
- `pydantic-settings`: environment-based settings.
- `pytest`: tests.

`backend/app/main.py` creates the FastAPI app (the backend equivalent of the frontend entry point).

`backend/app/api/*.py` files (and packages) define routes — HTTP endpoints such as `GET /dashboard` or `POST /sync/applications`. The modules are `applications.py` (list/detail/status-override), `auth.py`, `dashboard.py`, `health.py`, `screening.py` (the AI screening estimate/run endpoints), `ranking/` (the Rank-chain package: `run`/`current`/`shortlist`), `insights.py` (cost/metrics/last-runs), `evals/` (the eval cockpit package), `settings.py`, and `sync.py`, plus `dependencies.py` for shared FastAPI dependencies (e.g. `require_current_user`) and `problems.py` for the RFC 9457 error contract.

`backend/app/services/*.py` files contain reusable operations that routes call. For example, sync route code does not know every detail of importing application rows; it calls service functions.

`backend/app/domain/hard_filters.py` contains pure screening logic, intentionally separate from HTTP, SQLAlchemy, and Google APIs. `backend/app/domain/status.py` is the companion module that resolves an application's eligibility status from its findings (see the status model under "Database").

`backend/app/db/models.py` defines the database tables as Python classes. `backend/app/db/session.py` defines how code opens database sessions. `backend/alembic/versions/*.py` defines the migrations that give the database file the tables from `models.py`. `backend/tests/*.py` verifies important behavior.

### Backend Runtime

During local development, start the backend with:

```powershell
cd backend
uv run alembic upgrade head
uv run fastapi dev app/main.py --port 8000
```

The health check is `http://localhost:8000/health`.

`uv run ...` runs the command inside the backend project's managed Python environment, keeping dependencies local to this project instead of relying on globally installed packages.

### FastAPI App Setup

> For a one-line index of every HTTP endpoint, see [api.md](api.md). Because this is a FastAPI app, the live, always-current reference is also auto-generated at `http://localhost:8000/docs` (Swagger UI) and `http://localhost:8000/openapi.json`.

`backend/app/main.py` creates the FastAPI app. It currently installs:

- `SessionMiddleware`, which signs the browser session cookie and reads/writes it on each request.
- `CORSMiddleware`, which allows the local React frontend at port `5173` to call the backend at port `8000` with credentials.
- Route modules from `app.api.applications`, `app.api.auth`, `app.api.dashboard`, `app.api.evals`, `app.api.health`, `app.api.insights`, `app.api.screening`, `app.api.ranking`, `app.api.settings`, and `app.api.sync`.

The app uses an app factory, which makes testing easier because tests can create a fresh app instance:

```py
def create_app() -> FastAPI:
    ...
```

Routes are kept in separate router modules rather than registered in one central object; each router owns one slice of the API (for example, `app.api.sync` owns `/sync/applications`):

```py
app.include_router(applications_router)
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(evals_router)
app.include_router(health_router)
app.include_router(insights_router)
app.include_router(screening_router)
app.include_router(ranking_router)
app.include_router(settings_router)
app.include_router(sync_router)
```

FastAPI route functions are normal Python functions with a route decorator and dependency injection:

```py
@router.post("/applications")
def sync_applications(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    ...
```

The `Depends(...)` pieces tell FastAPI to run `require_current_user` and `get_db` before the route and pass the results as `user` and `db`. That is why route bodies focus on app behavior instead of manually opening database connections or checking cookies. Middleware wraps every request/response:

```text
Browser request
  Session/CORS middleware
    Route function
  Middleware finalizes response
Browser receives response
```

### Configuration

Configuration lives in `backend/app/core/config.py`. Settings are loaded from environment variables and local env files:

- `../.env`
- `../.env.local`
- `.env`
- `.env.local`

For this repo, the most important local file is `backend/.env.local` (ignored by Git).

The backend supports two ways to configure Google OAuth:

1. Direct environment variables: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
2. A downloaded Google OAuth JSON file: `GOOGLE_OAUTH_CLIENT_SECRETS_FILE`

For local MVP development, the JSON file approach is simpler because Google already provides that file.

The `Settings` class is a Pydantic settings model defining config values and defaults:

```py
class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/penta_screener.db"
    session_secret: str = "dev-only-change-me"
    frontend_url: str = "http://localhost:5173"
    ...
```

`get_settings()` is cached so the backend reads config once and reuses it:

```py
@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`backend/app/core/google_oauth.py` turns those settings into an Authlib OAuth client. It can read either direct env vars or the downloaded Google client-secret JSON; we use the JSON route locally because it keeps Google-provided values together.

### Database

The backend uses SQLite locally through SQLAlchemy. The default database URL is:

```text
sqlite:///./data/penta_screener.db
```

The SQLite database file is generated locally and ignored by Git.

Alembic owns schema migrations (in `backend/alembic/versions/`; M12 squashed the original chain into one baseline, and later migrations add the eval-runs table and the M14 `ranking_runs` split). The tables:

- `users`
- `google_credentials`
- `admin_settings`
- `applications`
- `application_notes` (a member's private per-application note)
- `application_ai_results` (cached AI analysis — see [ai-screening.md](ai-screening.md))
- `sync_runs`
- `ranking_runs` (a Rank's discovered dimensions + committee state; see the criteria-split note below)
- `ranking_run_audit` (1:1 with `ranking_runs`: the AI-legibility trail — discovery narrative + match/fan-out/decompose/consolidate audits)
- `dimension_aliases` (the sole merge-truth: a consolidated duplicate key → its canonical key)
- `run_cost_ledger` + `run_pass_cost` (per-run and per-pass cost/tokens/latency — M13 observability)
- `eval_runs` (persisted eval-cockpit runs)

During MVP iteration we do not preserve backward compatibility for local schema changes. If the local database shape changes, it is acceptable to delete the generated SQLite file and recreate it from migrations. Once real users or applicant data depend on the app, that tradeoff changes.

Three related concepts: SQLAlchemy models (Python classes describing tables), SQLAlchemy sessions (short-lived objects to query and save data), and Alembic migrations (scripts that create/change actual tables).

`backend/app/db/models.py` defines classes like:

```py
class Application(TimestampMixin, Base):
    __tablename__ = "applications"
    id: Mapped[int] = mapped_column(primary_key=True)
    primary_email: Mapped[str] = mapped_column(String(320), unique=True)
    raw_row: Mapped[dict[str, Any]] = mapped_column(JSON)
    raw_row_hash: Mapped[str] = mapped_column(String(64))
    normalized: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[ApplicationStatus] = mapped_column(...)
    status_source: Mapped[StatusSource] = mapped_column(...)
```

This declares an `applications` table with those columns. Some are regular relational columns (`id`, `primary_email`, `status`, `status_source`, `created_at`); some are JSON columns (`raw_row`, `normalized`, `hard_filter_reasons`). The hybrid is intentional: relational columns for things we query/filter/sort, JSON columns for flexible source payloads or debug/audit details.

**The status model.** Eligibility is not a single boolean. An application has a `status` (`ApplicationStatus`: `eligible` / `ineligible`) and a `status_source` (`StatusSource`: `untouched` / `rules` / `ai` / `human`) recording *who* last set it. The precedence is rules > AI > untouched, and a `human` source is sticky — machine re-runs never overwrite it. This is the model that lets the AI pass and the hard filters coexist; the logic lives in `app/domain/status.py`. (The older single `hard_filter_status` column was replaced by this two-column model.)

`backend/app/db/session.py` creates the database engine and session factory. A session is the unit of work for a request:

```text
Route starts
  get_db opens a Session
  route/service queries and writes through that Session
  get_db closes the Session
Route ends
```

`backend/alembic/versions/265a2a6c616c_create_initial_tables.py` is the first migration; later migrations in the same directory evolve the schema (status-model rework, AI results table, added columns). Running `uv run alembic upgrade head` applies migrations to the local SQLite database.

### Auth Routes

Auth routes live in `backend/app/api/auth.py`:

- `GET /auth/google/login` — starts the OAuth flow by redirecting the browser to Google.
- `GET /auth/google/callback` — handles Google's redirect back: exchanges the OAuth code for tokens, extracts user identity, creates or updates a local user record, stores `user_id` in the signed session cookie, and redirects back to the frontend.
- `GET /auth/me` — reads the signed session cookie. If it contains a valid active user ID, returns a serialized user; otherwise returns `{ "user": null }`.
- `POST /auth/logout` — clears the session cookie.

The login flow uses two separate pieces of identity: the Google identity (who Google says the user is) and the local user record (who the app knows the user as). On successful login the backend stores or updates a local `User` row; the first created user becomes `admin`, later users become `member`.

The backend also stores the Google OAuth token in `google_credentials`, which allows later Google Sheets reads without re-login. The browser never receives the raw Google token — only a signed session cookie carrying local session state (in practice, the local `user_id`). Later authenticated requests work like this:

```text
Browser calls GET /settings with session cookie
  Backend verifies signed cookie
  Backend loads user_id from session
  Backend queries local User row
  Route runs as that user
```

### Settings Routes

Settings routes live in `backend/app/api/settings.py`:

- `GET /settings`
- `PUT /settings`

Settings are stored in the `admin_settings` table as one JSON value under the key `app_settings`. Current settings:

- Google Sheet link or ID
- Unit size
- Move-in date
- Income minimum and maximum
- Income mismatch tolerance
- Household limits: max adults, minimum adult age
- Pet limits: max dogs, max cats, whether other/exotic pets are allowed
- `disabled_rules`: which deterministic hard-filter rules are turned off
- A nested `ai` block (`AISettings`): region, one model per AI pass (`screening_model`, `dimension_scoring_model`, `discovery_model`, `decompose_model`, `match_model`, `consolidate_model`), the consolidation correlation threshold, spending cap (default `$2.00`), and screening concurrency (`max_workers`) — see [ai-screening.md](ai-screening.md). Of these, only the spending cap is editable in the settings form; the rest are config-only but still round-tripped on save.

The defaults match the current planned 2-bedroom opening:

- Unit size: `2br`
- Move-in date: `2026-09-01`
- Income range: `$70,000` to `$150,000`

The settings API currently requires login. Role-specific authorization can be added when Member/Admin workflows become more complete.

When a user saves a Google Sheets link, the backend normalizes and stores the spreadsheet ID. Settings responses also include a canonical Google Sheets URL for display, plus the spreadsheet title when the logged-in user's Google token can resolve it.

Three files are involved:

- `backend/app/api/settings.py`: HTTP routes.
- `backend/app/schemas/settings.py`: request/response shape and validation.
- `backend/app/services/settings.py`: database read/write helpers.

`AppSettings` is a Pydantic model that validates settings coming from the frontend:

```py
class AppSettings(BaseModel):
    google_sheet_id: str = Field(default="", max_length=2000)
    income_min: int = Field(default=70_000, ge=0)
    income_max: int = Field(default=150_000, ge=0)
    min_adult_age: int = Field(default=18, ge=1, le=100)
    max_child_age: int = Field(default=17, ge=0, le=100)
    min_children: int = Field(default=1, ge=0, le=20)
    max_children: int = Field(default=4, ge=0, le=20)
    # ...plus pet limits, disabled_rules, and a nested ai: AISettings
```

The full model (see `app/schemas/settings.py`) includes the nested `AISettings` sub-model and normalizes a pasted Google Sheets URL into a sheet ID before saving, so the frontend can show a friendly URL while the backend stores a stable ID. Note there is no `unit_size` or `move_in_date` (those were display-only and removed), and no income-mismatch tolerance — the arithmetic check requires exact equality. Settings are stored as one JSON blob in `admin_settings`, which is simple for MVP because there is only one settings object.

### Sync And Dashboard Routes

Sync routes live in `backend/app/api/sync.py`:

- `POST /sync/applications`

Dashboard routes live in `backend/app/api/dashboard.py`:

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

Google OAuth tokens are stored in the local SQLite database in `google_credentials`. This is acceptable for the local MVP because the database is ignored by Git. A future hosted deployment should move this secret material to an encrypted store or cloud secret/token storage design.

The dashboard route returns `settingsComplete` (whether a Google Sheet is configured), a `submitted` total, and counts grouped by `status` (eligible / ineligible) and `status_source` (untouched / rules / ai / human). "Needs review" is the client's label for the `source = ai` group; "filtered out" is `source = rules`.

The sync flow crosses several layers:

```text
POST /sync/applications
  app/api/sync.py
    checks current user
    loads app settings
    loads stored Google token
    calls fetch_sheet_rows(...)
      app/services/google_sheets.py
        refreshes Google credentials if needed
        reads spreadsheet metadata
        reads values from the first sheet tab
        makes repeated headers unique
        returns list[dict] rows
    calls import_applications_from_rows(...)
      app/services/application_import.py
        de-dupes by email
        normalizes each row
        calls evaluate_hard_filters(...)
          app/domain/hard_filters.py
        writes Application rows
        writes SyncRun record
  returns sync counts as JSON
```

`backend/app/services/google_sheets.py` is concerned only with Google Sheets access and turning sheet values into row dictionaries. One important detail: Google Forms response sheets may repeat column labels, and a dictionary cannot have duplicate keys, so repeated headers are made unique (`First name`, `First name [2]`, `First name [3]`) to prevent later columns from overwriting earlier ones.

`backend/app/services/application_import.py` is where source rows become app data. It handles:

- primary email normalization
- duplicate email handling
- row hashing
- applicant/co-applicant name extraction
- child count extraction
- income parsing
- real-estate parsing
- pet parsing
- storing raw and normalized values

The importer preserves the raw Google Sheets row as JSON — useful for debugging, auditability, schema drift, and future candidate detail screens.

`SyncRun` records what happened during sync: `row_count`, `duplicate_count`, `imported_count`, `updated_count`, `unchanged_count`, `eligible_count`, `filtered_out_count`, and a `settings_fingerprint` (hash of the import-relevant settings at sync time). The dashboard compares the latest sync's fingerprint to the live settings to flag the Import step amber when settings changed since the last import (`workflow.importCurrent`).

`backend/app/api/dashboard.py` queries application counts from SQLite and returns them (see the response shape above). Richer per-application data is served by the separate `app/api/applications.py` list/detail endpoints.

### Application Routes

Application routes live in `backend/app/api/applications.py`:

- `GET /applications` — a searchable, filterable, sortable, paginated list. Filters by `status` and `status_source`, and returns faceted counts so the UI can show how many applications fall in each tab.
- `GET /applications/{id}` — one application's detail: normalized fields, essays, filter reasons, AI screening flags, the raw source row, and the AI narrative.
- `PATCH /applications/{id}/status` — a human status override. Sets `status_source = human`, which machine re-runs then leave untouched.
- `DELETE /applications/{id}/status` — removes a human override, handing the decision back to the machine. Recomputes status from the current findings and clears human ownership; idempotent if no override is set.

All application routes are open to any logged-in committee member. Roles (`admin` / `member`) exist in the data model but do not currently gate any route — members are trusted screeners.

The AI screening endpoints (`GET /screening/run/estimate` and `POST /screening/run`) live in `app/api/screening.py` and are documented in [ai-screening.md](ai-screening.md).

### User Creation

User creation/update logic lives in `backend/app/services/users.py`. Users are matched by normalized email address; the first user created becomes `admin`, later users become `member`. This is intentionally simple for MVP — invitations and stricter access control can come later.

### Deterministic Hard Filters

Hard-filter logic lives in `backend/app/domain/hard_filters.py`. This module is intentionally pure domain logic: it takes normalized application-like data and returns a result, without knowing about FastAPI, SQLAlchemy, Google Sheets, or the UI. Keeping it isolated makes it easy to test, read, and change, and it is a good place to read the business rules without web-framework noise.

Current tests cover all deterministic screening rules including child age limits, child age exceeding a parent, applicant and co-applicant age, income range, the household-income arithmetic mismatch, real estate ownership, child count mismatch, negative values, future employment dates, and co-applicant completeness.

### AI Screening

On top of the deterministic hard filters, the app runs an **AI screening pass**. It reviews each application for data-integrity concerns — placeholder-looking names, non-responsive essays, pet descriptions that conflict with the co-op policy, obviously fake contact details — and surfaces them as informational notices (flags) for a human screener.

Two things keep this bounded:

- **Flags never decide eligibility.** The hard filters decide; AI only annotates. A flagged application moves into a "needs review" bucket, not a rejection.
- **Machines never overwrite humans.** A human-set status is sticky across re-runs.

The AI code lives in `backend/app/ai/` and is built around a provider boundary: the app depends on an `AIProvider` interface, with the real implementation backed by the Strands SDK on Amazon Bedrock (Claude Haiku 4.5) and a `MockProvider` used in tests so they run with no AWS access. Results are cached by a content + model + prompt-version hash, and every run is cost-estimated and capped before it starts.

The pass runs applications **concurrently** through a thread pool (the model call is a slow, blocking network round-trip), streaming progress back to the browser as NDJSON. The design rule: only the model call runs in worker threads; all database access stays on the request thread, so the SQLAlchemy session is never shared.

This section is a summary. The full pipeline — provider boundary, structured output, caching, cost cap, the flags-to-status model, and the concurrency design — is documented in **[ai-screening.md](ai-screening.md)**.

The main hard-filter function is:

```py
def evaluate_hard_filters(application: dict[str, Any], rules: RulesConfig = RulesConfig()) -> FilterResult:
    ...
```

It takes already-normalized application data, not raw Google Sheets rows. That separation matters:

```text
Raw Google row
  application_import.py normalizes it
Normalized application dict
  hard_filters.py evaluates it
FilterResult
  application_import.py stores status/reasons
```

The hard-filter module returns structured reasons, so the UI can show a readable message while keeping machine-readable `code` and `details`:

```py
FilterReason(
    code="income_below_range",
    message=f"Household gross income (${income:,.0f}) is below ${rules.min_income:,}.",
    details={"household_income": income, "min_income": rules.min_income},
)
```

### Schemas

Schemas live in `backend/app/schemas/`. Here, "schema" means Pydantic request/response models, not database tables (those live in `backend/app/db/models.py`). FastAPI uses these models to validate and serialize data, and they make route behavior easier to read because the expected JSON shape is explicit. For example, `SettingsResponse` describes JSON returned to the frontend:

```py
class SettingsResponse(BaseModel):
    settings: AppSettings
    google_sheet_url: str = ""
    google_sheet_title: str | None = None
```

`backend/app/schemas/settings.py` also defines `AppSettings` (the full admin settings model) and its nested `AISettings` sub-model. The AI structured-output schemas (`ScreeningReport` and friends) live separately in `app/ai/schemas.py` — see [ai-screening.md](ai-screening.md).

### Services

Services live in `backend/app/services/`. Service functions are reusable app operations that do not themselves define HTTP routes. Current service files:

- `users.py`: create/update users from Google identity.
- `settings.py`: load/save the app settings JSON record.
- `google_credentials.py`: store/retrieve Google OAuth tokens.
- `google_sheets.py`: read spreadsheet metadata and rows.
- `application_import.py`: turn sheet rows into `Application` and `SyncRun` records.
- `ranking_run.py`: the Rank run's persistence + carry-forward — `create_run`, `dimension_weights` (derived from tiers), `adopt_matched_keys`, `carry_forward_layout`, `apply_consolidation`, the `*_audit_view` accessors, `rank_inputs_fingerprint`.
- `ranking_view.py`: assemble a candidate's per-dimension score contributions for the detail page.
- `cost_report.py` / `metrics.py`: the M13 observability surfaces (per-run/per-pass cost + operational trends) over the `run_cost_ledger` / `run_pass_cost` tables.
- `backup.py`: local `.db` snapshot/restore (a post-Rank snapshot is taken automatically).

This keeps route files short: a route says "what HTTP endpoint is this?" and "what service work should happen?"; the service does the details.

### Tests

Backend tests live in `backend/tests/`. They are deliberately focused:

- `test_hard_filters.py`: business-rule behavior.
- `test_application_import.py`: row normalization, duplicate handling, importer behavior.
- `test_settings.py`: settings defaults, saving, URL normalization.
- `test_google_oauth_config.py`: OAuth config loading.
- `test_auth.py`: auth endpoint expectations.
- `test_dashboard.py`: dashboard access expectations.
- `test_health.py`: health endpoint.
- `test_status_model.py`: the status / status_source transition rules (machine vs. human, staleness).
- `test_sync_errors.py`: sync failure handling.
- `test_ai_analysis.py`: AI caching, cost estimate, and spending-cap behavior.
- `test_screening.py` / `test_screening_api.py`: the AI screening pass, including its concurrency and failure-isolation contracts.
- `test_ranking.py` / `test_ranking_api.py`: the ranking math and the Rank-chain streaming endpoints (criteria → score → consolidate).
- `test_dimension_scoring.py`, and the eval suite (`test_evals*.py`, `test_*_eval.py`): per-pass scoring, invariants, and the eval-cockpit endpoints.

The most important tests right now are the hard-filter and application-import tests, because those protect the screening behavior. Some tests use an in-memory SQLite database so they run quickly without touching the local development database file:

```py
engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
return Session(engine)
```

## How Frontend And Backend Communicate

The frontend calls backend routes using `fetch`:

```ts
fetch(`${apiBaseUrl}/auth/me`, { credentials: "include" })
```

`apiBaseUrl` comes from `import.meta.env.VITE_API_BASE_URL` and falls back to `http://localhost:8000`.

For local development, the frontend runs on port `5173` and the backend on port `8000`. Because these are different origins, the backend must explicitly allow the frontend origin through CORS. It currently allows:

- `http://localhost:5173`
- `http://127.0.0.1:5173`

It also allows credentials so browser cookies work across the local frontend/backend boundary.

## OAuth Login Sequence

The current login flow:

1. Browser opens `http://localhost:5173`.
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

The local flow must consistently use `localhost` rather than mixing `localhost` and `127.0.0.1`. Browser cookies are host-specific, so mixing them can break OAuth state.

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

All backend tests should pass (`uv run pytest` reports the current count).

## Next Architecture Step

The current feature set includes Google Sheets sync, deterministic hard filters, application tables, searchable/filterable views, candidate detail pages, filtered-out reason display, raw row inspection, the AI screening pass, and the Rank chain that discovers criteria across the pool and scores candidates against them, feeding a deterministic stack-ranked shortlist (see [ai-screening.md](ai-screening.md)).

The next planned product areas build on the AI foundation, reusing the provider boundary, caching, and cost-cap machinery already in `app/ai/`.
