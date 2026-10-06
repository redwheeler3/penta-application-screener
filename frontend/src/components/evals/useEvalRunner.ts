import { useCommitteeApi } from "../../api/identity";
import { useEffect, useRef, useState } from "react";

import * as evalsApi from "../../api/evals";
import { streamNdjson } from "../../api/client";
import { useRequestScope } from "../../hooks/useRequestScope";
import { useFetchResource } from "../../hooks/useFetchResource";
import { acceptEvalHistory, acceptEvalReceipt, acknowledgeEvalCases, invalidateEvalConfiguration, displayedEvalResults, EMPTY_EVAL_RESULTS } from "./evalResultState";
import type {
  EvalFixtureKey,
  EvalCasesResponse,
  EvalRunMode,
  EvalRunOption,
  EvalStreamEvent,
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

  const fixture = useFetchResource(() => fetchEvalCases(options.caseEvalKey), { reloadKey: options.caseEvalKey });
  const [run, setRun] = useState<RunState>({
    running: false,
    thinking: "",
    error: null,
  });
  const [results, setResults] = useState(EMPTY_EVAL_RESULTS);
  const historyKey = options.runKeys.join(",");
  const historyReads = useRequestScope(historyKey);
  const activeRun = useRef<AbortController | null>(null);
  const runScope = useRequestScope(options.caseEvalKey);
  useEffect(() => () => { activeRun.current?.abort(); }, []);

  function setCases(saved: EvalCasesResponse) {
    historyReads.invalidate();
    fixture.setData(saved);
    setResults((current) => acknowledgeEvalCases(current, options.runKeys, saved.caseFingerprints));
    void loadLastRuns();
  }

  function acknowledgeBrief() {
    historyReads.invalidate();
    setResults((current) => invalidateEvalConfiguration(current, options.runKeys));
    void loadLastRuns();
  }

  async function loadLastRuns(): Promise<void> {
    if (!historyReads.isFor(historyKey)) return;
    const isCurrent = historyReads.begin();
    try {
      const data = await fetchLastEvalRun(options.runKeys);
      if (isCurrent()) setResults((current) => acceptEvalHistory(current, data));
    } catch {
      // Keep useful delivered output when optional history cannot be refreshed.
    }
  }

  useEffect(() => {
    setResults(EMPTY_EVAL_RESULTS);
    void loadLastRuns();
    // The joined mode keys define the mounted result workspace.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [historyKey]);

  async function runMode(mode: EvalRunOption, caseKey?: string, passName?: string) {
    if (activeRun.current || !runScope.isFor(options.caseEvalKey)) return;
    const controller = new AbortController();
    activeRun.current = controller;
    const isCurrent = runScope.capture();
    historyReads.invalidate();
    setRun({ running: true, thinking: "", error: null });
    try {
      const response = await runEval(mode.evalKey, { caseKey, passName, k: mode.repetitions, signal: controller.signal });
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
        setResults((current) => acceptEvalReceipt(current, event, caseKey !== undefined));
        void loadLastRuns();
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

  return { cases: fixture.data?.cases ?? null, casesLoadState: fixture.state, retryCases: fixture.reload,
    setCases, run, ...displayedEvalResults(results, fixture.data?.caseFingerprints), currentConfigurations: results.history.current,
    runMode, refreshHistory: loadLastRuns, acknowledgeBrief };
}
