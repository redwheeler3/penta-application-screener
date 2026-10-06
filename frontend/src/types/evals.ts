import type { ErrorEvent, PingEvent, ThinkingEvent } from "./workflow";

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

// A run mode is any eval key except "invariants" (which isn't a spend-confirmed model run).
export type EvalRunMode = Exclude<EvalKey, "invariants">;
export type EvalRunOption = {
  evalKey: EvalRunMode;
  label: string;
  rowLabel: string;
  repetitions: number;
};

// The fixtures a RunnableEval tab can read/edit cases for (the writable golden sets + the
// judge tab, which aggregates them). A subset of EvalKey; the stability modes reuse their
// pass's fixture rather than owning one.
export type EvalFixtureKey =
  | "scoring" | "consolidation" | "matching" | "decomposition" | "screening" | "judge";

// Each mode owns its required case fields. UI outcomes carry the mode beside the payload.
type EvalCaseBase = { key: string; passName?: string; inputFingerprint?: string };

export type ScoringEvalCaseResult = EvalCaseBase & {
  passed: boolean;
  score: number | null;
  confidence: string;
  evidence: string;
  failures: string[];
};

export type CategoricalEvalCaseResult = EvalCaseBase & {
  passed: boolean;
  verdict: string;
  expected: string;
  contested: boolean;
  reason: string;
  failures: string[];
};

export type ScreeningEvalCaseResult = EvalCaseBase & {
  passed: boolean;
  categories: string[];
  fires: string[];
  absent: string[];
  contested: boolean;
  reason: string;
  failures: string[];
};

export type StabilityEvalCaseResult = EvalCaseBase & {
  marker: string;
  agreement: number;
  tally: Record<string, number>;
  runs: { outcome: string; detail: string }[];
};

export type ScoringStabilityEvalCaseResult = StabilityEvalCaseResult & {
  scoreMin: number | null;
  scoreMax: number | null;
};

export type JudgeEvalCaseResult = EvalCaseBase & {
  marker: string;
  humanLabel: string;
  judgeLabel: string;
  contested: boolean;
  detail: string;
  labelRationale: string;
};

export type EvalCaseResultByMode = {
  scoring: ScoringEvalCaseResult;
  scoring_stability: ScoringStabilityEvalCaseResult;
  consolidation: CategoricalEvalCaseResult;
  consolidation_stability: StabilityEvalCaseResult;
  matching: CategoricalEvalCaseResult;
  matching_stability: StabilityEvalCaseResult;
  decomposition: CategoricalEvalCaseResult;
  decomposition_stability: StabilityEvalCaseResult;
  screening: ScreeningEvalCaseResult;
  screening_stability: StabilityEvalCaseResult;
  judge: JudgeEvalCaseResult;
  stability: StabilityEvalCaseResult;
};

export type EvalCaseOutcome = {
  [Mode in EvalRunMode]: { mode: Mode; result: EvalCaseResultByMode[Mode] }
}[EvalRunMode];
export type EvalCaseOutcomesByMode = Partial<Record<EvalRunMode, EvalCaseOutcome>>;

// A whole run's summary (the NDJSON `summary` payload, also what LastEvalRun.result carries):
// the per-case results plus run-level aggregates. The HTTP boundary attaches the requested mode
// before results reach case renderers. `agreement` is the judge's calibration block
// (Cohen's κ + failure-recall); `model`/`scoringModel`/`judgeModel` name the model that mode used.
export type EvalRunResult<Mode extends EvalRunMode = EvalRunMode> = {
  experimentId?: string;
  promptVersion?: string;
  scoringPromptVersion?: string;
  judgePromptVersion?: string;
  reasoningEffort?: string | null;
  cases?: EvalCaseResultByMode[Mode][];
  agreement?: {
    kappa: number | null;
    failureRecall: number | null;
    failureCaught: number;
    failureTotal: number;
  } | null;
  model?: string;
  scoringModel?: string;
  judgeModel?: string;
};

// The discriminator and payload travel together for both live and saved runs.
export type EvalRunSummary = {
  [Mode in EvalRunMode]: { eval: Mode; result: EvalRunResult<Mode> }
}[EvalRunMode];

export type EvalStreamEvent =
  | ThinkingEvent
  | ErrorEvent
  | PingEvent
  | ({ type: "summary"; savedPath: string | null; storedRunId?: number | null } & EvalRunSummary);

export type JudgeBackground = { passName: string; background: string; caseCount: number };

export type EvalDescriptor = {
  key: EvalKey;
  label: string;
  description: string;
  spends: boolean;
  estimatedCalls: number;
  repetitions: number;
};

// One restored run (GET /evals/last-run): the newest persisted run for a single eval key.
// `result` is the same shape the streaming summary carries for that evalKey; no thinking
// narration is restored.
export type EvalConfiguration = {
  promptVersion: string;
  modelId: string;
  reasoningEffort: string;
  caseFingerprints: Record<string, string>;
};

export type LastEvalRun = {
  runId: number;
  ranAt: string;
  promptVersion: string;
  modelId: string;
  supportsReasoningEffort: boolean;
  reasoningEffort: string;
  caseRunIds: Record<string, number>;
} & {
  [Mode in EvalRunMode]: { evalKey: Mode; result: EvalRunResult<Mode> }
}[EvalRunMode];

export type EvalHistory = {
  runs: LastEvalRun[];
  current: Partial<Record<EvalRunMode, EvalConfiguration>>;
};

export type InvariantOut = { check: string; description: string; passed: boolean; violations: string[] };
export type InvariantsResult = {
  hasFixture: boolean;
  dimensions: number;
  invariants: InvariantOut[];
};
