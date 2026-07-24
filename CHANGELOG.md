# Changelog

All notable resolved milestone work for the Penta Application Screener (Python/FastAPI + React/TS housing co-op application screener). Organized by milestone, newest first. This file holds resolved history extracted from `SPEC.md`; the SPEC itself tracks current-state design only.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/). Commit hashes are preserved where the SPEC or git history cites them.

---

## Milestone 14 — Code, Schema & Docs Cleanup

Behavior-preserving cleanup pass taken before multi-member (M15) and hosting (M16), so both land on a clean base rather than the accreted `criteria` blob and 1000-line grab-bag files. Grounded in a five-part audit (backend, frontend, DB schema, docs, best-practice research, 2026-07-20). Governing principles: delete dead code before de-duplicating; rule-of-three-gated extraction (over-abstraction is as bad as sloppiness); no backward-compat when it fights simplicity (DB reset is an acceptable fallback); each phase keeps the tree green (ruff + pytest + `npm run build`).

### Phase 1 — Dead-code removal (pure subtraction)
- Removed the dead in-UI harvest feature end-to-end: `HarvestPanel.tsx`, `harvestEvalCases`, `.eval-harvest*` CSS, the `EvalCaseEditor` judge template, backend `GET /evals/harvest/{family}`, `_HARVESTERS`, `HarvestResponse`, and the two tests pinning it (`fe6e9b6`).
- Removed 9 dead `types.ts` eval-result types and 4 spent one-shot experiment scripts (`fix_decomposer_why`, `coverage_gate`, `marginal_coverage`, `exp_single_call_discovery`) — kept `analyze_convergence` for the still-owed locked-pool experiment (`f3989b7`).
- Swept ~13 comment tombstones and trimmed dead `BLOCK_CONSUMER` entries (`eb51cfb`).
- Deferred to Phase 5: dead columns (`discovery_model_id`, `sync_runs.notes`) and the pre-fan-out "legacy" branches (they die with the schema work).

### Phase 2 — Harvest logic relocated to scripts
- Deleted `capture_scores`/`capture_screening`; replaced by self-describing `scripts/harvest_scoring_cases.py` + `scripts/harvest_screening_cases.py` + a shared `scripts/_harvest_common.py` (synthetic-source guard, opaque applicant index, evidence-source stamping), emitting the current uniform envelope, round-trip-verified against the live loaders (`a3df735`). This is the sanctioned "harvest via scripts, co-author cases" workflow that replaces the in-UI harvest.

### Phase 3 — De-duplication (rule-of-three gated)
- Hoisted the 5×-copied `_emit` into a shared `stability.emit` + `DeltaSink`, dropping 5 `type: ignore` (`e1155fd`).
- Extracted the three categorical passes' shared grading/stability/descriptor plumbing into `app/evals/_categorical.py`, −94 lines (`5be98d8`).
- Added a `useFetchOnce` hook over 5 Insights panels (`954288e`); `DiscoveryPanel` intentionally left out (real `runId` dependency).
- The ~10-endpoint eval registry was deferred into Phase 4a (folded with the `evals.py` split so the file is touched once).

