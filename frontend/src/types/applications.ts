import type { OpeningDetails } from "./core";
import type { DimensionContribution } from "./ranking";
import type { ReasoningEffort } from "./settings";

export type AppStatus = "eligible" | "ineligible";
export type StatusSource = "untouched" | "rules" | "ai" | "human";

// Which screening steps have run (persisted), so workflow gating survives a reload.
export type WorkflowState = {
  applicationsAvailable: boolean;
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

export type AdminActions = {
  archivedOpeningsNeedingSelection: Array<{
    openingId: number;
    unitSizeBedrooms: number;
    moveInDate: string;
  }>;
  queuedEmailCount: number;
  quotaBlockedEmailCount: number;
  recentFailedEmailCount: number;
  oldestQueuedEmailAt: string | null;
  newestQueuedEmailAt: string | null;
  lastEmailAttemptAt: string | null;
};

export type EmailDeliveryIssue = {
  id: number;
  recipientEmail: string;
  messageKind: string;
  state: "queued" | "failed";
  attemptedAt: string;
  attemptCount: number;
  errorCode: string | null;
  quotaBlocked: boolean;
};

// Faceted counts: each facet reflects the other group's active filter, so the two
// filter groups stay consistent.
export type AppFacets = {
  status: Record<AppStatus, number>;
  source: Record<StatusSource, number>;
  // Count of the member's starred applications under the other active filters.
  favourites: number;
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
  // Whether the signed-in member has starred (favourited) this applicant. Private
  // per member; a personal working aid with no effect on ranking or eligibility.
  starredByMe: boolean;
  openingIds: number[];
};

export type CommitteeOpening = OpeningDetails & {
  phase: "upcoming" | "open" | "closed" | "archived";
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
  supportsReasoningEffort: boolean;
  reasoningEffort: ReasoningEffort | null;
  promptVersion: string;
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
};

export type DimensionScoringTrace = {
  dimensionCount: number;
  models: Array<{
    modelId: string;
    supportsReasoningEffort: boolean;
    reasoningEffort: ReasoningEffort | null;
  }>;
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
  firstSubmittedAt: string | null;
  lastSubmittedAt: string | null;
  submissionVersionCount: number;
  normalized: Record<string, unknown>;
  essays: Essay[];
  // null = screening pass not yet run for this application; [] = ran, clean.
  flags: ScreeningFlag[] | null;
  // The AI-extracted pet inventory and its interpretation. Null means no extraction is stored.
  petFacts?: { dogs: number; cats: number; otherPets: string[]; reasoning: string } | null;
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
