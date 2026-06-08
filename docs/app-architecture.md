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

The useful mental model is:

```text
index.html
  loads src/main.tsx
    renders App.tsx
      stores browser state in React state variables
      calls the backend with fetch()
      redraws the UI when state changes
      uses styles.css for layout and visual design
```

React is the UI library. It turns state into screen output. Instead of manually finding DOM elements and changing them, React code changes state and React redraws the matching UI.

For example, `App.tsx` has state like:

```ts
const [user, setUser] = useState<CurrentUser | null>(null);
const [settings, setSettings] = useState<AppSettings>(defaultSettings);
const [dashboardCounts, setDashboardCounts] = useState<DashboardCounts>(...);
```

That pattern means:

- `user` is the current value.
- `setUser` is the function that changes it.
- When `setUser(...)` runs, React re-renders the relevant parts of the app.

Vite is the frontend build tool and development server. It serves the React app locally, updates the browser quickly when files change, and builds optimized static files for production.

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
npm run dev -- --host 127.0.0.1
```

Then open:

```text
http://127.0.0.1:5173
```

The frontend is currently a single React screen. It does six main things:

1. On load, call the backend's `/auth/me` endpoint.
2. If no user is logged in, show a Google sign-in panel.
3. If a user is logged in, fetch saved app settings and dashboard counts.
4. If a user is logged in, show the dashboard shell.
5. Let the user open the settings panel from the gear icon.
6. Let the user sync applications from the configured Google Sheet.

### Vite Files

`frontend/package.json` defines the frontend project and its commands.

Important scripts:

```json
"dev": "vite",
"build": "tsc -b && vite build",
"preview": "vite preview"
```

- `npm run dev` starts Vite's local development server.
- `npm run build` first runs the TypeScript compiler, then asks Vite to create production assets.
- `npm run preview` serves the production build locally after `npm run build`.

Important dependencies:

- `react`: the UI library.
- `react-dom`: connects React to the browser DOM.
- `lucide-react`: icon library used for toolbar/button icons.
- `vite`: dev server and bundler.
- `typescript`: typed JavaScript tooling.

`frontend/vite.config.ts` is intentionally small. It tells Vite to use the React plugin. Most of the behavior comes from Vite defaults.

`frontend/index.html` is the one real HTML document. It has:

```html
<div id="root"></div>
<script type="module" src="/src/main.tsx"></script>
```

The `root` div is an empty mounting point. React fills it in after `src/main.tsx` loads.

The favicon is linked here too:

```html
<link rel="icon" href="/favicon.ico" />
```

Files in `frontend/public/` are served directly by Vite. That is why `frontend/public/favicon.ico` is available at:

```text
http://127.0.0.1:5173/favicon.ico
```

### React Entry Point

`frontend/src/main.tsx` starts React:

```tsx
ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

Read this as:

1. Find the `root` element from `index.html`.
2. Create a React root inside it.
3. Render the `App` component.

`React.StrictMode` is a development helper. It makes React a little more aggressive about surfacing unsafe patterns. It may cause some development-only double calls in certain situations, but it does not change the production app behavior.

### App.tsx

`frontend/src/App.tsx` is currently the main UI component. It is doing a lot because the frontend is still young. This is acceptable for now because reading one file top-to-bottom makes the current flow easier to understand.

The top of the file defines TypeScript types:

```ts
type CurrentUser = { ... };
type AppSettings = { ... };
type SettingsResponse = { ... };
type DashboardCounts = { ... };
```

These types describe the data shape the frontend expects from the backend. They do not create runtime database tables or backend models; they are compile-time help for the frontend.

The next important line is:

```ts
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
```

`import.meta.env` is Vite's way of exposing frontend environment variables. If `VITE_API_BASE_URL` is not set, the app defaults to the local backend at port `8000`.

Inside `App()`, the `useState` calls hold browser-side state:

- `user`: who is logged in, or `null`.
- `settings`: the current admin settings form values.
- `googleSheetUrl`: the canonical clickable Google Sheets URL returned by the backend.
- `googleSheetTitle`: the resolved spreadsheet title returned by the backend.
- `isSettingsOpen`: whether the settings panel is visible.
- `dashboardCounts`: submitted/eligible/filtered-out/needs-review counts.
- `syncMessage`: the latest sync success/failure message.
- `isSyncing`: whether the sync button should be disabled while sync is running.

The first `useEffect` runs when the component first loads:

```ts
fetch(`${apiBaseUrl}/auth/me`, { credentials: "include" })
```

It asks the backend whether the browser already has a valid login session.

The second `useEffect` runs when `user` changes. Once a user is logged in, it fetches saved settings and dashboard counts.

The functions in `App.tsx` line up with user actions:

