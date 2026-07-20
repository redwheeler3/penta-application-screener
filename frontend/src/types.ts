// Shared types for the screener UI. Most mirror a backend schema; the comment on
// each says which and any non-obvious semantics (null vs [] etc.).

export type CurrentUser = {
  id: number;
  email: string;
  displayName: string;
  avatarUrl: string | null;
  role: "admin" | "member";
};

// Mirrors backend AISettings. The UI edits spendingCapUsd and discoveryFanOut; the
// rest are round-tripped so a save never resets them.
export type AISettings = {
  region: string;
  screeningModel: string;
  dimensionScoringModel: string;
  discoveryModel: string;
  decomposeModel: string;
  matchModel: string;
  consolidateModel: string;
  // Fan-out width: parallel discovery calls per Rank (SPEC "Fan-Out Redesign", D6).
  discoveryFanOut: number;
  // Pearson r at/above which post-score consolidation nominates a duplicate pair (0–1).
  consolidateCorrelationThreshold: number;
  spendingCapUsd: number;
  maxWorkers: number;
};

export type AppSettings = {
  googleSheetId: string;
  incomeMin: number;
  incomeMax: number;
  minAdultAge: number;
  maxChildAge: number;
  minChildren: number;
  maxChildren: number;
  maxDogs: number;
  maxCats: number;
  allowOtherPets: boolean;
  disabledRules: string[];
  ai: AISettings;
};

export type SettingsResponse = {
  settings: AppSettings;
  googleSheetUrl: string;
  googleSheetTitle: string | null;
};

export type AppStatus = "eligible" | "ineligible";
export type StatusSource = "untouched" | "rules" | "ai" | "human";

// Counts keyed by the real columns; named views are composed client-side.
export type DashboardCounts = {
  submitted: number;
  status: Record<AppStatus, number>;
  source: Record<StatusSource, number>;
};

// Which screening steps have run (persisted), so workflow gating survives a reload.
export type WorkflowState = {
  synced: boolean;
  // Whether the latest import used the settings as they are now. False flags the
  // Import step amber: a re-import would reclassify eligibility.
  importCurrent: boolean;
  screened: boolean;
  patternsDiscovered: boolean;
  candidatesScored: boolean;
  // Same truth the Rank no-op gate uses; the "needs re-run" badge reads this (not
  // score coverage), so a pool change still flags re-rank with full coverage.
  rankingCurrent: boolean;
};

// Per-AI-step coverage of the current scope. cached < inScope means results went
// stale, so the UI warns instead of a misleading done-check. Keys are absent for
// steps not yet computable (e.g. scoring before patterns exist).
export type Coverage = Partial<
  Record<"screened" | "candidatesScored", { cached: number; inScope: number }>
>;

// Faceted counts: each facet reflects the other group's active filter, so the two
// filter groups stay consistent.
export type AppFacets = {
  status: Record<AppStatus, number>;
  source: Record<StatusSource, number>;
};

export type ApplicationSummary = {
  id: number;
  primaryEmail: string;
  applicantName: string | null;
  coApplicantName: string | null;
  status: AppStatus;
  statusSource: StatusSource;
  // True when machine findings changed since a human last reviewed.
  stale: boolean;
  hardFilterReasons: Array<{ code: string; message: string; details: Record<string, unknown> }>;
  childCount: number | null;
  householdIncome: number | null;
  // null = AI screening pass not run; int = flag count (0 = ran clean).
  flagCount: number | null;
  // Distinct flag categories from the latest pass (null if not run).
  flagCategories: string[] | null;
  createdAt: string | null;
};

export type Essay = {
  label: string;
  question: string;
  answer: string;
};

export type ScreeningFlag = {
  category: string;
  summary: string;
  evidence: string;
};

export type AIResultTrace = {
  modelId: string;
  promptVersion: string;
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
};

export type DimensionScoringTrace = {
  dimensionCount: number;
  modelIds: string[];
  promptVersions: string[];
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
};

export type ApplicationDetail = ApplicationSummary & {
  // What the machine would decide from the current findings — i.e. the result of
  // clearing a human override. Lets the status control show the automatic verdict.
  autoStatus: AppStatus;
  autoStatusSource: StatusSource;
  normalized: Record<string, unknown>;
  essays: Essay[];
  // null = screening pass not yet run for this application; [] = ran, clean.
  flags: ScreeningFlag[] | null;
  rawRow?: Record<string, unknown>;
  // The model's free-text reasoning from the latest screening pass.
  aiNarrative?: string | null;
  // Provenance for the latest screening result and current dimension score results.
  // Costs describe original generation allocations; results may be reused from cache.
  screeningTrace?: AIResultTrace | null;
  // This candidate's scores against the current run's dimensions, by |impact|
  // descending — the same ranking contributions the ranked-list row slices. null =
  // no run, or not scored under it.
  dimensionScores?: DimensionContribution[] | null;
  dimensionScoringTrace?: DimensionScoringTrace | null;
  // Private to the signed-in committee member; never included in AI inputs.
  privateNote: string;
};

