# AI Screening

This document explains how AI-assisted screening works: the **screening pass** that reviews applications for data-integrity concerns and the **Rank chain** that discovers evaluation criteria across the pool and scores candidates against them, how results are cached and cost-capped, and how each pass runs many applications concurrently.

It is a companion to [app-architecture.md](app-architecture.md). The architecture doc gives the one-paragraph summary; this doc is the depth.

The per-applicant passes are built on one shared engine (`app/ai/analysis.py`): the same caching, cost estimate, spending cap, narrative capture, and the concurrent `screen_applications` loop. They differ only in their schema, prompt, scope, and whether they affect status. Most of this doc describes the screening pass in detail; the [Ranking (Milestone 8)](#ranking-milestone-8) section covers the Rank chain.

## What It Is, And What It Is Not

The AI screening pass reads each application and surfaces **informational concerns** a human screener should be aware of — a placeholder-looking name, a non-responsive essay, an obviously fake phone number. It also **extracts the household's pets** as neutral counts (M15 1e); pets are not a concern the model judges — the per-member pet limit is applied deterministically downstream.

Two principles bound the whole feature:

- **Flags are never disqualifying.** They are notices for a human to review, not acceptance or rejection decisions. The deterministic hard filters (in `app/domain/hard_filters.py`) decide eligibility; AI only annotates.
- **The model is told to be conservative.** It flags only concrete, evidenced problems. Most applications are expected to come back with zero flags.

This separation is why AI sits *on top of* the deterministic rules rather than replacing them.

## The Mental Model

```text
POST /screening/run
  app/api/screening.py
    enforce the spending cap (fail fast if the run would cost too much)
    run_screening(...)               app/ai/screening.py
      for each application:
        check the cache              app/ai/analysis.py  (DB read)
        build the prompt             (reads normalized fields + essays)
      run the uncached prompts CONCURRENTLY through the selected provider
        provider.structured_output  app/ai/strands_provider.py  (Strands routes)
      as each call returns:
        price + store the result     app/ai/analysis.py  (DB write)
        set the application status    app/domain/status.py
      yield one result at a time
    stream NDJSON progress back to the browser
```

The key idea, expanded in [Concurrency](#concurrency) below: **only the model call runs in parallel worker threads. Every database and ORM access stays on the request thread.**

## The Files

The AI code lives in `backend/app/ai/`:

- `provider.py` — the provider-agnostic interface. The rest of the app depends on `AIProvider` (a Protocol), never on a vendor SDK directly. Defines `AIResult` (output + token usage + optional narrative) and `Usage`.
- `model_catalog.py` — exact supported model routes and capabilities; the only provider-routing authority.
- `strands_provider.py` — the real implementation, backed by Strands routes for Bedrock, OpenAI, and Anthropic.
- `mock_provider.py` — a deterministic in-memory provider for tests and offline development. No AWS access.
- `analysis.py` — the shared engine: cache key, cache read/write, cost estimate, spending-cap enforcement, and the concurrent `screen_applications` loop both passes run through. Provider-agnostic.
- `screening.py` — the screening pass: prompt building, which applications to analyze, and status application via the shared engine.
- `schemas.py` — the structured-output contracts (`ScreeningReport` and the Rank-chain schemas). One definition each, shared by prompt, storage, API, and UI.
- `pricing.py` — supported model token prices, used for cost estimates and the cap.

Plus HTTP route modules and one domain module:

- `app/api/screening.py` (the `/screening/run` + `/screening/run/estimate` "Screen" endpoints) and `app/api/ranking/` (the `/ranking/*` chain package: `run`, `current`, `shortlist`). Both depend on the shared `get_ai_provider` in `app/api/dependencies.py`. The discovery, decomposition, matching, and scoring passes have no standalone endpoints — they run only as phases of `POST /ranking/run`.
- `app/domain/status.py` — how screening flags translate into an application's eligibility status (the Rank-chain passes do not touch status).

## The Provider Boundary

The app never imports `strands` or `boto3` outside `strands_provider.py`. Everything else talks to the `AIProvider` Protocol:

```py
class AIProvider(Protocol):
    def structured_output(
        self, *, model_id: str, schema: type[SchemaT],
        prompt: str, system_prompt: str | None = None,
    ) -> AIResult: ...
```

This matters for two reasons:

1. **Tests run with no provider credentials.** The route's `get_ai_provider` dependency is overridden with `MockProvider`, which returns pre-queued results. Tests assert on caching, cost, and status without making an external model call.
2. **The model vendor is swappable.** If the model backend changed, only `strands_provider.py` would change.

`strands_provider.py` imports the SDK lazily (inside the methods, not at module top) so importing the module — which the test suite does transitively — does not require `strands` or AWS configuration to be present.

## Structured Output

The model does not return free text we then parse. It returns data validated against a Pydantic schema:

```py
class ScreeningFlag(BaseModel):
    category: FlagCategory      # placeholder_name, minimal_essay, fake_contact, ... (7 categories)
    summary: str                # one neutral sentence
    evidence: str               # short quote or field reference, no full essays

class PetFacts(BaseModel):      # M15 1e: neutral extraction, never a verdict
    dogs: int = 0
    cats: int = 0
    other_pets: list[str] = Field(default_factory=list)

class ScreeningReport(BaseModel):
    flags: list[ScreeningFlag] = Field(default_factory=list)
    pets: PetFacts = Field(default_factory=PetFacts)
```

An empty `flags` list means "the screening pass found no integrity concern." The same schema definition is the contract for the prompt (what the model must produce), storage (`ApplicationAIResult.output` JSON), the API, and the UI rendering — so they cannot drift apart. As of M15 1e the report also carries extracted **pet facts** (`pets`): the model reports the household's animals as neutral counts (it never judges the pet policy — pets are not a flag category), and a deterministic per-member hard filter decides pass/fail against each member's pet limits on read.

Alongside the structured flags, the provider also captures the model's free-text **narrative** (its reasoning). Producing structured output splits the model's reasoning across several assistant turns, so `strands_provider.py` walks every assistant message and concatenates the text blocks. The narrative is stored for the "Raw AI output" view on the candidate detail page and is never parsed.

## Caching

A full run over ~300 applicants would be wasteful if every run re-analyzed everything. So each result is cached.

```py
cache_key = sha256(raw_row_hash + kind + model_id + prompt_version)
```

The key combines:

- **`raw_row_hash`** — the application content. Edit the application, miss the cache.
- **`kind`** — the analysis type (`screening`), so different passes don't collide.
- **`model_id`** — change the model, miss the cache.
- **`prompt_version`** — **derived by hashing each pass's static prompt text** (`derive_prompt_version` in `analysis.py`), not bumped by hand: editing the prompt or an embedded fragment re-derives it automatically, so old results are not reused after a prompt change. Screening's `screening_prompt_version()` is a pure function of its prompt text (M15 1e: the prompt no longer cites the pet policy — it extracts neutral facts — so a pet-limit change is a hard-filter change judged on read, not a screening-cache change).

Cached results are stored in the `application_ai_results` table along with token counts, cost, and the narrative — kept for auditability. A cache hit is free and is never blocked by the spending cap.

## Cost Estimation And The Spending Cap

Because each model call costs money, a run is cost-estimated *before* it starts and blocked if it would exceed a configurable cap.

An estimate is the product of three things, and it helps to keep them separate:

```text
estimated cost  =  price rate  ×  token count per call  ×  number of uncached applications
```

- **The price rate** (USD per token) is *always* the hardcoded table in `pricing.py`, keyed by a substring of the model ID. It is hardcoded because the AWS Price List API does not list the Claude 4.x models we use, so a live lookup would always fall back anyway. An *unknown* model ID falls back to the most expensive known rate (Opus-tier), so a missing table entry never silently under-estimates. This rate is never learned — it is what AWS charges.

- **The token count per call** (how many input/output tokens a call will use) is where the learning happens. It is chosen in three tiers, best first:
  1. The average of recent real calls at the **current `prompt_version`** — the most representative of what the next run will cost.
  2. If the current version has no history yet (e.g. right after a prompt change), the average of recent real calls from **any earlier version** — still real data, better than a guess.
  3. Only if there is **no usage history at all**, a static fallback (`fallback_input_tokens` / `fallback_output_tokens`, passed in by the screening pass).

  The average is taken over the most recent 50 calls (`_USAGE_SAMPLE_SIZE`). So the estimate gets more accurate as real runs accumulate, while the *rate* it multiplies by stays fixed.

- **The number of applications** counts only the *uncached* ones — cached results are free and excluded from the estimate.

**The cap** (`ai.spending_cap_usd`, default `$2.00`) is enforced before streaming starts. An over-cap run fails fast with HTTP 402 rather than spending partway through.

The estimate feeds a pre-run confirmation in the UI, so a screener sees the projected cost and how many applications will actually be sent before committing.

## From Flags To Status

A flagged application is not silently flagged — it moves into a review bucket. `app/domain/status.py` resolves what a machine actor would assign:

```text
has hard-filter reasons  ->  ineligible, source = rules   (rules outrank AI)
has AI flags (no reasons) ->  ineligible, source = ai      (the "needs review" bucket)
neither                   ->  eligible,  source = untouched
```

Two rules keep this safe:

- **Rules outrank AI.** A rules-disqualified application is never re-analyzed by AI — it could not change the outcome and would only waste spend.
- **Humans outrank machines.** A human-set status is sticky: a re-run refreshes the underlying flags (so the staleness nudge stays accurate) but never overwrites the human's decision.

This is why re-running the pass is safe and can revise a verdict in *either* direction — an application AI once flagged can be cleared and restored to eligible if a prompt change clears it.

## Concurrency

The model call is the slow part — a blocking, multi-second provider round-trip. Everything else (cache lookup, prompt building, persistence, status) is sub-millisecond. So screening ~300 applications one-at-a-time spends almost all its wall-clock waiting on the network, serially.

The shared `screen_applications` loop (in `analysis.py`, used by both passes) runs the model calls concurrently through a `ThreadPoolExecutor` (default 50 workers). The design rule that makes this safe and simple:

> **Workers do only the pure model call. Every database and ORM access stays on the request thread.**

Concretely:

```text
request thread:   cache-check + build prompt   (touches the ORM)
                        |
                        v  hand each worker a plain (application, prompt_string)
worker threads:   provider.structured_output(prompt)   (no session, no ORM)
                        |
                        v  return a session-free AIResult
request thread:   price + store + set status   (touches the ORM)   as each completes
```

Because the SQLAlchemy session and every ORM object are touched by exactly one thread, **no locks on application state are needed** — thread-safety holds by construction. The worker is a pure function of a prompt string.

A few deliberate choices:

- **`as_completed`, not `map`.** Results are handled in the order calls *finish*, so one slow application never holds back the progress of faster ones. The browser sees progress stream in real time.
- **Failures are isolated.** A model call that raises yields a `PassResult` with an error (surfaced as an `error` event and a `failed` count) rather than aborting the whole batch. The other applications still complete.
- **One shared model client per configuration.** `StrandsProvider` reuses each configured provider SDK client across workers. The per-call `Agent` is *not* shared, because it accumulates the conversation (read back for the narrative); a fresh one is built per call.

### Sizing The Pool

Three constraints govern how many workers are safe:

| Constraint | At ~300 applicants |
| --- | --- |
| Provider quota (account/model/region or tier) | Can bind; tune concurrency from measured throttling. |
| Cost | Per-token, so concurrency-independent. The cap guards it regardless. |
| Connection pool | Sized to match the worker count (`max_pool_connections == max_workers`), so workers don't queue on sockets. |

The `ai.max_workers` setting (default **50**, capped 1–100) drives the worker count and the Bedrock connection-pool size. It is exposed in Admin Settings because direct and Bedrock quotas vary by account; reducing it lowers burst pressure without a deployment. Concurrency is not an RPM limiter, so persistent throttling still requires an appropriate provider quota or a future explicit rate limiter based on measured limits.

Provider clients use bounded retries for throttling and transient failures. Bedrock uses adaptive retry mode; direct SDKs use their native bounded retry behavior.

## The Streamed Response

`POST /screening/run` responds as newline-delimited JSON (NDJSON), one line per event:

- `{"type": "progress", "processed": n, "total": N, "flagged": f}` — one per application as it finishes.
- `{"type": "error", "applicationId": id, "message": ...}` — for an application whose model call failed.
- `{"type": "summary", "analyzed": ..., "cached": ..., "flagged": ..., "failed": ..., "totalCostUsd": ...}` — the final line.

The route keeps a small `RunTally` of the counts and emits the summary at the end. The frontend reads the stream incrementally, updating a progress indicator and, on completion, showing how many were flagged, how much it cost, and how many (if any) failed.

## Ranking (Milestone 8)

The ranked shortlist is **not an AI pass** — it is deterministic math over the cached dimension scores, so it does not touch the provider, the cache, or the spending cap. It lives in `app/domain/ranking.py` alongside `hard_filters.py` (deterministic domain logic, separate from AI evaluation), as a pure function with no DB or I/O. This is the architectural payoff of milestone 7's "the LLM extracts scored features; ranking is math on top of them" decision: re-ranking is a re-fetch, not a re-spend, which is what makes the milestone 9 interactions instant and reproducible.

- **Fit** is the weight-normalized average of a candidate's per-dimension scores: `Σ(weight·score) / Σ(weight)` over dimensions with weight > 0. Weights are **derived from the committee's tier layout, never stored** — `dimension_weights(run)` (in `services/ranking_run.py`) computes them from `run_state.tiers`. The AI never proposes importance. At milestone 8 every dimension sits in one tier, so the weights are uniform and fit is a plain average; milestone 9's tier-list is the only thing that moves weights off equal — still no model call, just a re-derivation from the layout.
- **Confidence is surfaced, never folded into fit.** Each `DimensionScore` keeps its confidence label for display, but a score moves the ranking by exactly its weight — so the order stays explainable top-down.
- **Bands are relative to the pool**, not absolute thresholds. A candidate's label ("Strong fit" … "Limited") comes from its rank position, split into even contiguous slices anchored at the top (so rank 1 is always top-band even in a small pool). Equal-fit candidates share a band. This matches the "how does THIS pool vary" framing and keeps numbers as supporting detail.
- **No fixed cut line.** The list is stack-ranked and the committee reads top-down as far as they like — there is no configurable shortlist line. `GET /ranking` returns the ordered rows + weights.

The frontend surfaces this as a **separate ranked view**, not a re-sort of the browse table: the order is the product, read top-down, and milestone 9's tier-list maker docks above it (drag criteria into importance tiers → `PUT /ranking/tiers` → re-sort, no model call). Re-running the Rank chain finds fresh criteria and re-scores, then refreshes an open ranking. The chain is gated on a **rank-inputs fingerprint** (`RankingRun.rank_inputs_fingerprint`, its own indexed column — a hash of the pool *plus* each rank-chain prompt and model), so re-ranking with unchanged inputs is flagged up-front (`/ranking/run/estimate` returns `ranking_current: true`); a re-run is still allowed (discovery is nondeterministic, so a member may want a fresh criteria set — the confirmation card explains nothing requires it). A new/edited/eligibility-changed application, or an edited prompt, moves the fingerprint.

**The Rank button (workflow simplification).** The model passes that produce a ranking — pattern discovery, decomposition, identity-match, dimension scoring, and post-score consolidation — are exposed in the UI as a single "Rank" step, because the committee never runs them individually. `POST /ranking/run` orchestrates them back-to-back and streams phase-aware progress (`phase` lines for criteria / scores / consolidate, `progress` lines within the per-candidate phases, a final `summary`). The passes stay separate underneath (distinct schemas, cache kinds, status behavior); only the endpoint and the button are merged. Crucially for the cost rules, the cap is enforced **once over the combined projected cost** (`GET /ranking/run/estimate` sums discovery + decomposition + scoring + consolidation), before any model call — so the single button keeps the same hard pre-run cost gate the individual passes had. The estimate is approximate: scoring scales with the dimensions discovery settles on, which do not exist until the criteria phase runs, so it is labeled as such. The workflow strip is correspondingly three single-verb steps — **Import** (sync + deterministic hard filters), **Screen** (the AI screening pass), **Rank** (this chain).

## Configuration

AI settings live under `ai` in the admin settings (`app/schemas/settings.py`):

- `region` — region for Bedrock routes (default `us-east-1`; inert for direct routes).
- One catalogued model route per AI pass, named by the job:
  - `screening_model`, `dimension_scoring_model` — the high-volume per-applicant passes. Default Claude Haiku 4.5: call *count* drives their cost (scoring is candidates × dimensions), so cheap-and-fast wins.
  - `discovery_model` — the pool-level pattern-discovery call. Default Claude Sonnet 4.6 (cross-document judgment).
  - `decompose_model` — the call that settles the K fan-out discovery reports into one non-overlapping set. Default Claude Sonnet 4.6 (cross-report synthesis).
  - `match_model` — the once-per-re-rank dimension identity match. Default Claude Sonnet 4.6; earned its own tier because on Haiku it over-matched drifted concepts. Bump to Opus only if a real run shows Sonnet still over-matching.
  - `consolidate_model` — the post-score duplicate-merge confirm call. Default Claude Sonnet 4.6. (`consolidate_correlation_threshold`, default 0.8, sets the Pearson nomination bar.)
- `spending_cap_usd` — the per-run cost ceiling (default `$2.00`). Editable from the settings form ("AI Screening" section).
- `max_workers` — per-application AI concurrency and Bedrock connection-pool size (default `50`), exposed to admins for quota tuning.

The admin UI exposes supported routes from the backend catalog and disables direct routes whose deployment credential is absent. Model and reasoning settings are saved per pass; provider credentials never enter the database or browser response.

## Tests

- `test_ai_analysis.py` — pricing, cache key, cache miss-then-hit, cost estimate, cap enforcement.
- `test_screening.py` — prompt building, which applications are analyzed, status application, plus the concurrency contracts: that calls genuinely run in parallel (a thread barrier proves it) and that a failed call is isolated from the batch.
- `test_screening_api.py` — the streamed run end-to-end with `MockProvider`: status transitions, the needs-review bucket, member-visible raw row and narrative, member status override, and facet counts.

`MockProvider` supports two ways to supply results: a FIFO `queue` (for count-only assertions) and content-routed `route` (bind a specific verdict to a specific application by a marker in its prompt). Routing exists because, under real concurrency, calls do not complete in submission order — so a test that needs a particular application to be flagged keys on content, not order.
