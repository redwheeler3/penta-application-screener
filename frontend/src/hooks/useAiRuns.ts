import { useEffect, useRef, useState } from "react";

import { streamNdjson } from "../api/client";
import {
  fetchRankEstimate,
  fetchScoreCurrentEstimate,
  runRank as startRankRequest,
  scoreCurrent as startScoreCurrentRequest,
} from "../api/ranking";
import {
  fetchScreeningEstimate,
  runScreening as startScreeningRequest,
} from "../api/screening";
import { readProblem } from "../api/problems";
import { money } from "../format";
import type {
  CurrentRunResponse,
  RankEstimateResponse,
  RankProgress,
  RankingStreamEvent,
  ScoreCurrentEstimateResponse,
  ScreeningEstimateResponse,
  ScreeningStreamEvent,
} from "../types";

type Notifications = {
  success: (message: string) => void;
  error: (message: string) => void;
  warning: (message: string) => void;
};

type RankingCoordinator = {
  currentRun: CurrentRunResponse | null;
  refreshCurrentRun: () => Promise<unknown>;
  load: () => Promise<boolean>;
  setDisplayedProposals: (proposals: string[]) => void;
};

export function useAiRuns(options: {
  openingId: number | null;
  ranking: RankingCoordinator;
  notifications: Notifications;
  refreshDashboard: () => void;
  reloadApplications: () => void;
  clearSelectedApplication: () => void;
}) {
  const [screeningEstimate, setScreeningEstimate] =
    useState<ScreeningEstimateResponse | null>(null);
  const [screeningEstimateLoading, setScreeningEstimateLoading] = useState(false);
  const [screeningRunning, setScreeningRunning] = useState(false);
  const [screeningProgress, setScreeningProgress] = useState<{
    processed: number;
    total: number;
  } | null>(null);
  const [rankEstimate, setRankEstimate] = useState<RankEstimateResponse | null>(null);
  const [rankEstimateLoading, setRankEstimateLoading] = useState(false);
  const [scoreCurrentEstimate, setScoreCurrentEstimate] =
    useState<ScoreCurrentEstimateResponse | null>(null);
  const [rankRunning, setRankRunning] = useState(false);
  const [rankProgress, setRankProgress] = useState<RankProgress | null>(null);
  const [criteriaThinking, setCriteriaThinking] = useState("");
  const screeningEstimateRequest = useRef(0);
  const rankEstimateRequest = useRef(0);
  const screeningEstimateAbort = useRef<AbortController | null>(null);
  const rankEstimateAbort = useRef<AbortController | null>(null);

  useEffect(() => () => {
    screeningEstimateAbort.current?.abort();
    rankEstimateAbort.current?.abort();
  }, []);

  function cancelScreeningEstimate() {
    screeningEstimateAbort.current?.abort();
    screeningEstimateAbort.current = null;
    screeningEstimateRequest.current += 1;
    setScreeningEstimateLoading(false);
    setScreeningEstimate(null);
  }

  function cancelRankEstimate() {
    rankEstimateAbort.current?.abort();
    rankEstimateAbort.current = null;
    rankEstimateRequest.current += 1;
    setRankEstimateLoading(false);
    setRankEstimate(null);
    setScoreCurrentEstimate(null);
  }

  function resetEstimates() {
    cancelScreeningEstimate();
    cancelRankEstimate();
  }

  async function requestScreeningEstimate() {
    if (options.openingId === null) return;
    cancelRankEstimate();
    const requestId = ++screeningEstimateRequest.current;
    const controller = new AbortController();
    screeningEstimateAbort.current = controller;
    setScreeningEstimate(null);
    setScreeningEstimateLoading(true);
    try {
      const estimate = await fetchScreeningEstimate(options.openingId, controller.signal);
      if (requestId === screeningEstimateRequest.current) {
        setScreeningEstimate(estimate);
      }
    } catch {
      if (!controller.signal.aborted && requestId === screeningEstimateRequest.current) {
        options.notifications.error("Could not load the AI cost estimate for screening.");
      }
    } finally {
      if (screeningEstimateAbort.current === controller) {
        screeningEstimateAbort.current = null;
      }
      if (requestId === screeningEstimateRequest.current) {
        setScreeningEstimateLoading(false);
      }
    }
  }

  async function runScreening() {
    if (options.openingId === null) return;
    setScreeningRunning(true);
    setScreeningEstimate(null);
    setScreeningProgress(null);
    try {
      const response = await startScreeningRequest(options.openingId);
      if (!response.ok || !response.body) {
        const problem = await readProblem(response);
        options.notifications.error(
          problem ? `Screening failed: ${problem}` : "Screening failed.",
        );
      } else {
        await streamNdjson<ScreeningStreamEvent>(response.body, (event) => {
          if (event.type === "progress") {
            setScreeningProgress({ processed: event.processed, total: event.total });
          } else if (event.type === "summary") {
            const failedNote = event.failed ? ` ${event.failed} failed and were skipped.` : "";
            options.notifications.success(
              `Screening complete: ${event.flagged} flagged of ${event.analyzed + event.cached} analyzed ` +
                `(${money(event.totalCostUsd)}).` +
                failedNote,
            );
          }
        });
        options.refreshDashboard();
        options.reloadApplications();
        options.clearSelectedApplication();
      }
    } catch (error) {
      options.notifications.error(
        error instanceof Error ? `Screening error: ${error.message}` : "Screening error.",
      );
    } finally {
      setScreeningProgress(null);
      setScreeningRunning(false);
    }
  }

  async function requestRankEstimate() {
    if (options.openingId === null) return;
    cancelScreeningEstimate();
    const requestId = ++rankEstimateRequest.current;
    const controller = new AbortController();
    rankEstimateAbort.current = controller;
    setRankEstimate(null);
    setScoreCurrentEstimate(null);
    setRankEstimateLoading(true);

    try {
      const [estimate, scoreEstimate] = await Promise.all([
        fetchRankEstimate(options.openingId, controller.signal),
        options.ranking.currentRun
          ? fetchScoreCurrentEstimate(options.openingId, controller.signal)
          : Promise.resolve(null),
      ]);
      if (requestId === rankEstimateRequest.current) {
        setRankEstimate(estimate);
        setScoreCurrentEstimate(scoreEstimate);
      }
    } catch {
      if (!controller.signal.aborted && requestId === rankEstimateRequest.current) {
        options.notifications.error("Could not load the AI cost estimate for ranking.");
      }
    } finally {
      if (rankEstimateAbort.current === controller) {
        rankEstimateAbort.current = null;
      }
      if (requestId === rankEstimateRequest.current) {
        setRankEstimateLoading(false);
      }
    }
  }

  async function runRank(mode: "discover" | "score-current") {
    if (options.openingId === null) return;
    setRankRunning(true);
    cancelRankEstimate();
    setRankProgress(null);
    setCriteriaThinking("");
    const priorProposals = options.ranking.currentRun?.proposedDimensions ?? [];
    if (mode === "discover" && priorProposals.length > 0) {
      options.ranking.setDisplayedProposals([]);
    }

    try {
      const response = mode === "discover"
        ? await startRankRequest(options.openingId)
        : await startScoreCurrentRequest(options.openingId);
      if (!response.ok || !response.body) {
        const problem = await readProblem(response);
        options.notifications.error(problem ? `Ranking failed: ${problem}` : "Ranking failed.");
        if (mode === "discover" && priorProposals.length > 0) {
          options.ranking.setDisplayedProposals(priorProposals);
        }
      } else {
        await streamNdjson<RankingStreamEvent>(response.body, (event) => {
          if (event.type === "phase") {
            setRankProgress({
              phase: event.phase as RankProgress["phase"],
              processed: 0,
              total: event.total ?? 0,
            });
          } else if (event.type === "progress") {
            setRankProgress({
              phase: event.phase as RankProgress["phase"],
              processed: event.processed,
              total: event.total,
            });
          } else if (event.type === "stage") {
            setRankProgress((current) =>
              current
                ? { ...current, stage: event.stage }
                : { phase: "criteria", processed: 0, total: 0, stage: event.stage },
            );
          } else if (event.type === "thinking") {
            setCriteriaThinking((current) => current + event.text);
          } else if (event.type === "warning") {
            options.notifications.warning(event.message || "The run completed with a warning.");
          } else if (event.type === "error") {
            options.notifications.error(event.message || "Ranking failed.");
          } else if (event.type === "summary") {
            const failedNote = event.failed ? ` ${event.failed} failed and were skipped.` : "";
            options.notifications.success(
              `${mode === "discover" ? "Ranking complete" : "Current criteria updated"}: ` +
                `${event.dimensions} criteria, ${event.scored} candidates scored ` +
                `(${money(event.totalCostUsd)}).` +
                failedNote,
            );
          }
        });
        await options.ranking.refreshCurrentRun();
        options.refreshDashboard();
        void options.ranking.load();
      }
    } catch (error) {
      options.notifications.error(
        error instanceof Error ? `Ranking error: ${error.message}` : "Ranking error.",
      );
      if (mode === "discover") void options.ranking.refreshCurrentRun();
    } finally {
      setRankProgress(null);
      setRankRunning(false);
      setCriteriaThinking("");
    }
  }

  return {
    screeningEstimate,
    screeningEstimateLoading,
    screeningRunning,
    screeningProgress,
    rankEstimate,
    rankEstimateLoading,
    scoreCurrentEstimate,
    rankRunning,
    rankProgress,
    criteriaThinking,
    requestScreeningEstimate,
    runScreening,
    cancelScreeningEstimate,
    requestRankEstimate,
    runRank,
    cancelRankEstimate,
    resetEstimates,
  };
}
