import type {
  ConsolidateAuditResponse,
  CurrentRunResponse,
  DecomposeAuditResponse,
  FanOutAuditResponse,
  MatchAuditResponse,
  RankEstimateResponse,
  RankingResponse,
  ScoreCurrentEstimateResponse,
  Tier,
} from "../types";
import { getJson, request, streamRequest } from "./client";

const openingQuery = (openingId: number) => `?opening_id=${openingId}`;

export const fetchRankingCurrent = (openingId: number) =>
  getJson<CurrentRunResponse | null>(`/ranking/current${openingQuery(openingId)}`);

// The current run's carry-forward audit, or null when none is stored.
export const fetchMatchAudit = (openingId: number) =>
  getJson<MatchAuditResponse | null>(`/ranking/current/match-audit${openingQuery(openingId)}`);

// The current run's decomposition audit — how the K fan-out discovery reports were
// settled into one set (settled axes + merge reasoning + D9 folded-request trail).
// Null when no decomposition audit is stored.
export const fetchDecomposeAudit = (openingId: number) =>
  getJson<DecomposeAuditResponse | null>(`/ranking/current/decompose-audit${openingQuery(openingId)}`);

export const fetchConsolidateAudit = (openingId: number) =>
  getJson<ConsolidateAuditResponse | null>(`/ranking/current/consolidate-audit${openingQuery(openingId)}`);

// The current run's fan-out audit — each of the K parallel discoverers' dimensions +
// reasoning. Null when no fan-out audit is stored.
export const fetchFanOutAudit = (openingId: number) =>
  getJson<FanOutAuditResponse | null>(`/ranking/current/fan-out-audit${openingQuery(openingId)}`);

// Aggregated AI spend, grouped by run.

export const fetchRankEstimate = (openingId: number, signal?: AbortSignal) =>
  getJson<RankEstimateResponse>(`/ranking/run/estimate${openingQuery(openingId)}`, signal);
export const runRank = (openingId: number) =>
  streamRequest(`/ranking/run${openingQuery(openingId)}`);
export const fetchScoreCurrentEstimate = (openingId: number, signal?: AbortSignal) =>
  getJson<ScoreCurrentEstimateResponse>(`/ranking/score-current/estimate${openingQuery(openingId)}`, signal);
export const scoreCurrent = (openingId: number) =>
  streamRequest(`/ranking/score-current${openingQuery(openingId)}`);

export const fetchRanking = (openingId: number) =>
  getJson<RankingResponse>(`/ranking${openingQuery(openingId)}`);

export const fetchTiers = (openingId: number) =>
  getJson<{ tiers: Tier[] }>(`/ranking/tiers${openingQuery(openingId)}`);

// analysisId is the analysis the client is viewing; the server rejects a save against a
// superseded one (409 stale_analysis) so a member's edit never lands on the wrong board.
export function saveTiers(
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
export function saveSeeds(
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
