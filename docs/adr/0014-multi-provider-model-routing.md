# 14. Route supported models through Bedrock or direct provider APIs

Date: 2026-08-22

Status: accepted

## Context

The application began with Claude on Amazon Bedrock and added GPT-5.6 Luna and Terra through
Bedrock Mantle for M20. The production AWS account could not obtain Mantle model access, and low
Bedrock request-per-minute limits made Claude workloads slow even with bounded retries. Keeping
AWS as the only invocation boundary would therefore make provider availability and quota policy a
single operational bottleneck.

The rest of the application already depends on `AIProvider`, but model-family prefix checks had
started to spread routing knowledge into settings, traces, and the frontend. Adding two direct API
paths on top of those checks would make invalid provider/model combinations easy to create.

## Decision

Support four invocation routes behind the existing Strands-backed `AIProvider` implementation:

- Claude through Amazon Bedrock;
- GPT through Amazon Bedrock Mantle;
- GPT through OpenAI's Responses API; and
- Claude through Anthropic's Messages API.

A central, exact model catalog is the only routing authority. Each entry binds one provider-native
model ID to its provider, vendor, display label, and capabilities. Model IDs remain opaque outside
the catalog and continue to be the identity stored in settings, cache keys, traces, evals, and cost
rows. The eight supported routes have distinct provider-native IDs, so a second application model
identifier would add synchronization work without adding information.

The admin UI presents catalog entries rather than accepting free-form IDs. Direct-provider entries
are disabled until the corresponding deployment secret is configured. Saving shared AI settings is
admin-only. Credentials remain environment/Fly secrets and are never stored in the database or
returned by the settings API.

Existing Bedrock model defaults do not change. Adding credentials or deploying this code therefore
cannot switch the committee's live workload. A later operator choice can move each pass
independently after the direct route is verified in that environment.

## Consequences

- Callers, prompts, persistence, cost accounting, and observability do not branch on provider.
- Exact catalog validation rejects unsupported combinations early instead of relying on naming
  conventions or failing during a paid run.
- OpenAI reasoning effort remains per-pass configuration and only participates when the catalog
  says the selected model supports it.
- Direct APIs remove AWS as the only quota gate, but they have account-specific limits of their own.
  The existing maximum-worker setting is exposed to admins so bursts can be tuned without a code
  change; retries remain bounded in each transport.
- Bedrock region remains relevant to both Bedrock routes and inert for direct routes.
- Provider prices happen to be equivalent for the supported models as of this decision, but the
  application's explicit price table remains the spending-cap authority and must be reviewed when
  providers change pricing.

## Alternatives considered

**Separate provider and model selectors.** Rejected for now because it creates combinations the
application cannot invoke. A curated route selector communicates the real deployable choices and
keeps one stable identity throughout the pipeline.

**Replace Bedrock wholesale.** Rejected because the existing routes are tested, useful as a
fallback, and already isolated behind the same boundary. Removing them would reduce operational
choice without simplifying downstream code.

**Build vendor SDK adapters without Strands.** Rejected because Strands already normalizes the
structured-output and streaming contract across all four routes. The application retains its own
small provider interface, so this decision does not expose Strands types downstream.
