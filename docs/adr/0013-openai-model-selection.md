# 13. Evaluate Terra/Luna through Bedrock Mantle without switching defaults

- Status: **accepted** (transport and eval tooling; runtime switchover deferred)
- Date: 2026-08-21

## Context

The application originally used Claude Haiku for high-volume screening and scoring, and Claude
Sonnet for the higher-judgment Rank synthesis passes. M20 tested whether OpenAI's GPT-5.6 family
could reduce cost and latency without weakening the existing frozen prompts, structured outputs,
audit narratives, or human-review workflow.

The comparison used only the repository's synthetic local data. It kept Strands as the provider
abstraction: Claude used `BedrockModel`, while GPT used `OpenAIResponsesModel` through Amazon
Bedrock Mantle. No direct OpenAI API integration was added.

## Decision

Add Luna and Terra support behind the existing provider boundary, with an explicit reasoning effort
of `low`, but retain the current Haiku and Sonnet runtime defaults. The evidence-backed mapping for a
future switchover is:

| Pass | Preferred future model |
|---|---|
| Screening | `openai.gpt-5.6-luna` |
| Dimension scoring | `openai.gpt-5.6-luna` |
| Pattern discovery | `openai.gpt-5.6-terra` |
| Dimension decomposition | `openai.gpt-5.6-terra` |
| Dimension matching | `openai.gpt-5.6-terra` |
| Dimension consolidation | `openai.gpt-5.6-terra` |

Reasoning is explicit because GPT-5.6 defaults to `medium` when it is omitted. `Low` restored
Luna's quality to the Haiku baseline and gave Terra additional reasoning headroom without a
meaningful measured cost regression.

The production AWS account rejected both models as unavailable in `us-east-1`, `us-east-2`, and
`us-west-2` after its IAM policy was updated to authorize Mantle inference. This is an account-level
availability block, not a model-quality finding. M20 does not change persisted or default model
choices. It does persist `low` reasoning per pass so the chosen effort travels with the model
configuration; that value is inactive for Claude. After AWS enables both models, repeat the
synthetic production-credential probes before adding an explicit model switchover migration.

## Evidence

These results are dated snapshots, not universal model benchmarks. Prices, provider behavior, and
latency can change; rerun the same evals before a future model migration.

### Frozen-prompt golden suites

| Workload | Claude result | GPT result | Finding |
|---|---:|---:|---|
| Screening | Haiku 51/51 | Luna none 48/51; low 51/51; medium 50/51 | Luna requires low |
| Scoring | Haiku 14/15 | Luna none 12/15; low 14/15; medium 14/15 | Luna low matches Haiku |
| Decomposition | Sonnet 13/15 | Terra none/low/medium 15/15 | Terra was stronger |
| Matching | Sonnet 15/15 | Terra none/low/medium 15/15 | Equivalent quality |
| Consolidation | Sonnet 15/15 | Terra none/low/medium 15/15 | Equivalent quality |

Across the repeated Screening and Scoring suites, Luna-low cost $0.0532 versus Haiku's $0.4584.
Across the three repeated Terra-low synthesis suites, decomposition cost $0.1424, matching $0.0478,
and consolidation $0.0485, for $0.2387 total.

At medium reasoning, Luna cost $0.05331 across Screening and Scoring, effectively unchanged from
low in this small suite. Terra-medium cost $0.2219 across its three suites, 7% below low because it
happened to emit fewer total tokens. Reasoning effort is a ceiling rather than a fixed token charge;
small golden totals therefore show substantial run-to-run variance and should not be used alone for
capacity planning.

### Production-shaped synthetic Rank

Each run copied the 42-application local database, performed a full Rank in isolation, scored every
application, and ran the deterministic invariants.

| Configuration | Final dimensions | Baseline keys | Wall time | Cost | Failures / invariant violations |
|---|---:|---:|---:|---:|---:|
| Sonnet + Haiku control | 25 | 14 | 537.8 s | $1.6182 | 0 / 0 |
| Terra-none + Luna-low, run 1 | 36 | 20 | 107.5 s | $0.6814 | 0 / 0 |
| Terra-none + Luna-low, run 2 | 33 | 22 | 108.3 s | $0.7564 | 0 / 0 |
| Terra-low + Luna-low | 34 | 21 | 172.3 s | $0.6906 | 0 / 0 |
| Terra-medium + Luna-medium | 36 | 24 | 159.6 s | $0.9177 | 0 / 0 |

The Terra-low run's four Terra passes cost $0.5301, within the $0.5150-$0.5996 range of the two
Terra-none runs. Its longer wall time was dominated by Luna scoring taking 78.9 seconds despite an
unchanged Luna configuration, so that run does not isolate a Terra reasoning penalty. Discovery is
nondeterministic; dimension count and baseline-key overlap are review aids, not standalone quality
scores. Human inspection found the candidate dimensions broadly defensible.

Against the low full Rank, medium increased Luna from $0.16051 to $0.19838 (+23.6%) and Terra from
$0.53006 to $0.71928 (+35.7%). Total cost rose from $0.69057 to $0.91767 (+32.9%). Medium discovered
two more final dimensions, so Luna made 1,512 scoring calls instead of 1,470; normalized per call,
Luna still cost 20.2% more. Terra made the same eight calls at both settings, but discovery output
and the downstream prompt sizes vary between runs. The higher baseline-key overlap (24 versus 21)
is not enough to establish a quality gain because discovery is nondeterministic and prior none/low
runs already spanned 20-22 keys. With no golden improvement and one Luna regression, medium's
measured premium is not justified.

## Privacy decision

Future use of these models would process applicant text through Bedrock Mantle. The evaluated
account's effective retention mode was `default`, not zero-data-retention. Traffic flagged by AWS's
automated abuse detection may be retained by AWS for up to 30 days; AWS says operators cannot access
it and it is not shared with the model provider. The co-op explicitly accepted this tradeoff for a
future switchover of applicant-bearing passes.

Recheck the current
[AWS abuse-detection](https://docs.aws.amazon.com/bedrock/latest/userguide/abuse-detection.html) and
[data-retention](https://docs.aws.amazon.com/bedrock/latest/userguide/data-retention.html)
documentation before changing providers or retention settings.

## Reproduction

Run from `backend` with valid AWS credentials. Reports and copied databases belong under the ignored
`.pytest-tmp` directory.

```powershell
$env:UV_CACHE_DIR='.uv-cache'
uv run python -m app.evals.model_bakeoff `
  --repeat 3 --workers 10 --challenger-only --openai-reasoning-effort low `
  --output .pytest-tmp/m20-golden-low-repeat-3.json

uv run python -m app.evals.model_rank_bakeoff `
  --configuration candidate `
  --work-db .pytest-tmp/m20-rank-candidate.db `
  --output .pytest-tmp/m20-rank-candidate.json
```

Inspect aggregate pass/fail, tokens, cost, and duration in the JSON report. Review generated
dimensions and invariant results before accepting a future model change; a lower bill alone is not
a quality result.

## Consequences

- OpenAI models are available behind the existing provider-neutral interface with
  schema-constrained output, streamed audit narratives, cost ledgers, estimates, and spending caps.
- The current application remains on Claude and does not depend on Mantle availability.
- Each pass stores its reasoning effort beside its model. Effective reasoning is part of cache,
  Rank-fingerprint, and eval-run identity; settings for unsupported models are ignored.
- A future OpenAI switchover depends on Bedrock Mantle availability, bearer-token authentication,
  and explicit account access to both models in the configured region.
- That future model change will invalidate the relevant content-addressed caches and Rank-input
  fingerprint, so its first Screen and Rank will perform fresh work.