// GET /ranking/insights/cost — aggregated AI spend for the Insights tab (M13).
export type CostPass = {
  passLabel: string;
  // Uncached result units; dimension scoring counts per-dimension rows.
  calls: number;
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
  // cacheable false → this pass always calls fresh (pattern discovery, dimension
  // matching); the UI shows "—" for its savings, never $0. cachedCount/cachedSavedUsd
  // are summed from the run-cost ledger.
  cacheable: boolean;
  cachedCount: number;
  cachedSavedUsd: number;
};

// The passes triggered by one user-facing run (Screen or Rank), with subtotals.
export type CostGroup = {
  runLabel: string;
  passes: CostPass[];
  subtotalUsd: number;
  subtotalSavedUsd: number;
};

export type CostReport = {
  // Cumulative AI spend across all runs, grouped by the run that triggers each pass
  // (Screen vs Rank). Spend is exact; savings come from the ledger (runs since it
  // began). Unrelated to the spending cap (which bounds each single run).
  groups: CostGroup[];
  totalCostUsd: number;
  totalSavedUsd: number;
};

// One pass within a single completed run (GET /ranking/insights/last-runs).
// cachedSavedUsd = reused results' original cost — an estimate of what caching saved.
export type LastRunPass = {
  label: string;
  freshUsd: number;
  // Uncached result units; dimension scoring counts per-dimension rows.
  freshCalls: number;
  inputTokens: number;
  outputTokens: number;
  cachedCount: number;
  cachedSavedUsd: number;
  cacheable: boolean;
};

export type LastRunCost = {
  kind: string; // "screen" | "rank" | "rank_scores"
  at: string; // ISO timestamp
  freshUsd: number;
  cachedSavedUsd: number;
  estimatedUsd: number; // pre-run projection; 0 on runs recorded before capture (show "—")
  passes: LastRunPass[];
};

// GET /ranking/insights/metrics — operational trends across all runs (M13 Pillar 3).
// One point per completed run, oldest→newest.
export type TrendPoint = {
  at: string;
  kind: string; // "screen" | "rank" | "rank_scores"
  costUsd: number;
  inputTokens: number;
  outputTokens: number;
  durationMs: number;
  failedCalls: number;
  cacheHitRate: number | null; // over cacheable units; null when none
  dimensions: number | null; // live dimension count (full rank only)
};

export type PassTrendPoint = {
  at: string;
  label: string;
  costUsd: number;
  inputTokens: number;
  outputTokens: number;
  durationMs: number;
  failedCalls: number;
};

export type MetricsReport = {
  runs: TrendPoint[];
  passes: PassTrendPoint[];
};

// The most recent Screen, full Rank, and score-current update, each with fresh spend +
// cache savings. A run is null if that type has not completed since ledgering began.
export type LastRunsReport = {
  screen: LastRunCost | null;
  rank: LastRunCost | null;
  rankScores: LastRunCost | null;
};

// The current run's discovered dimensions, from GET /ranking/current.
export type PoolDimension = {
  key: string;
  name: string;
  definition: string;
  highEnd: string;
  lowEnd: string;
  whyItDifferentiates: string;
};

// --- Ranking: the deterministic ranked shortlist from GET /ranking,
// pure math over the cached scores. Mirrors the backend ranking dataclasses.

// How one dimension fed a candidate's fit. `impact` = weight × (score − pool mean):
// magnitude ranks "what mattered", sign gives direction.
export type DimensionContribution = {
  dimensionKey: string;
  name: string;
  score: number;
  weight: number;
  impact: number;
  confidence: "low" | "medium" | "high";
  rationale: string;
  evidence: string;
};

export type RankedCandidate = {
  applicationId: number;
  name: string | null;
  rank: number; // 1-based position
  fit: number; // -1..+1 weighted average — supporting detail, not the headline
  band: string; // relative pool-position label (Strong fit … Limited)
  contributions: DimensionContribution[];
};

