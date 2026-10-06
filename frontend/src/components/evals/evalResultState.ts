import { caseOutcomes, evalCaseIdentity, savedRunSummary } from "../../api/evals";
import type { EvalCaseOutcome, EvalCaseOutcomesByMode, EvalConfiguration, EvalHistory, EvalRunMode, EvalRunSummary, LastEvalRun } from "../../types";

type Configuration = Omit<EvalConfiguration, "caseFingerprints">;
type ResultSource = {
  outcome: EvalCaseOutcome;
  configuration: Configuration;
  experimentId: string | undefined;
  runId: number | null;
};
type Delivered = Partial<Record<EvalRunMode, Record<string, ResultSource>>>;
export type EvalResultState = { history: EvalHistory; delivered: Delivered };
export const EMPTY_EVAL_RESULTS: EvalResultState = { history: { runs: [], current: {} }, delivered: {} };

function configurationOf(run: EvalRunSummary): Configuration {
  return {
    modelId: run.result.model ?? run.result.scoringModel ?? run.result.judgeModel ?? "",
    promptVersion: run.result.promptVersion ?? run.result.scoringPromptVersion ?? run.result.judgePromptVersion ?? "",
    reasoningEffort: run.result.reasoningEffort ?? "",
  };
}

export function configurationChanges(source: Configuration, current: EvalConfiguration) {
  return {
    promptStale: source.promptVersion !== current.promptVersion,
    modelStale: source.modelId !== current.modelId,
    reasoningStale: source.reasoningEffort !== current.reasoningEffort,
  };
}

function matchesCurrent(source: ResultSource, current: EvalConfiguration | undefined): boolean {
  if (!current) return false;
  const key = evalCaseIdentity(source.outcome.result.key, source.outcome.result.passName);
  return !Object.values(configurationChanges(source.configuration, current)).some(Boolean)
    && source.outcome.result.inputFingerprint !== undefined
    && source.outcome.result.inputFingerprint === current.caseFingerprints[key];
}

function storedSources(history: EvalHistory): Delivered {
  const sources: Delivered = {};
  for (const run of history.runs) {
    const cases: Record<string, ResultSource> = {};
    for (const outcome of caseOutcomes(savedRunSummary(run))) {
      const key = evalCaseIdentity(outcome.result.key, outcome.result.passName);
      cases[key] = { outcome, configuration: run, experimentId: run.result.experimentId, runId: run.caseRunIds[key] };
    }
    sources[run.evalKey] = cases;
  }
  return sources;
}

export function acceptEvalHistory(state: EvalResultState, history: EvalHistory): EvalResultState {
  const stored = storedSources(history);
  const delivered: Delivered = {};
  for (const mode of Object.keys(state.delivered) as EvalRunMode[]) {
    for (const [key, receipt] of Object.entries(state.delivered[mode]!)) {
      const current = history.current[mode];
      if (current && !matchesCurrent(receipt, current)) continue;
      const saved = stored[mode]?.[key];
      if (receipt.runId !== null && saved?.runId != null && saved.runId >= receipt.runId
        && matchesCurrent(saved, current)) continue;
      (delivered[mode] ??= {})[key] = receipt;
    }
  }
  return { history, delivered };
}

export function acceptEvalReceipt(
  state: EvalResultState, receipt: EvalRunSummary & { storedRunId?: number | null }, partial: boolean,
): EvalResultState {
  const mode = receipt.eval;
  const previous = state.delivered[mode] ?? {};
  const sameExperiment = Object.values(previous).every((source) => source.experimentId === receipt.result.experimentId);
  const cases = partial && sameExperiment ? { ...previous } : {};
  for (const outcome of caseOutcomes(receipt)) {
    cases[evalCaseIdentity(outcome.result.key, outcome.result.passName)] = {
      outcome, configuration: configurationOf(receipt), experimentId: receipt.result.experimentId,
      runId: receipt.storedRunId ?? null,
    };
  }
  return { ...state, delivered: { ...state.delivered, [mode]: cases } };
}

/** A successful edit acknowledges validation inputs even if the later history read fails. */
export function acknowledgeEvalCases(state: EvalResultState, modes: EvalRunMode[],
  caseFingerprints: Record<string, string>): EvalResultState {
  const current = { ...state.history.current };
  for (const mode of modes) {
    if (current[mode]) current[mode] = { ...current[mode], caseFingerprints };
  }
  return acceptEvalHistory(state, { ...state.history, current });
}

export function invalidateEvalConfiguration(state: EvalResultState, modes: EvalRunMode[]): EvalResultState {
  const current = { ...state.history.current };
  for (const mode of modes) delete current[mode];
  return { ...state, history: { ...state.history, current } };
}

/** Derive one displayed result per case/mode; delivered receipts never become history. */
export function displayedEvalResults(state: EvalResultState, visibleFingerprints: Record<string, string> | undefined) {
  const stored = storedSources(state.history);
  const caseResults: Record<string, EvalCaseOutcomesByMode> = {};
  const retainedResults: Record<string, EvalCaseOutcomesByMode> = {};
  const restored: Record<string, LastEvalRun> = {};
  const modes = new Set([...Object.keys(stored), ...Object.keys(state.delivered)] as EvalRunMode[]);
  for (const mode of modes) {
    const receipts = state.delivered[mode] ?? {};
    const activeExperiment = Object.values(receipts)[0]?.experimentId;
    const sources = { ...stored[mode] };
    if (Object.keys(receipts).length) {
      for (const [key, source] of Object.entries(sources)) {
        if (source.experimentId !== activeExperiment) delete sources[key];
      }
    }
    Object.assign(sources, receipts);
    for (const [key, source] of Object.entries(sources)) {
      (retainedResults[key] ??= {})[mode] = source.outcome;
      if (matchesCurrent(source, state.history.current[mode])
        && source.outcome.result.inputFingerprint === visibleFingerprints?.[key]) {
        (caseResults[key] ??= {})[mode] = source.outcome;
      }
    }
    const historical = state.history.runs.find((run) => run.evalKey === mode);
    // A historical summary cannot describe overlaid, unrecorded outcomes truthfully.
    if (historical && !Object.keys(receipts).length) restored[mode] = historical;
  }
  return { caseResults, retainedResults, restored };
}
