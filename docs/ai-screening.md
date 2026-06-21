# AI Screening

This document explains how AI-assisted screening works: the quality-flag pass that reviews applications for data-integrity concerns, how results are cached and cost-capped, and how the pass runs many applications concurrently.

It is a companion to [app-architecture.md](app-architecture.md). The architecture doc gives the one-paragraph summary; this doc is the depth.

## What It Is, And What It Is Not

The AI quality-flag pass reads each application and surfaces **informational concerns** a human screener should be aware of — a placeholder-looking name, a non-responsive essay, a pet description that conflicts with the co-op policy, an obviously fake phone number.

Two principles bound the whole feature:

- **Flags are never disqualifying.** They are notices for a human to review, not acceptance or rejection decisions. The deterministic hard filters (in `app/domain/hard_filters.py`) decide eligibility; AI only annotates.
- **The model is told to be conservative.** It flags only concrete, evidenced problems. Most applications are expected to come back with zero flags.

This separation is why AI sits *on top of* the deterministic rules rather than replacing them.

## The Mental Model

```text
POST /quality-flags/run
  app/api/quality_flags.py
    enforce the spending cap (fail fast if the run would cost too much)
    screen_quality_flags(...)        app/ai/quality_flags.py
      for each application:
        check the cache              app/ai/analysis.py  (DB read)
        build the prompt             (reads normalized fields + essays)
      run the uncached prompts CONCURRENTLY through Bedrock
        provider.structured_output  app/ai/strands_provider.py  (Strands + Bedrock)
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
- `strands_provider.py` — the real implementation, backed by the Strands Agents SDK on Amazon Bedrock.
- `mock_provider.py` — a deterministic in-memory provider for tests and offline development. No AWS access.
- `analysis.py` — the shared engine: cache key, cache read/write, cost estimate, and spending-cap enforcement. Provider-agnostic.
- `quality_flags.py` — the quality-flag pass itself: prompt building, which applications to analyze, and the concurrent orchestrator.
- `schemas.py` — the structured-output contract (`QualityFlagReport` and its `QualityFlag` items). One definition shared by prompt, storage, API, and UI.
- `pricing.py` — Bedrock token prices, used for cost estimates and the cap.

Plus one HTTP route module and one domain module:

- `app/api/quality_flags.py` — the `/quality-flags/estimate` and `/quality-flags/run` endpoints.
- `app/domain/status.py` — how flags translate into an application's eligibility status.

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

1. **Tests run with no AWS.** The route's `get_ai_provider` dependency is overridden with `MockProvider`, which returns pre-queued results. Tests assert on caching, cost, and status without ever calling Bedrock.
2. **The model vendor is swappable.** If the model backend changed, only `strands_provider.py` would change.

`strands_provider.py` imports the SDK lazily (inside the methods, not at module top) so importing the module — which the test suite does transitively — does not require `strands` or AWS configuration to be present.

## Structured Output

The model does not return free text we then parse. It returns data validated against a Pydantic schema:

```py
class QualityFlag(BaseModel):
    category: FlagCategory      # placeholder_name, minimal_essay, pet_policy, ...
    severity: FlagSeverity      # info | notable
    summary: str                # one neutral sentence
    evidence: str               # short quote or field reference, no full essays

class QualityFlagReport(BaseModel):
    flags: list[QualityFlag] = Field(default_factory=list)