- `login()`: sends the browser to the backend's Google OAuth login route.
- `logout()`: calls the backend logout route and clears local user state.
- `saveSettings()`: sends the settings form to `PUT /settings`.
- `syncApplications()`: calls `POST /sync/applications` and refreshes dashboard counts.
- `refreshDashboard()`: calls `GET /dashboard`.
- `applySettingsResponse()`: converts the backend settings response into the shape the UI displays.

The bottom half of `App.tsx` returns JSX. JSX looks like HTML, but it is really TypeScript syntax that React compiles into UI instructions. The JSX uses normal JavaScript conditions to decide what to show:

```tsx
{!user ? (
  <section className="login-panel">...</section>
) : (
  <>...</>
)}
```

That says: if there is no user, show the login panel; otherwise show the authenticated dashboard.

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

### Frontend Data Flow

The frontend does not directly read Google Sheets or SQLite. It only talks to the backend.

The normal dashboard load is:

```text
Browser loads React
  App.tsx calls GET /auth/me
  If logged in:
    App.tsx calls GET /settings
    App.tsx calls GET /dashboard
  React stores the responses in state
  React renders the dashboard from that state
```

The sync flow is:

```text
User clicks Sync applications
  App.tsx calls POST /sync/applications
  Backend imports rows and applies hard filters
  App.tsx receives sync counts
  App.tsx calls GET /dashboard
  React redraws dashboard cards
```

This separation matters. The frontend is responsible for presentation and browser interactions. The backend is responsible for trusted work: authentication, Google API calls, database writes, and screening logic.

### Frontend Styling

The current look borrows from `pentacoop.com`:

- White and very light gray page surfaces
- Green primary actions and success states
- Blue neutral/action accents
- Orange used sparingly for caution/current-opening accents
- Red reserved for future filtered-out or failure states

The app should remain dashboard-like and operational. It should not become a marketing landing page.

`frontend/src/styles.css` is plain CSS. It defines color variables at the top:

```css
:root {
  --penta-blue: #2563eb;
  --penta-green: #16a34a;
  --ink: #111827;
}
```

Those variables keep the palette consistent. Later CSS rules use them with `var(...)`.

The file also defines the current layout pieces:

- `.app-shell`: centered page width and outer spacing.
- `.topbar`: app header row.
- `.brand-lockup` and `.brand-mark`: Penta title/icon grouping.
- `.toolbar`: right-side icon buttons.
- `.settings-panel` and `.settings-form`: admin settings layout.
- `.stats-grid` and `.stat-card`: dashboard count cards.
- `.panel`: current applications placeholder area.
- media query at the bottom: mobile layout adjustments.

When reading CSS in this project, start from the JSX class name in `App.tsx`, then search that class name in `styles.css`.

## Backend

The backend lives in `backend/`.

The useful mental model is:

```text
FastAPI app
  receives HTTP requests from the frontend
  uses dependencies to get the current user and database session
  calls service functions for app work
  uses SQLAlchemy models to read/write SQLite
  calls Google APIs when sync or OAuth needs them
  returns JSON back to the frontend
```

The backend is more complex than the frontend because it owns the trusted parts of the app:

- login/session handling
- Google OAuth token handling
- database schema and persistence
- Google Sheets reads
- application import and normalization
- deterministic screening rules
- API responses consumed by the React frontend

The backend is deliberately split into layers. The layers are not fancy; they are mostly there so each file has a clear job.

