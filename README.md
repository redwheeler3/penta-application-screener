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
- **Rank:** one orchestrated AI chain over eligible applicants — parallel pattern discovery → decomposition into one non-overlapping set → identity-match onto prior runs → per-dimension scoring → post-score duplicate consolidation — feeding a weighted ranked list with relative fit bands and per-driver rationale. (Detailed in *The AI Pipeline* below; the ranking math is in *The LLM extracts features; the math does the ranking* above.)
- **Interactive tier-list weighting:** drag discovered criteria into Critical/Important/Minor/Ignore tiers to instantly re-sort. Re-ranking carries tier placements forward and reuses cached scores (see *Prompt identity as a cache key* above).
- **Reports:** browser print-to-PDF of the ranked view and candidate detail pages, with an `@media print` stylesheet and a text importance-tiers summary.
- Provider-agnostic AI interface with Amazon Bedrock/Strands as the concrete provider and a deterministic mock provider for tests.
- Admin-only raw source row and raw AI output debug panels.
- Human status overrides with stale-finding indicators when machine findings change later.

## The AI Pipeline

Every AI call is a **named, single-purpose pass** — never a general "agent" deciding what to do next. The orchestration is deterministic code and human-gated workflow steps; no model chooses which pass runs, and no pass calls another. Each is a structured-output call with its own prompt, schema, cache/version, cost line, and reasoning trace. Model tier is chosen per job: cheap-and-fast **Haiku** where call *count* drives cost, stronger **Sonnet** for the once-per-run judgment calls.

**Screen** (one pass, runs on its own):
- **Screening integrity flags** *(Haiku)* — reads each application and flags placeholder/suspicious names, spam or AI-boilerplate essays, internal inconsistencies, and contact/pet-policy issues. Informational only; never auto-disqualifies.

**Rank** (one button, five passes chained deterministically over the eligible pool):
1. **Pattern discovery** *(Sonnet, ×K in parallel)* — reads the whole pool and discovers the dimensions it actually varies on. Runs K times on fresh contexts; their cross-call disagreement is the diversity the next step needs. Each call is blind except for committee proposals seeded into one worker.
2. **Decomposition** *(Sonnet)* — settles the K overlapping discovery reports into one finest, non-overlapping set: collapses re-carvings of one concept, keeps genuinely distinct axes apart, protects committee-requested axes.
3. **Identity matching** *(Sonnet)* — maps this run's dimensions onto prior runs' by *meaning*, so a re-discovered concept re-adopts its old key and carries its tier placement + cached scores forward. A high bar (a wrong match corrupts a reused score), so it errs toward "new."
4. **Dimension scoring** *(Haiku, per candidate)* — scores each applicant 0–1 on each dimension, with a rationale and grounding evidence. The only per-applicant pass; everything above is pool-level.
5. **Consolidation** *(Sonnet)* — post-score cleanup: since every dimension now has a per-applicant score vector, near-identical vectors *nominate* suspected duplicates the definition-only match pass missed, and one confirm call merges genuine ones (aliasing the newer key to the older, so the key space converges instead of growing). Distinct axes that merely correlate are kept apart.

Then the ranking itself is **pure deterministic math** over the cached scores and committee tier weights — no model call. Two invariants hold across all of it: **AI output is inert until a human activates it** (a discovered dimension has weight 0 until tiered), and **every pass persists its reasoning + cost** so any number traces back to its evidence.

The **Insights** tab surfaces this per run: what each discoverer found, how decomposition settled them, which duplicates consolidation merged and why, how dimensions carried forward, and a full cost breakdown per pass.

The next planned milestone (M13) is deeper AI observability and evals: the per-pass trace viewer and cost attribution are largely in place (discovery/decomposition/consolidation/match audits + per-pass cost, above); still to come are operational metrics and property-based quality checks. The failure-capture prerequisite (Stage 0) is done.

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
On Windows, `dev.ps1` writes per-service output and errors to `.dev-logs/`. If either
service exits, it prints the last log lines; it also retries the frontend twice before
leaving the backend running for diagnosis.

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
