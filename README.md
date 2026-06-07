# Penta Application Screener

Application screener for Penta Housing Coop membership applications.

The project will import application responses from Google Sheets, apply deterministic hard filters, use AI-assisted review for essay answers, and produce a MOMI-ready shortlist report with justifications.

Current planning lives in [SPEC.md](SPEC.md). Shared agent guidance lives in [.clinerules](.clinerules), with [AGENTS.md](AGENTS.md) pointing agents there.

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

This repository is private while the application is being planned and built.