### Phase 4 — File & module organization
Split the two 1000-line grab-bag routers and extracted the monster functions while **keeping** the existing technical-layer structure (`app/{api,ai,evals,services,domain,db,schemas,core}`). A full feature-folder restructure was considered and declined: ~90% of the readability win lives in splitting the two files, and an ~80-file reorg right before M15 was large risk for small gain.
- **4a** — `api/evals.py` (1049 lines) → `api/evals/` package (`_shared`/`catalog`/`cases`/`runs`) with the endpoint registry; the 3 categorical passes' 6 near-identical handlers collapsed into a `CategoricalPass` spec + `register()` factory, −200 lines (`758b472`, `5684163`). Largest file now 356 lines.
- **4b** — `api/ranking.py` (1147 lines) → `api/ranking/` package (`run`/`current`/`insights`/`shortlist`); `rank_run.stream()` (~410-line nested generator) broken into three `_stream_*` per-phase helpers, with `_CriteriaWork`/`_CriteriaResult` dataclasses replacing 11-element tuple hand-offs; `RunTally` renamed `ScoreTally` to reconcile a collision with screening's flag-count `RunTally` (`21f335b`, `158346f`).
- **4c** — Split the cost-estimation trio out of `ai/dimension_scoring.py` (625→458) into `dimension_scoring_cost.py` (185); deleted the dead `estimate_scoring_without_dimensions` alias (`2dcee6d`).
- **4d** — Extracted `App.tsx` (785→654) hooks into `src/hooks/`: `useToasts`, `useApplications`, `useRanking` (`5d22381`). `useAiRuns` deliberately not extracted (would need ~8 injected callbacks — the wrong abstraction).
- **4e** — Naming pass + dedup + `.clinerules` fixes (`39c863c`): `.match-audit-hint` → `.panel-hint` (~30 sites); deduped the `money` formatter; fixed stale `.clinerules` refs (`NumberInput` gotcha, `ScreeningRun`→`RankingRun`).

### Phase 4f — API contract redesign (plan-first)
A drift-and-consistency pass on top of M11's HTTP surface; Jeff approved all 3 changes 2026-07-20.
- **Change 1** (`766b0fc`): estimates uniformly at `<run>/estimate` — `/ranking/estimate`→`/ranking/run/estimate`, `/screening/estimate`→`/screening/run/estimate` — dissolving the estimate-placement and screening/ranking asymmetries.
- **Change 2** (`a29d07c`): collapsed the 12 eval run-routes to 6 — each pass is one `POST /evals/{pass}` with `?mode=stability`; retired the bare `/stability` (now `/judge?mode=stability`).
- **Change 3** (`f9a21f2`): `/ranking/insights/*`→`/insights/*` (top-level `api/insights.py`), since they span Screen + Rank + score-current.
- Kept (right-size guard): action-style run RPC, camelCase, RFC 9457.

### Phase 5 — DB schema rationalization
- Split the `ranking_runs.criteria` grab-bag blob (`0640362`) into `dimension_report` (JSON), `rank_inputs_fingerprint` (indexed String), `run_state` (JSON = tiers + new_dimension_keys + proposed_dimensions), and a new 1:1 `ranking_run_audit` table (narrative + match/fan_out/decompose/consolidate) so the hot path stays lean.
- Dropped derived `weights` (re-derived from tiers), dead `discovery_model_id`, vestigial `ranking_runs.name`/`.status`, and `sync_runs.notes`; made `dimension_aliases` the sole merge-truth.
- Migration `c84f612585ea` backfills in Python (never `CAST(text AS JSON)`, uses `batch_alter_table`), reversible. **Verified on the live DB: 6 runs + 5 sync_runs migrated intact; round-trip preserved everything — no reset needed.** `.db` backed up to `penta_screener.pre-M14-phase5.db` first.

### Phase 6 — Docs & SPEC reduction
- In progress: reduce SPEC to a ~500-line current-state living spec, extract resolved history into this CHANGELOG, adopt `docs/adr/` (MADR-style). Cut the four fully-superseded strata (pre-reframe judge design, deleted reconcile subsystem, removed essay-analysis, the favourite contradiction); re-term M11/M12-stale docs; archive point-in-time design docs.

