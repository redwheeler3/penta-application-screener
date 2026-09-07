# 16. Route Bedrock GPT through global Runtime profiles

Date: 2026-09-06

Status: accepted

## Context

M20 integrated GPT-5.6 Luna and Terra through Bedrock Mantle because Strands exposed
Mantle as its turnkey OpenAI-compatible Bedrock route. At that point the production
account could not invoke the models, so direct OpenAI routes were added and a Bedrock
switchover was explicitly deferred. Later production probes isolated a separate Terra
failure to Mantle: equivalent requests stalled before response headers in two source
Regions while Luna, Claude, and direct Terra succeeded.

AWS added geographic and global Bedrock Runtime inference profiles for GPT-5.6 in
August 2026 and now recommends Runtime for new integrations. Runtime supports the
OpenAI Responses API and streaming that this application already uses. Mantle's
additional server-side tools, background inference, and flexible projects are not used
here. The installed OpenAI SDK supplies a Bedrock provider that signs Runtime requests
from the normal AWS credential chain, and Strands' `OpenAIResponsesModel` accepts that
client through its generic configuration. The installed SDK release cannot yet select
Runtime's SigV4 signing service for a custom Runtime URL, so the client instead receives
a fresh short-lived Bedrock bearer token signed from the normal AWS credential chain for
each request attempt.

## Decision

Route Bedrock GPT through the `us-east-1` Bedrock Runtime endpoint and these global
inference profiles:

- `global.openai.gpt-5.6-luna`
- `global.openai.gpt-5.6-terra`

Keep `OpenAIResponsesModel`, the Responses API, explicit reasoning effort, streaming,
and stateless requests. Configure its OpenAI client with the SDK's Bedrock provider,
an explicit Runtime base URL, and per-request bearer tokens derived from the existing AWS
credential chain. Do not collapse GPT onto Strands' Converse adapter: preserving the evaluated
vendor-native interaction contract is more valuable than sharing one adapter class.

Migrate only active saved settings from the Mantle IDs. Historical result, cost-ledger,
and eval-fixture model IDs remain unchanged as provenance. The global and direct routes
retain their shared provider-neutral identities, so valid cached work and Rank freshness
survive the transport change.

## Consequences

- All Bedrock models now use Runtime and global inference profiles from one source
  Region, while Claude and GPT retain their appropriate wire protocols.
- Global GPT pricing matches the rates already used by the cost calculator. Mantle's
  approximately 10% higher in-region rates no longer create an accounting mismatch.
- The IAM user no longer needs `bedrock-mantle:*` or conditional Marketplace subscription
  permissions. Runtime Responses calls need `bedrock:InvokeModel*` on the selected global
  profiles, their foundation-model resources, and the account's default project, plus
  `bedrock:CallWithBearerToken` for Runtime authentication.
- Runtime has quota-based throughput rather than Mantle's work-queueing model. The
  existing `max_workers` control and bounded provider timeouts remain the operational
  controls; real Luna and Terra probes are required before relying on the route.
- The previous Mantle-specific Terra stall is bypassed, not proven fixed. A successful
  Runtime probe is new evidence for this route only.
- Worldwide processing and abuse-detection retention carry the privacy implications
  already accepted and documented for global Claude profiles.

## Alternatives considered

**Keep Mantle and correct its prices.** This would retain unused capabilities, the known
Terra failure mode, and in-region pricing without providing a benefit to this application.

**Use Strands' Bedrock/Converse adapter for GPT.** Runtime supports Converse, but changing
both the endpoint and wire protocol would make it harder to distinguish transport effects
and would discard the Responses behavior evaluated in M20.

**Use direct OpenAI exclusively.** The verified direct route remains available as a
fallback. Removing Bedrock would reduce operator choice and make the application depend on
one provider boundary without simplifying its downstream AI contract.
