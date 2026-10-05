import { type ApiClient, publicClient } from "./client";
import type {
  ConsolidateAuditResponse,
  CurrentRunResponse,
  DecomposeAuditResponse,
  FanOutAuditResponse,
  MatchAuditResponse,
  RankEstimateResponse,
  RankingBoardResponse,
  ScoreCurrentEstimateResponse,
  Tier,
} from "../types";

const openingQuery = (openingId: number) => `?opening_id=${openingId}`;

export function createApi(client: ApiClient) {
  const { getJson, request, streamRequest } = client;
  const fetchRankingCurrent = (openingId: number) =>
    getJson<CurrentRunResponse | null>(`/ranking/current${openingQuery(openingId)}`);

  // The current run's carry-forward audit, or null when none is stored.
  const fetchMatchAudit = (openingId: number) =>
    getJson<MatchAuditResponse | null>(`/ranking/current/match-audit${openingQuery(openingId)}`);

  // The current run's decomposition audit — how the K fan-out discovery reports were
  // settled into one set (settled axes + merge reasoning + folded-request trail).
  // Null when no decomposition audit is stored.
  const fetchDecomposeAudit = (openingId: number) =>
    getJson<DecomposeAuditResponse | null>(`/ranking/current/decompose-audit${openingQuery(openingId)}`);

  const fetchConsolidateAudit = (openingId: number) =>
    getJson<ConsolidateAuditResponse | null>(`/ranking/current/consolidate-audit${openingQuery(openingId)}`);

  // The current run's fan-out audit — each of the K parallel discoverers' dimensions +
  // reasoning. Null when no fan-out audit is stored.
  const fetchFanOutAudit = (openingId: number) =>
    getJson<FanOutAuditResponse | null>(`/ranking/current/fan-out-audit${openingQuery(openingId)}`);

  const fetchRankEstimate = (openingId: number, signal?: AbortSignal) =>
    getJson<RankEstimateResponse>(`/ranking/run/estimate${openingQuery(openingId)}`, signal);

  const runRank = (openingId: number, signal?: AbortSignal) =>
    streamRequest(`/ranking/run${openingQuery(openingId)}`, signal);

  const fetchScoreCurrentEstimate = (openingId: number, signal?: AbortSignal) =>
    getJson<ScoreCurrentEstimateResponse>(`/ranking/score-current/estimate${openingQuery(openingId)}`, signal);

  const scoreCurrent = (openingId: number, signal?: AbortSignal) =>
    streamRequest(`/ranking/score-current${openingQuery(openingId)}`, signal);

  const fetchRankingBoard = (openingId: number) =>
    getJson<RankingBoardResponse>(`/ranking/board${openingQuery(openingId)}`);

  // analysisId is the analysis the client is viewing; the server rejects a save against a
  // superseded one (409 stale_analysis) so a member's edit never lands on the wrong board.
  function saveTiers(
    openingId: number,
    analysisId: number,
    next: Tier[],
    acknowledgedKeys: string[],
    acknowledgedRequestedKeys: string[] = [],
  ): Promise<Response> {
    return request(`/ranking/tiers${openingQuery(openingId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ analysisId, tiers: next, acknowledgedKeys, acknowledgedRequestedKeys }),
    });
  }

  // Persist pending free-text proposals for the current analysis. The next Rank reads these,
  // so they take effect on its discovery pass. (Keeping an existing axis across re-runs is
  // tier placement — see saveTiers — not a seed.) analysisId guards against a stale save.
  function saveSeeds(
    openingId: number,
    analysisId: number,
    seeds: { proposedDimensions?: string[] },
  ): Promise<Response> {
    return request(`/ranking/seeds${openingQuery(openingId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ analysisId, ...seeds }),
    });
  }
  return {
    fetchRankingCurrent, fetchMatchAudit, fetchDecomposeAudit, fetchConsolidateAudit,
    fetchFanOutAudit, fetchRankEstimate, runRank, fetchScoreCurrentEstimate, scoreCurrent,
    fetchRankingBoard, saveTiers, saveSeeds,
  };
}

// Public/bootstrap callers and manual harnesses use the unbound client.
export const {
  fetchRankingCurrent, fetchMatchAudit, fetchDecomposeAudit, fetchConsolidateAudit,
  fetchFanOutAudit, fetchRankEstimate, runRank, fetchScoreCurrentEstimate, scoreCurrent,
  fetchRankingBoard, saveTiers, saveSeeds,
} = createApi(publicClient);
