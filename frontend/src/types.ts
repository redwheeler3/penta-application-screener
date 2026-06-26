// Shared types for the screener UI. Most mirror a backend schema; the comment on
// each says which and any non-obvious semantics (null vs [] etc.).

export type CurrentUser = {
  id: number;
  email: string;
  displayName: string;
  avatarUrl: string | null;
  role: "admin" | "member";
};

// Mirrors backend AISettings. The UI only edits spendingCapUsd; the rest are
// round-tripped so a save never resets them.
export type AISettings = {
  region: string;
  firstPassModel: string;
  synthesisModel: string;
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
  qualityChecksRun: boolean;
  essaysAnalyzed: boolean;
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
  Record<"qualityChecksRun" | "candidatesScored", { cached: number; inScope: number }>
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
  // null = AI quality-flag pass not run; int = flag count (0 = ran clean).
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

export type QualityFlag = {
  category: string;
  severity: "info" | "notable";
  summary: string;
  evidence: string;
};

// Neutral factual extraction across the four essays. Mirrors backend
// EssayAnalysisReport. Informational only — never affects status.
export type EssayAnalysis = {
  summary: string;
  householdContext: string | null;
  employmentBackground: string | null;
  interests: string[];
  values: string[];
  skillsOffered: string[];
  priorCoOpExperience: string | null;
  statedMotivations: string[];
  statedContributions: string[];
  evidence: string[];
};

export type ApplicationDetail = ApplicationSummary & {
  // What the machine would decide from the current findings — i.e. the result of
  // clearing a human override. Lets the status control show the automatic verdict.
  autoStatus: AppStatus;
  autoStatusSource: StatusSource;
  normalized: Record<string, unknown>;
  essays: Essay[];
  // null = quality-flag pass not yet run for this application; [] = ran, clean.
  qualityFlags: QualityFlag[] | null;
  rawRow?: Record<string, unknown>;
  // The model's free-text reasoning from the latest quality-flag pass.
  aiNarrative?: string | null;
  // null = essay-analysis pass not yet run for this application.
  essayAnalysis?: EssayAnalysis | null;
  // This candidate's scores against the current run's dimensions, by |impact|
  // descending — the same ranking contributions the ranked-list row slices. null =
  // no run, or not scored under it.
  dimensionScores?: DimensionContribution[] | null;
};

// The current run's discovered dimensions, from GET /ranking/current.
export type PoolDimension = {
  key: string;
  name: string;
  definition: string;
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
  fit: number; // 0..1 weighted average — supporting detail, not the headline
  band: string; // relative pool-position label (Strong fit … Limited)
  contributions: DimensionContribution[];
};

export type RankingState = {
  runId: number;
  weights: Record<string, number>;
  scoredCount: number;
  candidates: RankedCandidate[];
  // Unacknowledged new dimensions, recomputed on every tier save so badges clear
  // in the same round-trip.
  newDimensionKeys: string[];
  // Discovery seeds, echoed so the composer stays in sync after a tier/seed save.
  favouritedKeys: string[];
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

export type ScreeningRunState = {
  runId: number;
  name: string;
  status: string;
  summary: string;
  dimensions: PoolDimension[];
  // New dimensions with no confident match to a prior one — they start in Ignore,
  // badged "new" until the committee triages them. Empty on a first run.
  newDimensionKeys: string[];
  // Discovery seeds (see api): favourited dimension keys kept across re-runs, and
  // pending free-text proposals fed to the next Rank then consumed.
  favouritedKeys: string[];
  proposedDimensions: string[];
};

// A notification toast. Success toasts auto-dismiss; error toasts persist until
// dismissed (and offer a copy button), so a failure can't scroll away unread.
export type Toast = { id: number; message: string; variant: "success" | "error" };

export type QualityFlagEstimate = {
  total: number;
  toAnalyze: number;
  cached: number;
  estimatedUsd: number;
  capUsd: number;
  withinCap: boolean;
};

// Combined cost projection for the Rank chain, from GET /ranking/estimate.
// `approximate` is always true: scoring is priced as a whole-pool ceiling.
export type RankEstimate = {
  eligible: number;
  breakdown: {
    essaysUsd: number;
    criteriaUsd: number;
    // The dimension identity-match call; 0 on a first run (pass skipped).
    matchUsd: number;
    scoringUsd: number;
  };
  essaysCached: number;
  estimatedUsd: number;
  approximate: boolean;
  capUsd: number;
  withinCap: boolean;
  // True when the pool is unchanged — ranking is already current. Re-running is
  // still allowed (discovery is non-deterministic), but the UI flags it.
  rankingCurrent: boolean;
};

export type SortKey = "applicant" | "co_applicant" | "children" | "income" | "status";
export type SortState = { key: SortKey; direction: "asc" | "desc" } | null;

// The filter that the applications list / facets are keyed on.
export type AppFilter = { status?: AppStatus; statusSource?: StatusSource };

// Live progress emitted by the streaming Rank chain.
export type RankProgress = { phase: "essays" | "criteria" | "scores"; processed: number; total: number };
