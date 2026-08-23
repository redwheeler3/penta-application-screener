# 13. Select Luna/Terra and verify the direct OpenAI route

- Status: **accepted** (direct route production-verified; runtime switch is operator-controlled)
- Date: 2026-08-21

## Context

The application originally used Claude Haiku for high-volume screening and scoring, and Claude
Sonnet for the higher-judgment Rank synthesis passes. M20 tested whether OpenAI's GPT-5.6 family
could reduce cost and latency without weakening the existing frozen prompts, structured outputs,
audit narratives, or human-review workflow.

The comparison used only the repository's synthetic local data. It kept Strands as the provider
abstraction: Claude used `BedrockModel`, while GPT initially used `OpenAIResponsesModel` through
Amazon Bedrock Mantle. Direct routes were added after the production AWS availability block.

## Decision

Add Luna and Terra support behind the existing provider boundary, with an explicit reasoning effort
of `low`, but retain the current Haiku and Sonnet runtime defaults. The evidence-backed mapping for a
future switchover is:

| Pass | Preferred future model |
|---|---|
| Screening | `gpt-5.6-luna` |
| Dimension scoring | `gpt-5.6-luna` |
| Pattern discovery | `gpt-5.6-terra` |
| Dimension decomposition | `gpt-5.6-terra` |
| Dimension matching | `gpt-5.6-terra` |
| Dimension consolidation | `gpt-5.6-terra` |

Reasoning is explicit because GPT-5.6 defaults to `medium` when it is omitted. `Low` restored
Luna's quality to the Haiku baseline and gave Terra additional reasoning headroom without a
meaningful measured cost regression.

The production AWS account rejected both models as unavailable in `us-east-1`, `us-east-2`, and
`us-west-2` after its IAM policy was updated to authorize Mantle inference. This is an account-level
availability block, not a model-quality finding. M20 does not change persisted or default model
choices. It does persist `low` reasoning per pass so the chosen effort travels with the model
configuration; that value is inactive for Claude. Direct OpenAI is the selected future route because
the production AWS account remains blocked. Production defaults change only through an explicit
admin selection; installing credentials alone cannot move a workload.

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

### Direct-provider verification

On August 22, 2026, direct structured-output probes passed for Luna, Terra, Haiku, and Sonnet.
Direct Luna-low passed 51/51 Screening cases and direct Terra-low passed all 45/45 synthesis cases
over three repeats without transport or throttling errors. Luna initially passed 12/15 Scoring
cases; a focused comparison confirmed that it over-scored the modest-evidence case more often than
Haiku. One provider-neutral sentence reserving scores beyond +/-0.7 for substantial pole-level
evidence corrected that calibration without changing the fixture: Luna then passed 25/25 Scoring
judgments over five repeats.

On August 22, 2026, synthetic schema-constrained probes also passed from the production Fly Machine
for direct Luna-low and Terra-low. Both returned valid structured output and an audit narrative. The
probe read no application data and did not change the persisted production model settings.

Two direct Luna-low plus Terra-low synthetic Ranks completed all 40 applicants with no failed calls
or invariant violations. They took 186.7 and 235.8 seconds and cost $1.5038 and $1.7623, producing
35 and 41 final dimensions. Human review found the larger sample over-segmented in places; the two
runs are evidence of expected discovery variance, not a reason to reward dimension count.

Direct OpenAI uses different [standard prices](https://platform.openai.com/pricing) from Bedrock:
Luna is $1.00 input / $6.00 output and Terra is $2.50 input / $15.00 output per million tokens as of
this decision. Exact provider-native IDs now select route-specific prices. Direct OpenAI is
therefore an availability decision, not an isolated price reduction.

## Privacy decision

The co-op accepts the documented provider privacy tradeoffs for applicant-bearing passes. Direct
routes process application content under the selected vendor's API terms; Bedrock routes use AWS's
terms and account retention settings. The active route is explicit in admin settings and model
traces. Recheck the selected provider's current data-use and retention terms before changing routes
or privacy settings.

## Reproduction

Run from `backend` with the credential for the selected route. Reports and copied databases belong
under the ignored `.pytest-tmp` directory.

```powershell
$env:UV_CACHE_DIR='.uv-cache'
uv run python -m app.evals.model_bakeoff `
  --route direct --repeat 3 --workers 10 --challenger-only `
  --openai-reasoning-effort low `
  --output .pytest-tmp/m20-golden-low-repeat-3.json

uv run python -m app.evals.model_rank_bakeoff `
  --configuration direct-candidate --workers 10 `
  --work-db .pytest-tmp/m20-rank-candidate.db `
  --output .pytest-tmp/m20-rank-candidate.json
```

Inspect aggregate pass/fail, tokens, cost, and duration in the JSON report. Review generated
dimensions and invariant results before accepting a future model change; a lower bill alone is not
a quality result.

## Consequences

- OpenAI models are available behind the existing provider-neutral interface with
  schema-constrained output, streamed reasoning summaries or user-visible tool preambles, cost
  ledgers, estimates, and spending caps. These are exposed audit narratives, not raw private chain
  of thought.
- The current application remains on Claude and does not depend on Mantle availability.
- Each pass stores its reasoning effort beside its model. Effective reasoning is part of cache,
  Rank-fingerprint, and eval-run identity; settings for unsupported models are ignored.
- Direct Luna-low and Terra-low are credential- and schema-verified on the production Fly Machine;
  an admin can switch each pass independently without a deployment.
- That future model change will invalidate the relevant content-addressed caches and Rank-input
  fingerprint, so its first Screen and Rank will perform fresh work.
