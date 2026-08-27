// GET /observability/cost — aggregated AI spend for the Observability tab.
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

// One pass within a single completed run (GET /observability/last-runs).
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

// The kind of a recorded run in the cost ledger (backend cost_report.py: screen / the full
// discovery+rank chain / a score-only re-run against the current dimensions).
export type InsightRunKind = "screen" | "rank" | "rank_scores";

export type LastRunCost = {
  kind: InsightRunKind;
  at: string; // ISO timestamp
  freshUsd: number;
  cachedSavedUsd: number;
  estimatedUsd: number; // pre-run projection; 0 on runs recorded before capture (show "—")
  // The triggering member's email. Null on pre-Phase-4 runs or a
  // since-removed member — omit the stamp then.
  triggeredBy: string | null;
  passes: LastRunPass[];
};

// GET /observability/metrics — operational trends across all runs.
// One point per completed run, oldest→newest.
export type TrendPoint = {
  at: string;
  kind: InsightRunKind;
  costUsd: number;
  inputTokens: number;
  outputTokens: number;
  durationMs: number;
  failedCalls: number;
  cacheHitRate: number | null; // over cacheable units; null when none
  dimensions: number | null; // live dimension count (full rank only)
  triggeredBy: string | null;
};

export type EligibilityCheck = { id: string; label: string; description: string };
export type EligibilityCheckCatalog = {
  deterministic: EligibilityCheck[];
  ai: EligibilityCheck[];
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
