# Architecture Decision Records

Significant architectural decisions for the Penta Application Screener, in
[MADR](https://adr.github.io/madr/)-style format — one immutable decision per file. These
were extracted from `SPEC.md` (M14 Phase 6) so the living spec can shrink to current-state
only; the ADRs preserve the *why* — including the rationale behind decisions that were later
reversed. The blow-by-blow session history lives in git and `docs/case-studies/`.

Each ADR records: Status, Context, Decision, Consequences. A **superseded**/**reversed**
record states what replaced it and why.

| # | Decision | Status |
|---|----------|--------|
| [0001](0001-remove-essay-analysis-pass.md) | Remove the essay-analysis pass (M6) | superseded — removed after measurement (digest +172% tokens, no coverage gain) |
| [0002](0002-blind-judge-eval-reframe.md) | Blind-then-compare judge; one deterministic grader per pass | superseded — replaced the inline per-pass judge design |
| [0003](0003-favourite-dimension-feature.md) | Favourite-dimension feature | reversed / superseded — collapsed into tier membership ("kept") |
| [0004](0004-orient-dimensions-at-discovery-no-direction-flag.md) | Orient dimensions at discovery (no direction flag) | reversed — `more/less/undecided` enum + sign-aware ranking reverted |
| [0005](0005-llm-extracts-features-deterministic-ranking.md) | LLM extracts scored features; ranking is deterministic math | accepted |
| [0006](0006-tier-list-weighting-over-pairwise-questions.md) | Tier-list weighting over sequential pairwise questions | accepted |
| [0007](0007-fan-out-discovery-single-call-decomposition.md) | Fan-out discovery + single-call decomposition (loop not built) | accepted |
| [0008](0008-grader-matched-to-output-shape.md) | Grader matched to output shape + derived prompt versions | accepted |
| [0009](0009-signed-scoring-scale-silence-neutral.md) | Signed −1..+1 scoring scale, silence = neutral | accepted |
| [0010](0010-provider-adaptable-ai-interface-cost-controls.md) | Provider-adaptable AI interface (Bedrock first) + cost controls | accepted |

ADRs 0001–0004 capture **superseded/reversed** decisions (the "four superseded strata");
0005–0010 capture **major decisions that still hold**.
