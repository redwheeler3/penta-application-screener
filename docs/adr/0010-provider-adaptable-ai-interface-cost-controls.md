# 10. Provider-adaptable AI interface (Bedrock first) + cost controls

- Status: **accepted** (still holds)
- Date: MVP / Milestone 5–6 foundation

## Context

Jeff may work on this project from AWS-managed laptops where direct OpenAI/Anthropic API
calls may be blocked, so **Amazon Bedrock is the likely first provider.** But the app should
not lock to one vendor SDK. Separately, cost control is a **core product requirement** — a
committee running AI review over ~300 applicants must not be surprised by spend.

## Decision

**Depend on an internal AI provider interface, not a specific vendor SDK.** Bedrock is
implemented first; direct OpenAI/Anthropic providers can be added later behind the same
interface. Model choice is Admin-configurable and the cost estimate self-tunes per model, so
model selection is never a lock-in.

**Cost controls are first-class**, layered as:

- **Cached AI analysis** per application, keyed by `(raw_row_hash, kind, model,
  prompt_version)` — repeated work is never re-billed; shared across all committee members.
- **Model tiering:** smaller/cheaper models (Haiku) for first-pass extraction and scoring;
  frontier models (Sonnet) only for higher-judgment synthesis (pattern discovery,
  decomposition). Upgrades are decided empirically ("measure first"), never assumed.
- **A pre-run cost estimate** shown before any large review, and a **configurable spending
  cap per run** enforced once over the combined cost of a merged step.
- **Short structured outputs** over verbose freeform; batch/async where latency doesn't matter.
- Hard filters run automatically after sync; **AI review does not auto-run** — it starts only
  after the user sees the estimate and confirms (unless an Admin later enables auto-run).

## Consequences

- The provider interface is a single seam: `structured_output(..., on_delta=...)` — one call
  path that always drains the stream, with `on_delta` firing per reasoning chunk only when a
  caller wants deltas. (An earlier sync-vs-streaming two-method split was collapsed.)
- The known-in-advance call graph the pipeline design gives (see ADR 0005) is what makes
  pre-run estimates, the cap, per-unit caching, and eval-replay all *possible* — a
  runtime-variable swarm would fight every one of these requirements.
- Estimate-vs-actual is reconciled and surfaced (the project was bitten by an estimate that
  disagreed with reality); the estimate is an upper-bound ceiling, so under-estimate is the
  healthy norm and over-estimate is the flag.
- The app runs local-first for MVP (SQLite) while staying cloud-ready; the provider
  abstraction and DB portability keep later AWS deployment open.