```

An empty `flags` list means "the integrity pass found nothing." The same schema definition is the contract for the prompt (what the model must produce), storage (`ApplicationAIResult.output` JSON), the API, and the UI rendering — so they cannot drift apart.

Alongside the structured flags, the provider also captures the model's free-text **narrative** (its reasoning). Producing structured output splits the model's reasoning across several assistant turns, so `strands_provider.py` walks every assistant message and concatenates the text blocks. The narrative is stored for the "Raw AI output" view on the candidate detail page and is never parsed.

## Caching

A full run over ~300 applicants would be wasteful if every run re-analyzed everything. So each result is cached.

```py
cache_key = sha256(raw_row_hash + kind + model_id + prompt_version)
```

The key combines:

- **`raw_row_hash`** — the application content. Edit the application, miss the cache.
- **`kind`** — the analysis type (`quality_flags`), so different passes don't collide.
- **`model_id`** — change the model, miss the cache.
- **`prompt_version`** — a constant bumped by hand whenever the prompt or schema changes, so old results are not reused after a prompt change.

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
  3. Only if there is **no usage history at all**, a static fallback (`fallback_input_tokens` / `fallback_output_tokens`, passed in by the quality-flag pass).

  The average is taken over the most recent 50 calls (`_USAGE_SAMPLE_SIZE`). So the estimate gets more accurate as real runs accumulate, while the *rate* it multiplies by stays fixed.

- **The number of applications** counts only the *uncached* ones — cached results are free and excluded from the estimate.

**The cap** (`ai.spending_cap_usd`, default `$0.50`) is enforced before streaming starts. An over-cap run fails fast with HTTP 402 rather than spending partway through.

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

The model call is the slow part — a blocking, multi-second Bedrock round-trip. Everything else (cache lookup, prompt building, persistence, status) is sub-millisecond. So screening ~300 applications one-at-a-time spent almost all its wall-clock waiting on the network, serially.

`screen_quality_flags` runs the model calls concurrently through a `ThreadPoolExecutor` (default 50 workers). The design rule that makes this safe and simple:

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
- **Failures are isolated.** A model call that raises yields a `ScreeningResult` with an error (surfaced as an `error` event and a `failed` count) rather than aborting the whole batch. The other applications still complete.
- **One shared Bedrock client per model.** `StrandsProvider` builds the boto3 Bedrock client once per model id and reuses it across workers — it is stateless and thread-safe, and owns the HTTP connection pool. The per-call `Agent` is *not* shared, because it accumulates the conversation (read back for the narrative); a fresh one is built per call.

### Sizing The Pool

Three constraints govern how many workers are safe:

| Constraint | At ~300 applicants |
| --- | --- |
| Bedrock quota (us-west-2: ~10k requests/min, ~5M tokens/min for Haiku 4.5) | Far above any setting here; not binding. |
| Cost | Per-token, so concurrency-independent. The cap guards it regardless. |
| Connection pool | Sized to match the worker count (`max_pool_connections == max_workers`), so workers don't queue on sockets. |

The `ai.max_workers` setting (default **50**, capped 1–100) drives both the worker count and the connection-pool size — one knob, so the two numbers always agree. At ~300 applicants, 50 captures essentially all the available speedup; going higher saves only seconds while saturating the pool harder. If the applicant pool ever grew to thousands, the tokens-per-minute quota and pool sizing would be worth revisiting.

The connection client is configured with **adaptive retries** (`mode="adaptive"`), which backs off on throttling and retries transient 5xx/timeout errors at the client layer — cheap insurance once calls run in parallel, even though the quota headroom means throttling is unlikely here.

## The Streamed Response

`POST /quality-flags/run` responds as newline-delimited JSON (NDJSON), one line per event:

- `{"type": "progress", "processed": n, "total": N, "flagged": f}` — one per application as it finishes.
- `{"type": "error", "applicationId": id, "message": ...}` — for an application whose model call failed.
- `{"type": "summary", "analyzed": ..., "cached": ..., "flagged": ..., "failed": ..., "totalCostUsd": ...}` — the final line.

The route keeps a small `RunTally` of the counts and emits the summary at the end. The frontend reads the stream incrementally, updating a progress indicator and, on completion, showing how many were flagged, how much it cost, and how many (if any) failed.

## Configuration

AI settings live under `ai` in the admin settings (`app/schemas/settings.py`):

- `region` — Bedrock region (default `us-west-2`).
- `first_pass_model` — the quality-flag model. Default Claude Haiku 4.5, as a Bedrock inference-profile ID (`us.anthropic...`), which these models require.
- `synthesis_model` — reserved for heavier, judgment-driven milestones (default Claude Sonnet 4.6). Not used by the quality-flag pass.
- `spending_cap_usd` — the per-run cost ceiling (default `$0.50`). Editable from the settings form ("AI Screening" section).
- `max_workers` — screening concurrency and connection-pool size (default `50`). Config-only; not exposed in the UI.

The other `ai` fields (region, model IDs) are config-only too. The frontend still round-trips the whole `ai` block on save, so editing the cap never resets them.

## Tests

- `test_ai_analysis.py` — pricing, cache key, cache miss-then-hit, cost estimate, cap enforcement.
- `test_quality_flags.py` — prompt building, which applications are analyzed, status application, plus the concurrency contracts: that calls genuinely run in parallel (a thread barrier proves it) and that a failed call is isolated from the batch.
- `test_quality_flags_api.py` — the streamed run end-to-end with `MockProvider`: status transitions, the needs-review bucket, member-visible raw row and narrative, member status override, and facet counts.

`MockProvider` supports two ways to supply results: a FIFO `queue` (for count-only assertions) and content-routed `route` (bind a specific verdict to a specific application by a marker in its prompt). Routing exists because, under real concurrency, calls do not complete in submission order — so a test that needs a particular application to be flagged keys on content, not order.
