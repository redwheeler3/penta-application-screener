import { useEffect, useState } from "react";

import { caseOutcomes, fetchEvalCases, fetchLastEvalRun, runEval, savedRunSummary } from "../../api/evals";
import { streamNdjson } from "../../api/client";
import { useRequestScope } from "../../hooks/useRequestScope";
import type {
  EvalCaseOutcomesByMode,
  EvalFixtureKey,
  EvalRunMode,
  EvalRunOption,
  EvalStreamEvent,
  LastEvalRun,
} from "../../types";

type RunState = {
  running: boolean;
  thinking: string;
  error: string | null;
};

export function useEvalRunner(options: {
  caseEvalKey: EvalFixtureKey;
  runKeys: EvalRunMode[];
}) {
  const [cases, setCases] = useState<Record<string, unknown>[] | null>(null);
  const [run, setRun] = useState<RunState>({
    running: false,
    thinking: "",
    error: null,
  });
  const [caseResults, setCaseResults] = useState<Record<string, EvalCaseOutcomesByMode>>({});
  const [restored, setRestored] = useState<Record<string, LastEvalRun>>({});
  const historyKey = options.runKeys.join(",");
  const historyReads = useRequestScope(historyKey);

  function loadCases() {
    fetchEvalCases(options.caseEvalKey)
      .then((data) => setCases(data.cases))
      .catch(() => setCases([]));
  }

  useEffect(loadCases, [options.caseEvalKey]);

  async function loadLastRuns(seedResults: boolean): Promise<void> {
    if (!historyReads.isFor(historyKey)) return;
    const isCurrent = historyReads.begin();
    try {
      const data = await fetchLastEvalRun(options.runKeys);
      if (!isCurrent() || !data.runs.length) return;
      const byMode: Record<string, LastEvalRun> = {};
      for (const lastRun of data.runs) byMode[lastRun.evalKey] = lastRun;
      setRestored(byMode);
      if (!seedResults) return;

      const seeded: Record<string, EvalCaseOutcomesByMode> = {};
      for (const lastRun of data.runs) {
        const mode = lastRun.evalKey;
        for (const outcome of caseOutcomes(savedRunSummary(lastRun))) {
          (seeded[outcome.result.key] ??= {})[mode] = outcome;
        }
      }
      setCaseResults(seeded);
    } catch {
      // History is optional; a failed refresh must preserve displayed run results.
    }
  }

  useEffect(() => {
    void loadLastRuns(true);
    // The keys are stable per tab; the joined value makes the dependency primitive.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [historyKey]);

  async function runMode(mode: EvalRunOption, caseKey?: string) {
    historyReads.invalidate();
    setRestored((current) => {
      const { [mode.evalKey]: _removed, ...remaining } = current;
      return remaining;
    });
    setRun({ running: true, thinking: "", error: null });
    try {
      const response = await runEval(mode.evalKey, { caseKey });
      if (!response.ok || !response.body) {
        setRun((current) => ({
          ...current,
          running: false,
          error: `Request failed (${response.status})`,
        }));
        return;
      }
      let finished = false;
      await streamNdjson<EvalStreamEvent>(response.body, (event) => {
        if (event.type === "thinking") {
          setRun((current) => ({ ...current, thinking: current.thinking + event.text }));
          return;
        }
        if (event.type === "error") {
          finished = true;
          setRun((current) => ({ ...current, running: false, error: event.message }));
          return;
        }
        if (event.type !== "summary") return;

        finished = true;
        setRun((current) => ({ ...current, running: false }));
        const runCases = caseOutcomes(event);
        setCaseResults((current) => {
          const next: Record<string, EvalCaseOutcomesByMode> = {};
          for (const [key, results] of Object.entries(current)) {
            next[key] = caseKey
              ? { ...results }
              : { ...results, [event.eval]: undefined };
          }
          for (const outcome of runCases) {
            (next[outcome.result.key] ??= {})[outcome.mode] = outcome;
          }
          return next;
        });
        void loadLastRuns(false);
      });
      if (!finished) {
        setRun((current) => ({
          ...current,
          running: false,
          error: "Eval progress was interrupted before completion was confirmed. " +
            "Review current results before starting another run.",
        }));
      }
    } catch (error) {
      setRun((current) => ({
        ...current,
        running: false,
        error: String(error),
      }));
    }
  }

  return { cases, setCases, run, caseResults, restored, runMode };
}
