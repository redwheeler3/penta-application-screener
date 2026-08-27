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

export const fetchRankingCurrent = () => getJson<CurrentRunResponse | null>("/ranking/current");

// The current run's carry-forward audit, or null when none is stored.
export const fetchMatchAudit = () => getJson<MatchAuditResponse | null>("/ranking/current/match-audit");

// The current run's decomposition audit — how the K fan-out discovery reports were
// settled into one set (settled axes + merge reasoning + D9 folded-request trail).
// Null when no decomposition audit is stored.
export const fetchDecomposeAudit = () =>
  getJson<DecomposeAuditResponse | null>("/ranking/current/decompose-audit");

export const fetchConsolidateAudit = () =>
  getJson<ConsolidateAuditResponse | null>("/ranking/current/consolidate-audit");

// The current run's fan-out audit — each of the K parallel discoverers' dimensions +
// reasoning. Null when no fan-out audit is stored.
export const fetchFanOutAudit = () =>
  getJson<FanOutAuditResponse | null>("/ranking/current/fan-out-audit");

// Aggregated AI spend, grouped by run.

export const fetchRankEstimate = (signal?: AbortSignal) =>
  getJson<RankEstimateResponse>("/ranking/run/estimate", signal);
export const runRank = () => streamRequest("/ranking/run");
export const fetchScoreCurrentEstimate = (signal?: AbortSignal) =>
  getJson<ScoreCurrentEstimateResponse>("/ranking/score-current/estimate", signal);
export const scoreCurrent = () => streamRequest("/ranking/score-current");

export const fetchRanking = () => getJson<RankingResponse>("/ranking");

export const fetchTiers = () => getJson<{ tiers: Tier[] }>("/ranking/tiers");

// analysisId is the analysis the client is viewing; the server rejects a save against a
// superseded one (409 stale_analysis) so a member's edit never lands on the wrong board.
export function saveTiers(
  analysisId: number,
  next: Tier[],
  acknowledgedKeys: string[],
  acknowledgedRequestedKeys: string[] = [],
): Promise<Response> {
  return request("/ranking/tiers", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ analysisId, tiers: next, acknowledgedKeys, acknowledgedRequestedKeys }),
  });
}

// Persist pending free-text proposals for the current analysis. The next Rank reads these,
// so they take effect on its discovery pass. (Keeping an existing axis across re-runs is
// tier placement — see saveTiers — not a seed.) analysisId guards against a stale save.
export function saveSeeds(
  analysisId: number,
  seeds: { proposedDimensions?: string[] },
): Promise<Response> {
  return request("/ranking/seeds", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ analysisId, ...seeds }),
  });
}

