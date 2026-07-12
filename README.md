# Penta Application Screener

Local-first tool that turns 300+ housing co-op applications into a committee-ready, weighted shortlist — with a human in the loop at every stage and every AI-influenced number traceable back to its evidence.

It imports Google Sheets responses, applies deterministic eligibility filters, runs cached AI passes over the eligible pool, and produces a ranked list with per-candidate rationale. Reviewers get a searchable table, candidate detail pages, audit-friendly flags, human overrides, and an interactive tier-list for weighting what matters.

It's both a working MVP for a real co-op screening workflow and a portfolio project exploring the craft of AI product design: human-in-the-loop review, cost-aware model use, and the judgment of which decisions to keep deterministic and which to hand to an LLM.

## Design Highlights

A few decisions I'm particularly happy with — the ideas that make this more than a wrapper around an LLM call:

- **AI suggestions are inert until a human activates them.** The model may propose *any* differentiating dimension, but a discovered one carries **weight 0 until a committee member drags it into a tier** — nothing the AI says can move a ranking on its own. Safety becomes a property of the workflow rather than of prompt wording, so *every* junk suggestion is harmless by default, including the ones I never anticipated.

- **The LLM extracts features; the math does the ranking.** No model is ever asked "who's the best candidate?" — it scores each applicant per dimension (with rationale and evidence), and fit is a pure, inspectable formula, `Σ(weight·score) / Σ(weight)`, so every ranked number traces back to a specific score and a committee-assigned weight.

- **Prompt identity as a cache key.** Each pass hashes its own static prompt text into a `PROMPT_VERSION`, so editing a prompt re-runs *only that pass* — and re-ranking after re-tiering reuses cached scores via an LLM identity-match, charging model calls only for genuinely new or changed dimensions.

- **Cost estimated up front, capped, and attributed.** Every run projects its cost before starting, is checked against a server-side spending cap, and refuses no-op re-runs — AI spend is a first-class product surface, not a surprise on a bill.

## What It Does Now

The workflow is three single-verb steps — **Import → Screen → Rank** — each gated behind a confirmation card with an up-front cost estimate, plus a "View ranking" action.

- Google OAuth login with signed server-side sessions.
- Read-only Google Sheets sync into a local SQLite database.
- Configurable application settings for unit size, move-in date, income range, household rules, pets, and disabled deterministic rules.
- Deterministic hard filters for clear eligibility issues, applied at import.
- Application dashboard, searchable/sortable table, facets, pagination, and candidate detail pages.
- **Screen:** AI integrity pass flagging suspicious, AI-boilerplate, or low-quality submissions (informational input to human review, never auto-disqualifying).
- **Rank:** one orchestrated AI chain over eligible applicants — parallel pattern discovery of differentiating dimensions → decomposition into one non-overlapping set → per-dimension scoring — feeding a weighted ranked list with relative fit bands and per-driver rationale. (See *The LLM extracts features; the math does the ranking* above.)
- **Interactive tier-list weighting:** drag discovered criteria into Critical/Important/Minor/Ignore tiers to instantly re-sort. Re-ranking carries tier placements forward and reuses cached scores (see *Prompt identity as a cache key* above).
- **Reports:** browser print-to-PDF of the ranked view and candidate detail pages, with an `@media print` stylesheet and a text importance-tiers summary.
- Provider-agnostic AI interface with Amazon Bedrock/Strands as the concrete provider and a deterministic mock provider for tests.
- Admin-only raw source row and raw AI output debug panels.
- Human status overrides with stale-finding indicators when machine findings change later.

The next planned milestone (M13) is AI observability and evals: a per-pass AI trace viewer (what each pass output, match/discovery audit included), cost attribution, operational metrics, and property-based quality checks. The failure-capture prerequisite (Stage 0) is done.

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
