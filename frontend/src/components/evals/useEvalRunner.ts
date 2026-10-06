import { useCommitteeApi } from "../../api/identity";
import { type SetStateAction, useEffect, useRef, useState } from "react";

import * as evalsApi from "../../api/evals";
import { caseOutcomes, evalCaseIdentity, savedRunSummary } from "../../api/evals";
import { streamNdjson } from "../../api/client";
import { useRequestScope } from "../../hooks/useRequestScope";
import type {
  EvalCaseOutcomesByMode,
  EvalCaseOutcome,
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
  const { fetchEvalCases, fetchLastEvalRun, runEval } = useCommitteeApi(evalsApi);

  const [cases, setStoredCases] = useState<Record<string, unknown>[] | null>(null);
  const caseReads = useRequestScope(options.caseEvalKey);
  const [run, setRun] = useState<RunState>({
    running: false,
    thinking: "",
    error: null,
  });
  const [caseResults, setCaseResults] = useState<Record<string, EvalCaseOutcomesByMode>>({});
  const [restored, setRestored] = useState<Record<string, LastEvalRun>>({});
  const historyKey = options.runKeys.join(",");
  const historyReads = useRequestScope(historyKey);
  const experiments = useRef<Record<string, string | undefined>>({});
  const activeRun = useRef<AbortController | null>(null);
  const runScope = useRequestScope(options.caseEvalKey);
  useEffect(() => () => { activeRun.current?.abort(); }, []);

  function loadCases() {
    const isCurrent = caseReads.begin();
    fetchEvalCases(options.caseEvalKey)
      .then((data) => { if (isCurrent()) setStoredCases(data.cases); })
      .catch(() => { if (isCurrent()) setStoredCases([]); });
  }

  function setCases(next: SetStateAction<Record<string, unknown>[] | null>) {
    caseReads.invalidate();
    setStoredCases(next);
    void loadLastRuns(true);
  }

  // The fixture key owns the read; render-local setters must not replay it on save.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(loadCases, [options.caseEvalKey]);

  async function loadLastRuns(seedResults: boolean): Promise<void> {
    if (!historyReads.isFor(historyKey)) return;
    const isCurrent = historyReads.begin();
    try {
      const data = await fetchLastEvalRun(options.runKeys);
      if (!isCurrent() || !data.runs.length) return;
      const relevant = data.runs.filter((last) => seedResults
        || experiments.current[last.evalKey] === last.result.experimentId);
      const byMode: Record<string, LastEvalRun> = {};
      for (const lastRun of relevant) byMode[lastRun.evalKey] = lastRun;
      setRestored(byMode);

      const seeded: Record<string, EvalCaseOutcomesByMode> = {};
      function matchesCurrent(last: LastEvalRun, outcome: EvalCaseOutcome): boolean {
        if (last.promptStale || last.modelStale || last.reasoningStale) return false;
        const identity = evalCaseIdentity(outcome.result.key, outcome.result.passName);
        return !last.currentCaseFingerprints
          || outcome.result.inputFingerprint === last.currentCaseFingerprints[identity];
      }
      for (const lastRun of relevant) {
        const mode = lastRun.evalKey;
        experiments.current[mode] = lastRun.result.experimentId;
        for (const outcome of caseOutcomes(savedRunSummary(lastRun))) {
          const identity = evalCaseIdentity(outcome.result.key, outcome.result.passName);
          if (!matchesCurrent(lastRun, outcome)) continue;
          (seeded[identity] ??= {})[mode] = outcome;
        }
      }
      setCaseResults((current) => {
        if (seedResults) return seeded;
        const next = Object.fromEntries(Object.entries(current).map(([key, modes]) => [key, { ...modes }]));
        for (const last of relevant) {
          for (const modes of Object.values(next)) {
            const outcome = modes[last.evalKey];
            if (outcome && !matchesCurrent(last, outcome)) delete modes[last.evalKey];
          }
        }
        // A telemetry write can fail after a summary was delivered. Preserve that
        // fresh receipt while filling other current coverage from stored history.
        for (const [key, modes] of Object.entries(seeded)) {
          next[key] = { ...modes, ...next[key] };
        }
        return next;
      });
    } catch {
      // History is optional; a failed refresh must preserve displayed run results.
    }
  }

  useEffect(() => {
    void loadLastRuns(true);
    // The keys are stable per tab; the joined value makes the dependency primitive.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [historyKey]);

  async function runMode(mode: EvalRunOption, caseKey?: string, passName?: string) {
    if (activeRun.current) return;
    const controller = new AbortController();
    activeRun.current = controller;
    const isCurrent = runScope.capture();
    historyReads.invalidate();
    setRestored((current) => {
      const { [mode.evalKey]: _removed, ...remaining } = current;
      return remaining;
    });
    setRun({ running: true, thinking: "", error: null });
    try {
      const response = await runEval(mode.evalKey, { caseKey, passName, signal: controller.signal });
      if (!isCurrent()) { controller.abort(); return; }
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
        if (!isCurrent()) return;
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
        const sameExperiment = experiments.current[event.eval] === event.result.experimentId;
        experiments.current[event.eval] = event.result.experimentId;
        setCaseResults((current) => {
          const next: Record<string, EvalCaseOutcomesByMode> = {};
          for (const [key, results] of Object.entries(current)) {
            next[key] = caseKey && sameExperiment
              ? { ...results }
              : { ...results, [event.eval]: undefined };
          }
          for (const outcome of runCases) {
            (next[evalCaseIdentity(outcome.result.key, outcome.result.passName)] ??= {})[outcome.mode] = outcome;
          }
          return next;
        });
        void loadLastRuns(false);
      });
      if (!finished && isCurrent()) {
        setRun((current) => ({
          ...current,
          running: false,
          error: "Eval progress was interrupted before completion was confirmed. " +
            "Review current results before starting another run.",
        }));
      }
    } catch (error) {
      if (isCurrent() && !controller.signal.aborted) setRun((current) => ({
        ...current,
        running: false,
        error: String(error),
      }));
    } finally {
      if (activeRun.current === controller) activeRun.current = null;
    }
  }

  return { cases, setCases, run, caseResults, restored, runMode, refreshHistory: () => loadLastRuns(true) };
}
