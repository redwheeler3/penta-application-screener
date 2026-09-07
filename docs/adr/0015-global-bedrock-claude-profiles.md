# 15. Route Bedrock Claude through global inference profiles

Date: 2026-09-06

Status: accepted

## Context

Production invoked Claude Haiku 4.5 and Sonnet 4.6 through `us.` geographic
cross-region inference profiles. Comparing July and August 2026 production run ledgers
with AWS Marketplace invoices showed that the application priced those calls at the
global-profile rates. The invoices were about 10% higher because geographic profiles
carry higher token prices.

Both models offer `global.` profiles from the existing `us-east-1` source region. AWS
may route a global-profile request to any supported commercial Region, keeps the traffic
on its network, and prices the route below a geography-bound profile. Applicant prompts
contain personal information, so worldwide processing is a privacy tradeoff rather than
an incidental model-ID edit. Penta's public privacy policy already discloses that service
providers may process information outside British Columbia or Canada.

## Decision

Use Bedrock's global inference profiles for the default Claude routes:

- `global.anthropic.claude-haiku-4-5-20251001-v1:0`
- `global.anthropic.claude-sonnet-4-6`

Keep `us-east-1` as the Bedrock source region. Update persisted AI settings from the
equivalent `us.` IDs during migration, but retain exact historical route IDs in AI result,
cost-ledger, and eval-fixture provenance. Both routes keep the same provider-neutral model
identities, so valid cached work and Rank freshness survive the transport change.

## Consequences

- Bedrock can process applicant prompts and outputs in any supported commercial AWS
  Region. The set may change as AWS expands a global profile.
- Claude token spend is approximately 10% lower than on geographic profiles, and global
  routing can draw on broader capacity.
- The Fly runtime still calls Bedrock from `us-east-1`; `global.` changes the inference
  profile's destination pool, not the client endpoint.
- The least-privilege IAM policy must authorize the global inference-profile ARN, the
  source-region foundation model, and the regionless global foundation model, constrained
  to the selected profile. The global resource evaluation uses `aws:RequestedRegion =
  "unspecified"`.
- Deployment verification must include one real Haiku call and one real Sonnet call before
  production settings are relied on. The invoke-only app identity does not need
  `bedrock:GetInferenceProfile`.
- Returning to geography-bound processing requires an explicit route change, updated IAM
  permissions, and geographic-profile pricing; changing only the displayed price would not
  constrain where inference runs.
