# Penta Application Screener

Local-first application screener for Penta Housing Co-op membership applications.

The app imports Google Sheets application responses, applies deterministic eligibility rules, runs cached AI passes over eligible applications, and produces a deterministic, committee-weighted ranked list with per-candidate rationale. Reviewers get a searchable application table, candidate detail pages, audit-friendly flags, human overrides, and an interactive tier-list for weighting what matters.

This is both a practical MVP for a co-op screening workflow and a portfolio/learning project around AI product management, human-in-the-loop review, cost-aware AI use, and readable full-stack application design.

## What It Does Now

The workflow is three single-verb steps — **Import → Screen → Rank** — each gated behind a confirmation card with an up-front cost estimate, plus a "View ranking" action.

- Google OAuth login with signed server-side sessions.
- Read-only Google Sheets sync into a local SQLite database.
- Configurable application settings for unit size, move-in date, income range, household rules, pets, and disabled deterministic rules.
- Deterministic hard filters for clear eligibility issues, applied at import.
- Application dashboard, searchable/sortable table, facets, pagination, and candidate detail pages.
- **Screen:** AI integrity pass flagging suspicious, AI-boilerplate, or low-quality submissions (informational input to human review, never auto-disqualifying).
- **Rank:** one orchestrated AI chain over eligible applicants — essay analysis → pattern discovery of differentiating dimensions → per-dimension scoring — feeding a deterministic, weighted ranked list with relative fit bands and per-driver rationale. The LLM extracts scored features; the ranking itself is pure deterministic math.
- **Interactive tier-list weighting:** drag discovered criteria into Critical/Important/Minor/Ignore tiers to instantly re-sort. Re-ranking carries the committee's tier placements forward by LLM identity-match, reusing cached per-dimension scores so only new or changed dimensions are re-scored.
- **Reports:** browser print-to-PDF of the ranked view and candidate detail pages, with an `@media print` stylesheet and a text importance-tiers summary.
- AI integration is backed by a provider-agnostic interface with Amazon Bedrock/Strands as the current concrete provider and a deterministic mock provider for tests.
- Shared AI result caching by application content, model, and derived prompt version (a hash of the static prompt text), so repeated runs reuse stored results and editing a prompt re-runs only that pass.
- Per-run cost estimates enforced against an admin-configurable spending cap before any run starts; no-op re-runs are blocked server-side (Screen when nothing is uncached, Rank when the eligible pool is unchanged).
- Admin-only raw source row and raw AI output debug panels.
- Human status overrides with stale-finding indicators when machine findings change later.

The next planned milestone (M13) is AI observability and evals: surfacing cost attribution, the match/discovery audit, operational metrics, and property-based quality checks.

Current planning lives in [SPEC.md](SPEC.md). Developer architecture notes live in [docs/app-architecture.md](docs/app-architecture.md), with deeper references in [docs/ai-screening.md](docs/ai-screening.md), [docs/api.md](docs/api.md), and [docs/form-field-reference.md](docs/form-field-reference.md). Shared agent guidance lives in [.clinerules](.clinerules), with [AGENTS.md](AGENTS.md) pointing agents there.

## Privacy And Test Data

Applicant data is sensitive. Do not commit real application exports, local SQLite databases, OAuth credentials, raw AI traces, exported/printed reports with applicant data, or `.env` files.

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

## License

This project is licensed under the **Apache License 2.0**. See [LICENSE](LICENSE).