export type RankingResponse = {
  runId: number;
  weights: Record<string, number>;
  scoredCount: number;
  candidates: RankedCandidate[];
  // Unacknowledged flagged dimensions (new OR revived), recomputed on every tier save
  // so badges clear in the same round-trip.
  newDimensionKeys: string[];
  // Subset of newDimensionKeys that are "revived" (seen in an earlier run, dropped,
  // now back) — the UI badges these blue vs. amber "new". new = flagged − revived.
  revivedDimensionKeys: string[];
  // Kept axes: every dimension in a working (non-Ignore) tier — guaranteed to survive
  // the next Rank. Derived from tier placement. Echoed so the tier list stays in sync.
  keptKeys: string[];
  proposedDimensions: string[];
};

// One importance tier. Same tier → equal weight; higher tiers weigh more; Ignore
// weighs 0. The backend stores only working tiers and synthesizes the Ignore zone
// for display (the one with `ignore: true`), so the flag is optional here.
export type Tier = {
  id: string;
  label: string;
  dimensionKeys: string[];
  ignore?: boolean;
};

export type CurrentRunResponse = {
  runId: number;
  name: string;
  status: string;
  dimensions: PoolDimension[];
  // The model's streamed reasoning from the discovery pass (markdown), shown on the
  // Insights tab. Null for runs from before it was captured.
  discoveryNarrative: string | null;
  // Flagged dimensions (new OR revived) absent from the immediately-prior run — they
  // are badged until the committee triages them. Empty on a first run.
  newDimensionKeys: string[];
  // Subset of newDimensionKeys that are "revived" (seen in an earlier run, dropped,
  // now back) — badged blue vs. amber "new". new = flagged − revived.
  revivedDimensionKeys: string[];
  // Kept axes: every dimension in a working (non-Ignore) tier — guaranteed to survive
  // the next Rank (derived from tier placement). Plus pending free-text proposals fed
  // to the next Rank then consumed.
  keptKeys: string[];
  proposedDimensions: string[];
};

// GET /ranking/current/match-audit — the carry-forward trace for the current run
// (M13 per-run AI legibility). What discovery ACTUALLY emitted before matched keys
// were rewritten, how the match pass mapped it onto prior dimensions, and the
// derived carry-forward rate. Null when no run exists or the run predates capture.
export type MatchAuditResponse = {
  runId: number;
  rawDiscoveryDimensions: { key: string; name: string; fromCommitteeRequest: boolean }[];
  // new dimension key → the prior dimension it adopted (key + prior user-facing name;
  // name is null for audits written before the prior-names capture).
  newToOld: Record<string, { key: string; name: string | null }>;
  matchNarrative: string | null;
  priorDimensionCount: number;
  discoveredCount: number;
  matchedCount: number;
  newCount: number;
  // Fraction matched onto a prior dimension. Null on a first run (undefined, not 0);
  // a persistently near-1.0 rate on re-runs is the over-matching smell.
  carryForwardRate: number | null;
};

// GET /ranking/current/decompose-audit — how the K fan-out discovery reports were
// settled into one non-overlapping dimension set for the current run. Null on runs
// that predate the fan-out redesign (single-discovery runs).
export type DecomposeAuditResponse = {
  runId: number;
  inputReportCount: number;
  inputDimensionCount: number;
  settledCount: number;
  mergeCount: number;
  // Each settled axis: its key/name, the input axes it absorbed (sourceKeys — one =
  // kept as-is, several = a merge), the committee-request flag, and the model's
  // decision reasoning (why merged / kept distinct).
  settled: {
    key: string;
    name: string;
    sourceKeys: string[];
    // source key → discovery report indices that coined it (e.g. {trade_skills: [0, 3]}),
    // so the UI can label a source "trade_skills (R0, R3)". Empty if fan-out uncaptured.
    sourceReportMap: Record<string, number[]>;
    // source key → its user-facing name, so a source shows as name + key (like Matching).
    // Empty if fan-out uncaptured; the UI then falls back to the bare source key.
    sourceNames: Record<string, string>;
    fromCommitteeRequest: boolean;
    decision: string;
  }[];
  // D9: committee-requested axes decomposition folded INTO another axis
  // (requestKey → intoKey), surfaced so a fold is visible, never silent.
  foldedRequests: { requestKey: string; intoKey: string }[];
  // The decomposition pass's free-text reasoning (markdown). Null if none surfaced.
  narrative: string | null;
};