```text
app/api/       HTTP routes
app/core/      config and OAuth setup
app/db/        database models and sessions
app/domain/    pure business rules
app/schemas/   request/response data shapes
app/services/  reusable application operations
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

`backend/pyproject.toml` defines the backend package, dependencies, and pytest configuration.

Important dependencies:

- `fastapi[standard]`: web framework and local dev server support.
- `sqlalchemy`: ORM used to work with SQLite as Python objects.
- `alembic`: database migration tool.
- `authlib`: OAuth client used for Google login.
- `google-api-python-client`: Google Sheets/Drive/Docs API client.
- `google-auth`: Google credential/refresh support.
- `pydantic-settings`: environment-based settings.
- `pytest`: tests.

`backend/app/main.py` creates the FastAPI app. This is the backend equivalent of the frontend entry point.

`backend/app/api/*.py` files define routes. A route is an HTTP endpoint such as `GET /dashboard` or `POST /sync/applications`.

`backend/app/services/*.py` files contain reusable operations that routes call. For example, sync route code does not directly know every detail of importing application rows; it calls service functions.

`backend/app/domain/hard_filters.py` contains pure screening logic. This is intentionally separate from HTTP, SQLAlchemy, and Google APIs.

`backend/app/db/models.py` defines the database tables as Python classes.

`backend/app/db/session.py` defines how code opens database sessions.

`backend/alembic/versions/*.py` defines database migrations. Migrations are how the database file gets the tables from `models.py`.

`backend/tests/*.py` verifies important behavior.

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

`uv run ...` means "run this command inside the backend project's managed Python environment." That keeps dependencies local to this project instead of relying on globally installed Python packages.

### FastAPI App Setup

`backend/app/main.py` creates the FastAPI app.

It currently installs:

- `SessionMiddleware`, which signs the browser session cookie.
- `CORSMiddleware`, which allows the local React frontend to call the backend with credentials.
- Route modules from `app.api.auth`, `app.api.dashboard`, `app.api.health`, `app.api.settings`, and `app.api.sync`.

The app uses an app factory:

```py
def create_app() -> FastAPI:
    ...
```

This makes testing easier because tests can create a fresh app instance.

In older web frameworks, you might remember one large app object with routes registered directly in a central file. FastAPI can work that way too, but this project keeps routes in separate router modules:

```py
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(health_router)
app.include_router(settings_router)
app.include_router(sync_router)
```

Each router owns one slice of the API. For example, `app.api.sync` owns `/sync/applications`.

FastAPI route functions look like normal Python functions:

```py
@router.post("/applications")
def sync_applications(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    ...
```

The decorator says which HTTP route calls the function. The `Depends(...)` pieces are FastAPI dependency injection. They tell FastAPI:

- Before calling this route, run `require_current_user` and give me the result as `user`.
- Before calling this route, run `get_db` and give me the result as `db`.

That is why route bodies can focus on app behavior instead of manually opening database connections or checking cookies every time.

Middleware is request/response plumbing that wraps routes:

- `SessionMiddleware` reads and writes the signed session cookie.
- `CORSMiddleware` allows the frontend dev server at port `5173` to call the backend at port `8000`.

The app has both:

```text
Browser request
  Session/CORS middleware
    Route function
  Middleware finalizes response
Browser receives response
```

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

The `Settings` class is a Pydantic settings model. It defines config values and defaults:

```py
class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/penta_screener.db"
    session_secret: str = "dev-only-change-me"
    frontend_url: str = "http://127.0.0.1:5173"
    ...
```

The `get_settings()` function is cached:

```py
@lru_cache
def get_settings() -> Settings:
    return Settings()
```

That means the backend reads environment/config once and reuses it. This is a common pattern in FastAPI apps.

`backend/app/core/google_oauth.py` turns those settings into an Authlib OAuth client. It can read either direct env vars or the downloaded Google client-secret JSON. We use the JSON route locally because it is less fiddly and keeps Google-provided values together.

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

There are three related database concepts here:

- SQLAlchemy models: Python classes that describe tables.
- SQLAlchemy sessions: short-lived objects used to query and save data.
- Alembic migrations: scripts that create/change actual database tables.

`backend/app/db/models.py` defines classes like:

```py
class Application(TimestampMixin, Base):
    __tablename__ = "applications"
    id: Mapped[int] = mapped_column(primary_key=True)
    primary_email: Mapped[str] = mapped_column(String(320), unique=True)
    raw_row: Mapped[dict[str, Any]] = mapped_column(JSON)
    normalized: Mapped[dict[str, Any]] = mapped_column(JSON)
```

Read that as "there is an `applications` table with these columns."

Some columns are regular relational columns, such as:

- `id`
- `primary_email`
- `hard_filter_status`
- `created_at`

Some columns are JSON columns, such as:

- `raw_row`
- `normalized`
- `hard_filter_reasons`

This hybrid is intentional. We use relational columns for things we need to query/filter/sort, and JSON columns for flexible source payloads or debug/audit details.

`backend/app/db/session.py` creates the database engine and session factory. A database session is the unit of work for a request:

```text
Route starts
  get_db opens a Session
  route/service queries and writes through that Session
  get_db closes the Session
Route ends
```

`backend/alembic/versions/265a2a6c616c_create_initial_tables.py` is the current migration that creates the initial tables. Running:

```powershell
uv run alembic upgrade head
```

applies migrations to the local SQLite database.

For this MVP, when we make schema changes, we are allowed to keep the schema clean rather than preserving compatibility with old local DB files. Once real users or real applicant data are depending on the app, that tradeoff changes.

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

The login flow uses two separate pieces of identity:

- Google identity: who Google says the user is.
- Local user record: who the app knows the user as.

On successful login, the backend stores or updates a local `User` row. The first created user becomes `admin`; later users become `member`.

The backend also stores the Google OAuth token in `google_credentials`. That token is what allows later Google Sheets reads without asking the user to log in again immediately.

The browser does not receive the raw Google token. Instead, the browser gets a signed session cookie containing local session state. In practice, the important value is the local `user_id`.

That means later authenticated requests work like this:

```text
Browser calls GET /settings with session cookie
  Backend verifies signed cookie
  Backend loads user_id from session
  Backend queries local User row
  Route runs as that user
```

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

There are three files involved:

- `backend/app/api/settings.py`: HTTP routes.
- `backend/app/schemas/settings.py`: request/response shape and validation.
- `backend/app/services/settings.py`: database read/write helpers.

`AppSettings` is a Pydantic model. It validates settings coming from the frontend:

```py
class AppSettings(BaseModel):
    google_sheet_id: str = Field(default="", max_length=2000)
    unit_size: str = Field(default="2br", pattern="^(1br|2br|3br)$")
    move_in_date: date = date(2026, 9, 1)
    income_min: int = Field(default=70_000, ge=0)
    income_max: int = Field(default=150_000, ge=0)
```

It also normalizes a pasted Google Sheets URL into a sheet ID before saving. The frontend can show a friendly URL, while the backend stores a stable ID.

Settings are stored as one JSON blob in the `admin_settings` table. That is simple for MVP because we have only one settings object, not many rows of settings.

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

The dashboard route returns setup state and counts for submitted, eligible, filtered-out, and needs-review applications.

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

`backend/app/services/google_sheets.py` is concerned only with Google Sheets access and turning sheet values into row dictionaries.

One important detail: Google Forms response sheets may repeat column labels. A plain dictionary cannot have duplicate keys, so repeated headers are made unique:

```text
First name
First name [2]
First name [3]
```

This prevents later columns from overwriting earlier columns.

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

The importer preserves the raw Google Sheets row as JSON. That is useful for debugging, auditability, schema drift, and future candidate detail screens.

`SyncRun` is the record of what happened during sync. It stores counts like row count, imported count, updated count, eligible count, filtered-out count, and needs-review count.

The dashboard is intentionally lightweight right now. `backend/app/api/dashboard.py` queries application counts from SQLite and returns them to the frontend. Later, this route can grow or be replaced by richer application-list endpoints.

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

This file is a good place to read if you want to understand the business rules without web-framework noise.

The main function is:

```py
def evaluate_hard_filters(application: dict[str, Any], rules: UnitRules = UnitRules()) -> FilterResult:
    ...
```

It takes already-normalized application data, not raw Google Sheets rows.

That separation matters:

```text
Raw Google row
  application_import.py normalizes it
Normalized application dict
  hard_filters.py evaluates it
FilterResult
  application_import.py stores status/reasons
```

The hard-filter module returns structured reasons:

```py
FilterReason(
    code="income_below_range",
    message="Household gross income is below $70,000.",
    details={"household_income": income, "min_income": rules.min_income},
)
```

That shape is useful because the UI can show a readable message while still keeping machine-readable `code` and `details`.

### Schemas

Schemas live in `backend/app/schemas/`.

In this codebase, "schema" means Pydantic request/response models, not database tables. Database tables live in `backend/app/db/models.py`.

For example, `SettingsResponse` describes JSON returned to the frontend:

```py
class SettingsResponse(BaseModel):
    settings: AppSettings
    google_sheet_url: str = ""
    google_sheet_title: str | None = None
```

FastAPI uses these models to validate and serialize data. They also make route behavior easier to read because the expected JSON shape is explicit.

### Services

Services live in `backend/app/services/`.

Think of service functions as reusable app operations that do not themselves define HTTP routes.

Current service files:

- `users.py`: create/update users from Google identity.
- `settings.py`: load/save the app settings JSON record.
- `google_credentials.py`: store/retrieve Google OAuth tokens.
- `google_sheets.py`: read spreadsheet metadata and rows.
- `application_import.py`: turn sheet rows into `Application` and `SyncRun` records.

This keeps route files short. A route says "what HTTP endpoint is this?" and "what service work should happen?" The service does the details.

### Tests

Backend tests live in `backend/tests/`.

The tests are deliberately focused:

- `test_hard_filters.py`: business-rule behavior.
- `test_application_import.py`: row normalization, duplicate handling, importer behavior.
- `test_settings.py`: settings defaults, saving, URL normalization.
- `test_google_oauth_config.py`: OAuth config loading.
- `test_auth.py`: auth endpoint expectations.
- `test_dashboard.py`: dashboard access expectations.
- `test_health.py`: health endpoint.

The most important tests right now are the hard-filter and application-import tests, because those protect the screening behavior.

Some tests use an in-memory SQLite database:

```py
engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
return Session(engine)
```

That lets tests run quickly without touching the local development database file.

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
25 passed
```

## Next Architecture Step

The current feature is Google Sheets sync. The next planned feature is improving the application table and candidate detail surfaces.

Upcoming UI work will add:

- Searchable/sortable application tables
- Filtered-out reason display
- Candidate detail pages
- Admin-only raw row debug view
