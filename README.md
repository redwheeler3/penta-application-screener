# Penta Application Screener

Application screener for Penta Housing Coop membership applications.

The project will import application responses from Google Sheets, apply deterministic hard filters, use AI-assisted review for essay answers, and produce a MOMI-ready shortlist report with justifications.

Current planning lives in [SPEC.md](SPEC.md). Shared agent guidance lives in [.clinerules](.clinerules), with [AGENTS.md](AGENTS.md) pointing agents there.

Developer architecture notes live in [docs/app-architecture.md](docs/app-architecture.md).

## Current Build Direction

- Backend: Python, FastAPI, SQLAlchemy, Alembic, SQLite
- Python tooling: `uv`, project-local virtual environment, `pytest`
- Frontend: Vite React with `npm`
- Authentication: Google OAuth with signed server-side session cookies
- Google integration: read-only Google Sheets import/sync for applications
- AI integration: OpenAI adapter behind a provider-agnostic interface, after deterministic filtering works

## First Implementation Phase

The first implementation phase should stop at:

1. Project scaffold and local dev environment
2. SQLite schema and migrations
3. Google OAuth setup checklist
4. Read-only Google Sheets sync
5. Dashboard shell
6. Deterministic hard filters and unit tests

## Setup

1. Install prerequisites: [uv](https://docs.astral.sh/uv/) (`brew install uv`), Node.js 20+ with npm (`brew install node`).

2. Install dependencies:

   ```sh
   cd backend && uv sync && cd ..
   cd frontend && npm install && cd ..
   ```

3. Place your Google OAuth client secret JSON (downloaded from Google Cloud Console) in `backend/secrets/`:

   ```sh
   mkdir -p backend/secrets
   # copy or move the downloaded client_secret_*.json file into backend/secrets/
   ```

   The backend auto-discovers any `client_secret_*.json` file in that directory. All other settings have working defaults for local dev.

6. Run database migrations:

   ```sh
   cd backend && uv run alembic upgrade head
   ```

See [docs/google-cloud-oauth-setup.md](docs/google-cloud-oauth-setup.md) for full Google Cloud and OAuth details.

## Local Development

Start both servers:

```sh
./dev.sh        # macOS/Linux
./dev.ps1       # Windows PowerShell
```

Or run them individually:

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

Run tests:

```sh
cd backend && uv run pytest
```

This repository is private while the application is being planned and built.
