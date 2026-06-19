# Penta Application Screener

Local-first application screener for Penta Housing Co-op membership applications.

The app imports Google Sheets application responses, applies deterministic eligibility rules, runs cached AI quality checks over eligible applications, and gives reviewers a searchable application table with candidate detail pages, audit-friendly flags, and human override controls.

This is both a practical MVP for a co-op screening workflow and a portfolio/learning project around AI product management, human-in-the-loop review, cost-aware AI use, and readable full-stack application design.

## What It Does Now

- Google OAuth login with signed server-side sessions.
- Read-only Google Sheets sync into a local SQLite database.
- Configurable application settings for unit size, move-in date, income range, household rules, pets, and disabled deterministic rules.
- Deterministic hard filters for clear eligibility issues.
- Application dashboard, searchable/sortable table, facets, pagination, and candidate detail pages.
- AI quality checks for suspicious or low-quality submissions, backed by a provider-agnostic interface with Amazon Bedrock/Strands as the current concrete provider and a deterministic mock provider for tests.
- Shared AI result caching by application content, model, and prompt version, so repeated runs reuse stored results.
- Admin-only raw source row and raw AI output debug panels.
- Human status overrides with stale-finding indicators when machine findings change later.

The next planned milestone is richer per-candidate AI essay analysis and committee-ready summary/report generation.

Current planning lives in [SPEC.md](SPEC.md). Developer architecture notes live in [docs/app-architecture.md](docs/app-architecture.md). Shared agent guidance lives in [.clinerules](.clinerules), with [AGENTS.md](AGENTS.md) pointing agents there.

## Privacy And Test Data

Applicant data is sensitive. Do not commit real application exports, local SQLite databases, OAuth credentials, raw AI traces, generated reports with applicant data, or `.env` files.

The sample CSV in [test-data](test-data) is synthetic and intentionally realistic so import logic and AI quality checks can be exercised locally. See [test-data/README.md](test-data/README.md) for the directory policy.

## Tech Stack

- Backend: Python, FastAPI, SQLAlchemy, Alembic, SQLite
- Python tooling: `uv`, project-local virtual environment, `pytest`
- Frontend: Vite, React, TypeScript, npm
- Authentication: Google OAuth with signed server-side session cookies
- Google integration: read-only Google Sheets import/sync
- AI integration: provider-agnostic interface; Strands + Amazon Bedrock provider; mock provider for tests

## Setup

1. Install prerequisites:

   - [uv](https://docs.astral.sh/uv/)
   - Node.js 20+ with npm
   - PowerShell 7 on Windows if using `dev.ps1`

2. Install dependencies:

   ```sh
   cd backend && uv sync && cd ..
   cd frontend && npm install && cd ..
   ```

3. Configure Google OAuth.

   Place the downloaded OAuth client JSON from Google Cloud Console in `backend/secrets/`:

   ```sh
   mkdir -p backend/secrets
   # copy or move the downloaded client_secret_*.json file into backend/secrets/
   ```

   The backend auto-discovers any `client_secret_*.json` file in that directory. The directory is ignored by Git.

   See [docs/google-cloud-oauth-setup.md](docs/google-cloud-oauth-setup.md) for full Google Cloud and OAuth details.

4. Run database migrations:

   ```sh
   cd backend && uv run alembic upgrade head
   ```

## Local Development

Start both servers:

```sh
./dev.sh        # macOS/Linux
```

```powershell
./dev.ps1       # Windows PowerShell
```

The backend runs at `http://localhost:8000`. The frontend runs at `http://localhost:5173`.

If local screening data looks stale or inconsistent, reset the local SQLite database before starting dev:

```sh
./reset-db.sh
./dev.sh
```

```powershell
./reset-db.ps1
./dev.ps1
```

Or run services individually:

Backend:

```sh
cd backend
uv run fastapi dev app/main.py
```

Frontend:

```sh
cd frontend
npm run dev
```

## Tests

Backend:

```sh
cd backend
uv run pytest
```

Frontend build/type check:

```sh
cd frontend
npm run build
```

## Status

This is an active MVP. It is useful today for local screening workflows, but it is not yet a hosted multi-user production system.
