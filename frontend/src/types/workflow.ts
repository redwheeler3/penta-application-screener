import type { AppStatus, StatusSource } from "./applications";

// A notification toast. Success toasts auto-dismiss; error toasts persist until
// dismissed (and offer a copy button), so a failure can't scroll away unread.
// An optional recovery button on a toast (e.g. "Reload" on the stale-ranking notice).
// Clicking it runs onClick, then the toast dismisses itself.
export type ToastAction = { label: string; onClick: () => void };
export type Toast = {
  id: number;
  message: string;
  variant: "success" | "error" | "warning";
  action?: ToastAction;
};

export type ScreeningEstimateResponse = {
  total: number;
  toAnalyze: number;
  cached: number;
  estimatedUsd: number;
  capUsd: number;
  withinCap: boolean;
};

// Combined cost projection for the Rank chain, from GET /ranking/run/estimate.
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
export type AppFilter = {
  status?: AppStatus;
  statusSource?: StatusSource;
  savedView?: "favourites" | "shortlist";
};

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

type PhaseEvent = { type: "phase"; phase: string; total: number | null };
type ProgressEvent = { type: "progress"; phase: string; processed: number; total: number };
export type ThinkingEvent = { type: "thinking"; phase: string; text: string };
type StageEvent = { type: "stage"; phase: string; stage: CriteriaStage };
type NoticeEvent = {
  type: "notice";
  phase: string;
  dimensions: number;
  carriedForward: number;
  newDimensions: number;
};
type WarningEvent = { type: "warning"; phase: string; message: string };
type ItemErrorEvent = {
  type: "item_error";
  phase: string;
  message: string;
  applicationId: number | null;
};
export type ErrorEvent = { type: "error"; phase: string; message: string };
export type PingEvent = { type: "ping"; phase: string };

export type ScreeningStreamEvent =
  | PhaseEvent
  | ProgressEvent
  | ItemErrorEvent
  | ErrorEvent
  | PingEvent
  | {
      type: "summary";
      analyzed: number;
      cached: number;
      flagged: number;
      failed: number;
      totalCostUsd: number;
    };
export type RankingStreamEvent =
  | PhaseEvent
  | ProgressEvent
  | ThinkingEvent
  | StageEvent
  | NoticeEvent
  | WarningEvent
  | ItemErrorEvent
  | ErrorEvent
  | PingEvent
  | {
      type: "summary";
      dimensions: number;
      scored: number;
      failed: number;
      totalCostUsd: number;
    };