### Phase 7 — Post-cleanup follow-up passes
Two fresh-eyes reviews after the Phase 1–6 churn settled, both behavior-preserving and tree-green each step (ruff + pytest + `npm run build`), rule-of-three throughout.
- **Second cleanup pass** over the modules the M14 splits churned most (the ranking + evals API packages, the extracted cost module and hooks, the big eval components). Confirmed the refactor was structurally sound — the large abstractions (the `CategoricalPass` factory, the worker-thread reasoning bridge, the extracted hooks, `App.tsx` as orchestrator) were correctly judged and left alone — and landed small fixes: removed a `CRITERIA_STAGES` identity dict; renumbered fossilized phase comments; de-privatized `missing_dimensions_by_application` (a split had turned a same-file helper into a cross-module import); typed the scoring estimate (`ScoringEstimate` TypedDict) and RunnableEval's whole result-render path (`EvalCaseResult`/`EvalRunResult`, replacing pervasive `any` that had silently disabled the sole `tsc` guard — surfacing three unguarded-optional reads); centralized the eval-key unions on `EvalKey`; cleared naming/comment drift.
- **Broad sweep across every layer** (all of `app/ai`, `app/evals` + `app/api/evals`, `app/services` + `app/db`, `app/schemas`/`domain`/`core` + the top-level API, every frontend component, all docs) on their own merits, not only split seams. **Dead code** removed (four unused pass `KIND` constants, `format_agreement`, `JudgeStabilityReport.counts`); **de-duplication** (`_BACKGROUND_PASSES` identity map collapsed, `seed_str` delegating to each pass's own formatter, a shared `_resolve_chains` chain-walk, `_audit_field` for the 7× audit-null guard, `current_dimension_kinds` for a 2-site null-dance); **type tightening** (a shared `CostEstimate` TypedDict; `StatusOverride` on `RequestModel`; a promoted `InsightRunKind`; centralized `EvalRunMode`/`EvalFixtureKey`); **eval-reframe fossils** cleaned; **six docs drift fixes** verified against code; and three approved structural changes — removed the test-only `analyze_one`/`analyze_application` screening path (coverage preserved via the production path), converted `DiscoveryPanel` to `useFetchOnce`, wired the previously-dead judge `label_rationale` into the Judge tab, and dropped the always-NULL `ranking_runs.owner_user_id` column (reversible migration, round-trip verified on a DB copy, live DB backed up first). Left alone as correctly-judged: the `CategoricalPass` factory, the worker-thread bridge, `WorkflowBar`'s prop breadth, and `streamNdjson`'s `any` (a genuinely heterogeneous stream boundary).

---

## Milestone 13 — Observability And Evals

Made the AI pipeline legible: what it cost, what it did, and whether it is any good. Motivated by a re-rank that carried 18/18 dimensions forward by identical key with no way to distinguish genuine re-discovery from match-pass over-matching. Locked plan (2026-07-07), built in order across four pillars plus failure capture.

- **Failure capture (2026-07-07):** `error_type` preserved on `PassResult` + durable logging on the error path; behavior-neutral prerequisite for failure rates.
- **Pillar 1 — Cost surfacing** (built 2026-07-08, unified 2026-07-12): a "Cost" Insights subtab (`CostPanel` / `cost_report.py`) showing cumulative + last-run AI spend broken down per pass with token/model breakdown. Unified all cost accounting onto one shared `PassCost` value object and a single `RunPassCost` table (under a `RunCostLedger` header) that both Screen and Rank write and both surfaces read — collapsing three prior parallel cost structures. Per-run cost is now exact (stamped at write time); every pass is attributed separately. Estimate-vs-actual reconciliation added 2026-07-16 (`RunCostLedger.estimated_usd`, additive migration `server_default='0'`).
- **Pillar 2 — Per-pass AI trace viewer** (reframed; done 2026-07-14): every pass's raw output made legible, match-audit included as one panel.
- **Pillar 3 — Operational metrics** (built 2026-07-12): an Insights "Trends" subtab (`MetricsPanel` / `services/metrics.py`) charting per-run/per-pass cost, tokens, wall-clock latency, cache-hit rate, failure count, and dimension count over time. Two `RunPassCost` columns added (`duration_ms`, `failed_calls`). Honest scope calls: failure counts are real for per-application passes but ~always 0 for fatal pool passes; retry counts deliberately NOT captured (would be a fake or heavy observability lie).
- **Pillar 4 — Property-based evals** (built 2026-07-12): `app/evals/` scores a committed PII-safe fixture against checks split by determinism — **INVARIANTS** (hard-fail pytest CI gate: `poles_present`, `no_protected_attributes`) vs. **SIGNALS** (report-only: `overlap`, `match_rate`). Transferable lesson: split by determinism, not by "is it an eval" — a check you'd soften to keep green is a signal, not an invariant. `one_concept` was cut entirely (semantic, deferred to LLM-judge); `no_protected_attributes` narrowed to whole-word unambiguous terms.
- **Pillar 4 next layer — LLM-judge evals** (first checkpoint 2026-07-14): `python -m app.evals.judge`, a non-gating spend boundary, one Sonnet call per human-labelled case. Coverage extended to **five of six model steps** by 2026-07-16 (consolidation, decomposition, matching, scoring, screening; discovery covered transitively). Established three disciplines: the fidelity rule (judge sees exactly what production saw — no `r` value leaked), the contested category (both verdicts defensible; consistency, not direction, is what matters), and `r` stays out of the confirm step. Score-defensibility judge added with a synthetic-source guard (`app/evals/synthetic_guard.py`, `require_synthetic_pool`).
- Watch-item recorded (not actionable): scorer **confidence** calibration — `medium`-confidence scores cluster in 0.4–0.7 and rarely reach ≥0.9; the broad "under-anchoring" hypothesis was dismissed by a 1363-row distribution analysis (healthy full-range distribution). Do not tune the prompt on n≈1.

---

## Milestone 12 — Database Schema Refactor + Terminology Sweep

Cleaned the persisted data model once the API contract was settled and aligned internal vocabulary with the data/API schema.

- `ScreeningRun` → `RankingRun` (table `ranking_runs`); legacy nullable-for-old-rows columns tightened to non-null (`ApplicationAIResult.prompt_version`, `SyncRun.settings_fingerprint`); the 7-migration chain squashed to one fresh baseline (`18fae53`).
- With "screening" freed by the model rename, the **Screen step** claimed it: route `/quality-flags` → `/screening`, AI-result `kind` `"quality_flags"` → `"screening"`, and the whole `quality_flags`/`QualityFlag*`/`qf*` family → a screening vocabulary (findings are now `flags`; the dashboard flag is `screened`).
- Consistency fixes: `PoolPatternReport` → `PoolDimensionReport`, `current_pattern_report` → `current_dimension_report` (the discovery act stays `discover_patterns`); generic `ScreeningResult` → `PassResult`; frontend types harmonized (`RankEstimate` → `RankEstimateResponse`, `RankingState` → `RankingResponse`, `ScreeningRunState` → `CurrentRunResponse`).
- `/sync` deliberately kept (not renamed to `/import`). Presentational CSS classes (`qf-*`, `quality-flags`) renamed too.
- **Naming principle (gem):** the code's internal vocabulary matches the data model and API schema, so a reader never translates a concept across layers.

---

## Milestone 11 — API Redesign

Redesigned the HTTP surface to best practices while there was no public contract to break (the only client is the first-party frontend, changed in the same commits). Scope: the API layer only — a contract refactor, not a rewrite of screening logic. Step one was an audit of ~21 endpoints, not edits.

Decisions locked (2026-06-26):
- **camelCase everywhere on the wire**, enforced by direction-split Pydantic alias bases in `app/schemas/base.py`: `ResponseModel` (emits camelCase), `RequestModel` (accepts only camelCase), `BridgeModel` (accepts both — the deliberate `AppSettings` exception). Domain dataclasses and storage schemas stay pure; casing lives only in boundary `*Out` models.
- **RFC 9457 problem+json for every error** — one machine-readable shape replacing ad-hoc `{detail: "string"}`. A single `Problem` exception + code→(status, title) registry in `app/api/problems.py`; the frontend branches on `code`.
- **Rename `/screening` → `/ranking`** — the router is the ranking subsystem and the UI calls it "Rank"; "screening" was actively misleading. `/screening/rank/run` → `/ranking/run`. The `/quality-flags` → `/screening` two-way rename was deferred to M12 (renaming the model frees the word with no collision). `/sync` deliberately kept — it is an idempotent upsert-by-email reconcile, and the codebase speaks sync throughout.

Sequenced before observability (M13) so instrumentation and a second actor (M15) build on a clean surface; the DB refactor (M12) lands in between.

---

## Milestone 10 — Committee-Ready Report

Shipped as browser print-to-PDF of the ranked view, replacing the originally-planned Google Docs generation. This removed the need for Docs/Drive write scopes — the app's only Google scopes are login + Sheets read-only.

---

## Milestone 9 — Interactive Weighting (Tier List)

The M8 equal-weight ranking was validated against the real pool and judged not good enough. M9 lets the committee say what matters and re-sorts instantly as deterministic math over cached `DimensionScore`s — no model call.

- **The interface is a tier-list maker, not sequential pairwise questions.** The committee drags dimensions into self-defined importance tiers (from 2 tiers to a strict stack rank) plus an **Ignore** zone (weight 0). This replaced the SPEC's original "what matters more — X or Y?" framing: direct beats indirect for a committee with opinions, and always-editable controls remove the lock-in that pairwise redundancy guarded against (so the anti-lock-in machinery and constraint-solver were unnecessary).
- **Tier layout is source of truth; weights are derived.** `weights_from_tiers` recomputes `criteria.weights` from the layout (non-ignore tiers get descending weight by position; Ignore = 0). Every weight traces to a tier position. The ranking engine (`rank_candidates`, M8) is untouched.
- Default layout: Critical / Important / Minor + Ignore, everything starting in one tier (so the opening ranking equals the M8 equal-weight baseline). Deterministic and trivially reversible; undo/redo is editing the layout. `@dnd-kit` for accessible drag.

### M9 fast-follows (all complete)

**1. Tier carry-forward on re-rank** (Phases 1–5, complete). A blind-discovery + identity-match two-pass that carries the committee's tier placements across a re-rank.
- Phase 1: `weights_from_tiers` falls back to uniform when no dimension has positive weight; `default_tier_layout` starts every dimension in Ignore.
- Phase 2: `app/ai/dimension_matching.py` returns high-bar one-to-one `{new_key → old_key}` matches; `carry_forward_layout` re-places matched dimensions and sends unmatched to Ignore. Ignore is modeled as the **absence of a placement** (`weights_from_tiers`: unplaced → weight 0), not a stored tier with an invariant.
- Phase 3: amber "New" badging for unmatched-new dimensions while in Ignore, with in-place acknowledge (per-badge ✕, "Clear all N new flags", or dragging into a tier); folded into the tiers PUT via `acknowledged_keys`. Post-Phase-3 bug fix: "New" branches on `old_key is None` (no match at all), not on whether a match landed in a working tier.
- Phase 4 (per-dimension score reuse): scores cached per-(candidate, dimension) under `dimension_scoring:<dimension_key>`; matched dimensions **adopt the prior key** (`adopt_matched_keys`), so cache + tier placement carry forward by key alone with no parallel lineage id. Batched scoring (one call per candidate scores all uncached dimensions); the thread-pool core extracted into `run_in_pool`. The whole-set `dims_hash` design was deleted.
- Phase 5 (estimator): the pre-run Rank estimate prices scoring as a whole-pool ceiling (it runs before discovery, so it can't know carry-forward savings); the match-pass cost folds into the combined estimate and single cap check only when a prior run exists.
- **Matching scope: all-history, not last-run (decided 2026-07-08).** `all_known_dimensions(db)` matches fresh discovery against every dimension ever discovered (one entry per key, latest definition), fixing runaway key growth (67 distinct keys for a ~20-25-concept pool) and stale-score cache collisions. "New" now means never-seen-in-any-run. Chosen over scoping the score cache to the match verdict because it also fixes the root cause and improves caching.
- **Post-score consolidation** (built + verified live 2026-07-11): a Pearson-nominate / LLM-confirm cleanup pass after scoring. Pearson correlation (default r ≥ 0.8) nominates near-duplicate score vectors; one cheap LLM call adjudicates by definitions — merge only on confirmed same-concept. Merge = alias the losing (newer) key to the winner; the alias is durable and feeds the match pass so future re-mints are adopted. Verified: 1 real merge, 5 correct keeps (including a 0.94 confound held apart), 0 over-merges. Consolidation stays a definition-based identity merge — it does NOT auto-deactivate on correlation (decided 2026-07-12), separating identity duplication (safe to merge) from mere correlation.

**2. Add-a-dimension mid-tiering** — done, realized by the Committee-Proposed Criteria feature: a proposed axis runs through discovery, gets a fresh key, and is the only uncached dimension, so scoring sends just that one dimension per candidate.
- **Committee-Proposed Criteria (propose):** free text a member writes, persisted on `criteria.proposed_dimensions`, fed to the next Rank's discovery as "strongly consider, but you decide," then cleared. Complementary to (not redundant with) automatic reconcile. Every dimension created from a request is flagged `from_committee_request` (provenance surviving renames/splits).
- **Favourite → "kept" (superseded 2026-07-17):** an earlier ★ "favourite" seed was slated for removal (2026-07-09), reversed and kept (2026-07-10) when reconcile was deleted, then **superseded** — favourite collapses into tier membership. New rule: a dimension in ANY working (non-Ignore) tier is KEPT; Ignore is the only "fair game to drop" bucket. `kept_keys(run)` derives the kept set from working tiers; the ★ UI, `favourited_keys`, and cross-run auto-keep union were all removed. Merge transfers the dropped twin's tier placement to the survivor.

**3. Surface weak spots in the ranked list** — done (pure presentation, no AI). Fixed two defects: a **label bug** (rows showed dimension *confidence* colored high→green, not the *score*) and a **selection bug** (rows chose dimensions by `weight × score`, which structurally only picks strengths). The fix: **`impact = weight × (score − pool_mean)`**, the exact per-dimension decomposition of `fit_i − avg_fit`. Contributions are selected/ordered by `abs(impact)` — sign carries direction, magnitude carries importance, the score band's color says strength-vs-weakness. Computed once in `app/domain/ranking.py`; the candidate detail page shares the same contribution objects via `app/services/ranking_view.py` and drops weight-0 dimensions.

**4. AI Criteria Coach** — deferred until the tier-list has been used against real data. Not a propose-the-tiering tool; its role is to help the committee understand and challenge the weighting they built.

### Fan-Out Redesign (complete — all phases built + committed)
The "first multi-agent workflow" the project parked, justified by evidence rather than proposed on spec. Replaced the sequential match-then-reconcile accumulation that never converged.
- **The decision and evidence:** a locked-pool convergence experiment (n=10) proved re-running the Rank chain to accumulate the "fullest set" does not usefully converge — discovery re-carves the same concepts at different granularities and the sequential machinery hoards every carving, because reconcile's per-axis variance test is near-unfalsifiable. Coverage/redundancy can only be answered with all carvings visible at once — hence fan-out.
- **The shape:** K parallel discovery calls (no scoring) → one decomposition step that sees all K reports and settles the finest non-overlapping set → score once against the settled set.
- **Cost model corrected from the real ledger:** per-(dim × candidate) score = $0.00087, discovery ≈ $0.17, settled-set scoring ≈ $0.52. Discovery is the bigger, uncached half, so K carries real linear cost → K stays small (default started at 4, raised to 5 on 2026-07-10).
- **Phase 1** (2026-07-09): the overlap judge `scripts/dimension_overlap.py` — pairwise Pearson correlation over cached score vectors. Validation caught a hand-diagnosis error: the three participation-commitment slices are behaviorally distinct (r=0.20), so collapsing them would have been an over-merge — the metric's highest value is as an over-merge guardrail. Default threshold r ≥ 0.8.
- **Phase 2** (2026-07-09): `discover_patterns_fanout` runs K calls in parallel via `run_in_pool`; new `AISettings.discovery_fan_out` (default 4). The dead single-call `discover_patterns` was removed (K=1 IS the single call, per D1).
- **Phase 3 — the bake-off** (2026-07-09): both D7 contenders run 3× on the historical fixture and scored by the Phase-1 judge. **Verdict: the single-call baseline wins; the multi-agent loop is NOT built into the product.** The merger↔splitter loop was strictly dominated (23% costlier, no more stable, worse on overlaps) — its Splitter is a one-directional force, a structural thumb on the scale toward under-merging. "Right-size the solution / don't buy multi-agent we didn't earn," decided by measurement.
- **Coverage gate** (`scripts/coverage_gate.py`): measured +36% real-differentiator territory (K-union 25 vs. single-run mean 18.4), padding excluded — confirming K fresh contexts buy real coverage. The completeness-critic fallback was NOT needed.
- **Phase 4** (all done): 4a wired `decompose_dimensions` into the chain (`read_timeout` raised to 600 for the heavy call); discovery timeout + partial-failure tolerance added 2026-07-16 (a failed fan-out worker is collected into `failed_count`; only all-K-failing is fatal; a degraded run surfaces a `WarningEvent`). 4b enforced D9 (committee-request protection) via the deterministic `enforce_committee_requests` backstop + tests. 4c (`0d52b7d`) deleted `dimension_reconcile.py`, its wiring, the reconcile estimate/audit/panel, and the losing bake-off machinery (`decompose_dimensions_loop`, `_split_back`, the Splitter prompts, `OverMergeReport`, `scripts/exp_decompose_bakeoff.py`); net −1190/+69 for the sweep. **Kept:** the overlap judge and the "Revived" badge (presence-derived, NOT part of reconcile).

---

## Milestone 8 — Deterministic Ranked List

Turned the M7 per-candidate scores into a ranked shortlist with **no new model calls** — pure deterministic math over cached `DimensionScore`s, which is what makes the M9 interactions instant, free, and reproducible.

- **Equal-weight baseline:** weights seeded uniform at run creation; fit is the weight-normalized average `Σ(weight·score) / Σ(weight)`. The AI never proposes importance.
- **Confidence is surfaced, not discounted** — shown next to the score but never folded into the fit number (confidence-weighting was considered and rejected: it hides a term).
- **Qualitative labels are relative bands** (Strong fit / Promising / Mixed / Limited) by rank percentile within the pool, not absolute cutoffs.
- **Ranking is a pure domain function** in `app/domain/ranking.py` — no DB or provider access, trivially unit-testable.
- **No fixed shortlist line** — an earlier configurable "shortlist line" with a live above-line count was removed as unhelpful (`criteria.shortlist_size`, the `/screening/shortlist-line` endpoint, and the `above_line` flag all removed). The list is stack-ranked; the committee reads top-down.
- Surfaced as a separate ranked view, not an in-place re-sort of the eligible table.

---

## Milestone 7 — Pattern Discovery And Dimension Scoring

The read-only AI foundation for ranking: discovers how this pool varies and scores each candidate on those axes, but does not yet rank, weight, or ask questions.

- **The defining decision:** the LLM extracts scored features; ranking is deterministic math on top. The model scores each candidate on discovered dimensions and never opines on importance. M8 starts every dimension at equal weight (an honest "no judgment yet" baseline); M9 is the only place weights diverge. Re-ranking the pool with the LLM on every answer was rejected (~300× the cost, slow, nondeterministic).
- **Two passes:** the **Pattern Finder** (pool-level, one synthesis-model call) discovers the differentiating dimensions for this specific pool — name, definition, why-it-differentiates — and proposes no weighting; **Dimension Scoring** (per-candidate fan-out, first-pass model) scores each candidate per dimension with rationale, evidence, and a confidence label. No call-level narrative (decided 2026-07-11) — the per-dimension rationale + evidence IS the observability.
- **Dimensions oriented so MORE is better fit (decided 2026-06-28):** direction is baked in at discovery, not left implicit; there is no per-dimension direction flag (an earlier `more/less/undecided` enum + sign-aware ranking was designed and reverted). "Goldilocks" axes reframe to a monotonic concept or split into two more-is-better dimensions. Empirically, the two-dimension split fires reliably only when the two forces are independently measured; a single-variable soft trait is (correctly) absorbed into a nearby measured axis.
- **Cache key includes dimension identity**, and `prompt_version` is derived by hashing each pass's static prompt text (a prompt edit invalidates that pass's cache automatically).
- **Inputs: essays and structured facts** via a shared `applicant_facts` view so the two passes never drift. Excluded: identifiers and real-estate ownership (a hard filter). Fields that are hard filters but still vary (income within band, household size, pets) are framed for residual variation only.
- **Dimension count is a guided range (5–25), not a fixed number**, biased to split; empirically ~14–16.
- **The whole Rank chain is gated on a pool fingerprint** — a hash of the sorted `raw_row_hash`es of the eligible pool. If unchanged, re-ranking is blocked (`/rank/run` → 409; estimate returns `ranking_current: true`). This supersedes the earlier "re-running always produces a fresh run" behavior — the pool must actually change to re-rank.
- **Surfacing UX:** the workflow is an ordered gated strip — **Import → Screen → Rank** — where Rank is one button running the whole essays → criteria → scores chain under one combined cost estimate (standalone per-pass endpoints removed). Steps go amber-stale by the same signal their no-op gate uses (Import on settings fingerprint, Screen on coverage, Rank on pool fingerprint). Rank streams phase-aware progress; the criteria phase streams the model's live reasoning as a "thinking" panel. A completed Rank lands the user directly in the ranked view. Every AI step opens a confirmation card before running, even when there's nothing to do.

---

## Milestone 6 — Essay Analysis (REMOVED)

**This pass no longer exists.** M6 added a per-candidate essay-analysis pass that extracted and normalized what applicants said (a neutral summary + structured per-signal fields mirroring the four essay questions), without judging. It was deleted after measurement showed its digest inflated tokens ~172% over the raw essays while buying no discovery coverage; discovery and scoring now read the raw essays directly (see `pool_digest.py`). The design record is retained in the SPEC for history.

- Key decisions while it lived: schema fixed (not adhoc), no `other`/catch-all field, first-pass model (Haiku), eligible applications only, status-independent, surfaced as a collapsed accordion below the raw essays, and no reasoning narrative (an A/B run showed the preamble produced no systematic change while costing ~18% more output tokens).
- Commits: added in `83edb35`; narrative dropped in `a860c64`; `evidence` field dropped in `2fa3906`; pass removed in `4e520ab`.

---

## Foundation (Milestones 1–5)

- **M1–4:** project scaffold + Google OAuth + SQLite schema; read-only Google Sheets import/sync + dashboard; deterministic hard filters + configurable rules engine + filtered-out view; application tables, candidate detail pages, and searchable/sortable views.
- **M5 — AI screening flags,** which also delivered the shared AI foundation originally listed under M6: the provider-agnostic interface (Strands + Amazon Bedrock, with a deterministic mock for tests), cached per-application analysis keyed on content hash + model + prompt version, a token pricing table, cost estimate, per-run spending cap, and raw-debug access via the candidate detail page. The **status model** was reworked here: `status` (eligible/ineligible) with a `status_source` (untouched/rules/ai/human), sticky human override, and a staleness signal when machine findings change after review.