// GET /ranking/current/consolidate-audit — the post-score duplicate-merge pass:
// score-vector correlation nominates suspected-duplicate pairs, a confirm call merges
// genuine ones (older key kept, newer aliased). Null on runs that predate the pass.
export type ConsolidateAuditResponse = {
  runId: number;
  // Applied merges: dropped (newer) key → kept (older canonical) key.
  merges: Record<string, string>;
  // Every nominated pair: keep/drop keys + their user-facing names (snapshotted at
  // consolidation time — a merged drop key leaves the report, so its name can't be
  // resolved later; empty when the key predates name capture), the correlation r that
  // flagged it, whether it merged, and the confirm call's reason.
  pairs: {
    keep: string;
    drop: string;
    keepName: string;
    dropName: string;
    r: number;
    merged: boolean;
    reason: string;
  }[];
  nominatedCount: number;
  mergedCount: number;
  // The confirm call's free-text reasoning (markdown). Null if none surfaced.
  narrative: string | null;
};

// GET /ranking/current/fan-out-audit — the K parallel discoverers that fed
// decomposition. Each pass is one fresh-context discovery: the dimensions it found +
// its own reasoning. Null on runs that predate the fan-out redesign.
export type FanOutAuditResponse = {
  runId: number;
  k: number;
  passes: {
    dimensions: { key: string; name: string; definition: string; whyItDifferentiates: string }[];
    narrative: string | null;
  }[];
};

// A notification toast. Success toasts auto-dismiss; error toasts persist until
// dismissed (and offer a copy button), so a failure can't scroll away unread.
export type Toast = { id: number; message: string; variant: "success" | "error" | "warning" };

export type ScreeningEstimateResponse = {
  total: number;
  toAnalyze: number;
  cached: number;
  estimatedUsd: number;
  capUsd: number;
  withinCap: boolean;
};

// Combined cost projection for the Rank chain, from GET /ranking/estimate.
// `approximate` is always true: scoring is priced as a whole-pool ceiling.
export type RankEstimateResponse = {
  eligible: number;
  // K parallel discovery calls per Rank (the fan-out width), for the confirm-card copy.
  fanOut: number;
  breakdown: {
    // K parallel discoveries + the decomposition that settles them into one set.
    criteriaUsd: number;
    // The dimension identity-match call; 0 on a first run (pass skipped).
    matchUsd: number;
    scoringUsd: number;
  };
  estimatedUsd: number;
  approximate: boolean;
  capUsd: number;
  withinCap: boolean;
  // True when the pool is unchanged — ranking is already current. Re-running is
  // still allowed (discovery is non-deterministic), but the UI flags it.
  rankingCurrent: boolean;
};

export type ScoreCurrentEstimateResponse = {
  eligible: number;
  toAnalyze: number;
  cached: number;
  dimensions: number;
  estimatedUsd: number;
  capUsd: number;
  withinCap: boolean;
};

export type SortKey = "applicant" | "co_applicant" | "children" | "income" | "status";
export type SortState = { key: SortKey; direction: "asc" | "desc" } | null;

// The filter that the applications list / facets are keyed on.
export type AppFilter = { status?: AppStatus; statusSource?: StatusSource };

// Live progress emitted by the streaming Rank chain. `stage` is the current sub-step
// within the criteria phase (discovery → decompose → match), set by "stage" events so
// the UI can name which opaque step is running; null in phases without sub-steps.
export type CriteriaStage = "discovering" | "settling" | "matching";
export type RankProgress = {
  phase: "criteria" | "scores" | "consolidate";
  processed: number;
  total: number;
  stage?: CriteriaStage | null;
};

// --- Evals tab (in-UI eval cockpit) -----------------------------------------
// Mirrors backend/app/schemas/evals.py. The catalog is free; runs stream NDJSON
// (thinking lines then a summary carrying one of the result shapes below).
export type EvalKey =
  | "invariants" | "scoring" | "scoring_stability"
  | "consolidation" | "consolidation_stability"
  | "matching" | "matching_stability"
  | "decomposition" | "decomposition_stability"
  | "screening" | "screening_stability"
  | "judge" | "stability";

export type EvalDescriptor = {
  key: EvalKey;
  label: string;
  description: string;
  spends: boolean;
  estimatedCalls: number;
};

// One restored run (GET /evals/last-run): the newest persisted run for a single eval key.
// `result` is the same shape the streaming summary carries for that evalKey; no thinking
// narration is restored.
export type LastEvalRun = {
  evalKey: EvalKey;
  ranAt: string;
  promptVersion: string;
  currentPromptVersion: string;
  stale: boolean;
  result: any;
};

export type InvariantOut = { check: string; description: string; passed: boolean; violations: string[] };
export type InvariantsResult = {
  hasFixture: boolean;
  dimensions: number;
  invariants: InvariantOut[];
};
