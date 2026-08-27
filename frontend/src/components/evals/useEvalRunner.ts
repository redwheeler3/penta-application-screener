import { useEffect, useState } from "react";

import { fetchEvalCases, fetchLastEvalRun, runEval } from "../../api/evals";
import { streamNdjson } from "../../api/client";
import type {
  EvalCaseResult,
  EvalFixtureKey,
  EvalRunMode,
  EvalRunOption,
  EvalRunResult,
  EvalStreamEvent,
  LastEvalRun,
} from "../../types";

type ModeResults = Partial<Record<EvalRunMode, EvalCaseResult>>;
type RunState = {
  running: boolean;
  thinking: string;
  result: EvalRunResult | null;
  ranMode: EvalRunMode;
  error: string | null;
};

export function useEvalRunner(options: {
  caseEvalKey: EvalFixtureKey;
  runKeys: EvalRunMode[];
  initialMode: EvalRunMode;
}) {
  const [cases, setCases] = useState<Record<string, unknown>[] | null>(null);
  const [run, setRun] = useState<RunState>({
    running: false,
    thinking: "",
    result: null,
    ranMode: options.initialMode,
    error: null,
  });
  const [caseResults, setCaseResults] = useState<Record<string, ModeResults>>({});
  const [restored, setRestored] = useState<Record<string, LastEvalRun>>({});

  function loadCases() {
    fetchEvalCases(options.caseEvalKey)
      .then((data) => setCases(data.cases))
      .catch(() => setCases([]));
  }

  useEffect(loadCases, [options.caseEvalKey]);

  const loadLastRuns = (seedResults: boolean) =>
    fetchLastEvalRun(options.runKeys).then((data) => {
      if (!data.runs.length) return;
      const byMode: Record<string, LastEvalRun> = {};
      for (const lastRun of data.runs) byMode[lastRun.evalKey as EvalRunMode] = lastRun;
      setRestored(byMode);
      if (!seedResults) return;

      const seeded: Record<string, ModeResults> = {};
      for (const lastRun of data.runs) {
        const mode = lastRun.evalKey as EvalRunMode;
        for (const result of lastRun.result.cases ?? []) {
          (seeded[result.key] ??= {})[mode] = result;
        }
      }
      setCaseResults(seeded);
      const newest = data.runs.reduce((left, right) =>
        left.ranAt >= right.ranAt ? left : right,
      );
      setRun((current) => ({
        ...current,
        result: newest.result,
        ranMode: newest.evalKey as EvalRunMode,
      }));
    });

  useEffect(() => {
    void loadLastRuns(true);
    // The keys are stable per tab; the joined value makes the dependency primitive.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options.runKeys.join(",")]);

  async function runMode(mode: EvalRunOption, caseKey?: string) {
    setRestored((current) => {
      const { [mode.evalKey]: _removed, ...remaining } = current;
      return remaining;
    });
    setRun({ running: true, thinking: "", result: null, ranMode: mode.evalKey, error: null });
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
      await streamNdjson<EvalStreamEvent>(response.body, (event) => {
        if (event.type === "thinking") {
          setRun((current) => ({ ...current, thinking: current.thinking + event.text }));
          return;
        }
        if (event.type === "error") {
          setRun((current) => ({ ...current, running: false, error: event.message }));
          return;
        }
        if (event.type !== "summary") return;

        setRun((current) => ({ ...current, running: false, result: event.result }));
        const runCases = event.result.cases ?? [];
        setCaseResults((current) => {
          const next: Record<string, ModeResults> = {};
          for (const [key, results] of Object.entries(current)) {
            next[key] = caseKey
              ? { ...results }
              : { ...results, [mode.evalKey]: undefined };
          }
          for (const result of runCases) {
            (next[result.key] ??= {})[mode.evalKey] = result;
          }
          return next;
        });
        void loadLastRuns(false);
      });
      setRun((current) => (current.running ? { ...current, running: false } : current));
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
