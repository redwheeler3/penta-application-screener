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
  calls: number;
};

// The fixtures a RunnableEval tab can read/edit cases for (the writable golden sets + the
// judge tab, which aggregates them). A subset of EvalKey; the stability modes reuse their
// pass's fixture rather than owning one.
export type EvalFixtureKey =
  | "scoring" | "consolidation" | "matching" | "decomposition" | "screening" | "judge";

// The run mode is the discriminator for case results, but it lives beside the payload rather
// than inside it. The shared optional fields let generic list/status renderers work across
// modes; the named result types below make each mode's required wire shape explicit.
type EvalCaseDisplayFields = {
  key: string;
  marker?: string;
  contested?: boolean;
  verdict?: string;
  expected?: string;
  passed?: boolean;
  score?: number;
  confidence?: string;
  evidence?: string;
  failures?: string[];
  reason?: string;
  categories?: string[];
  fires?: string[];
  absent?: string[];
  agreement?: number;
  tally?: Record<string, number>;
  scoreMin?: number;
  scoreMax?: number;
  runs?: { outcome: string; detail: string }[];
  humanLabel?: string;
  judgeLabel?: string;
  detail?: string;
  labelRationale?: string;
  passName?: string;
  majority?: string;
  flipped?: boolean;
};

export type ScoringEvalCaseResult = EvalCaseDisplayFields & {
  passed: boolean;
  score: number;
  confidence: string;
  evidence: string;
  failures: string[];
};

export type CategoricalEvalCaseResult = EvalCaseDisplayFields & {
  passed: boolean;
  verdict: string;
  expected: string;
  contested: boolean;
  reason: string;
  failures: string[];
};

export type ScreeningEvalCaseResult = EvalCaseDisplayFields & {
  passed: boolean;
  categories: string[];
  fires: string[];
  absent: string[];
  contested: boolean;
  reason: string;
  failures: string[];
};

export type StabilityEvalCaseResult = EvalCaseDisplayFields & {
  marker: string;
  agreement: number;
  tally: Record<string, number>;
  runs: { outcome: string; detail: string }[];
};

export type ScoringStabilityEvalCaseResult = StabilityEvalCaseResult & {
  scoreMin: number;
  scoreMax: number;
};

export type JudgeEvalCaseResult = EvalCaseDisplayFields & {
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

export type EvalCaseResult = EvalCaseResultByMode[EvalRunMode];

// A whole run's summary (the NDJSON `summary` payload, also what LastEvalRun.result carries):
// the per-case results plus run-level aggregates. `agreement` is the judge's calibration block
// (Cohen's κ + failure-recall); `model`/`scoringModel`/`judgeModel` name the model that mode used.
export type EvalRunResult = {
  cases?: EvalCaseResult[];
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

export type EvalStreamEvent =
  | ThinkingEvent
  | ErrorEvent
  | PingEvent
  | { type: "summary"; eval: string; savedPath: string | null; result: EvalRunResult };

export type JudgeBackground = { passName: string; background: string; caseCount: number };

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
  modelId: string;
  currentModelId: string;
  supportsReasoningEffort: boolean;
  reasoningEffort: string;
  currentReasoningEffort: string;
  promptStale: boolean;
  modelStale: boolean;
  reasoningStale: boolean;
  result: EvalRunResult;
};

export type InvariantOut = { check: string; description: string; passed: boolean; violations: string[] };
export type InvariantsResult = {
  hasFixture: boolean;
  dimensions: number;
  invariants: InvariantOut[];
};
