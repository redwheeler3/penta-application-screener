import { useState } from "react";
import * as api from "../api";
import { readProblem } from "../format";
import type { CurrentRunResponse, RankingResponse, Tier } from "../types";

export interface RankingState {
  /** The current run's discovered dimensions, shown above the list once Rank has run;
   * null until discovery has run (or after a failed fetch). */
  rankingRun: CurrentRunResponse | null;
  /** The deterministic ranked shortlist; null means not yet fetched. */
  ranking: RankingResponse | null;
  /** The committee's importance tiers for the current run. */
  tiers: Tier[] | null;
  /** Re-fetch the current run's dimensions. Returns the promise so callers can await
   * it before rendering anything that resolves dimension keys to names. */
  refreshRankingRun: () => Promise<void>;
  /** Fetch the ranked shortlist + tier layout (pure math, no cost). Returns whether it
   * loaded — the caller owns the tab switch / detail clear, which aren't ranking state. */
  loadRanking: () => Promise<boolean>;
  /** Persist a new tier layout; the PUT returns the re-sorted ranking. Optimistic. */
  saveTiers: (next: Tier[], acknowledgedKeys?: string[]) => Promise<void>;
  /** Acknowledge "new" dimensions in place (drop them from new_dimension_keys without
   * moving), via the same tiers PUT. */
  acknowledgeNewDimensions: (keys: string[]) => Promise<void>;
  /** Dismiss the "Requested" provenance pill on the given keys (its ✕), via the same
   * tiers PUT — provenance, so it clears only on this explicit action, not on a move. */
  dismissRequested: (keys: string[]) => Promise<void>;
  addProposal: (text: string) => void;
  removeProposal: (text: string) => void;
}

/** The ranking cluster: the current run's dimensions, the ranked shortlist, and the
 * committee's tiers + free-text proposals — plus the pure-persistence handlers that keep
 * them in lockstep (a tier edit re-sorts; a proposal feeds the next Rank). Talks to the
 * api layer and surfaces failures through the injected ``onError``. The AI *run* flow
 * (discover/score) lives in App: it orchestrates dashboard/list/tab refreshes across
 * clusters, so it stays with the orchestrator rather than owning this state. */
export function useRanking(onError: (message: string) => void): RankingState {
  const [rankingRun, setRankingRun] = useState<CurrentRunResponse | null>(null);
  const [ranking, setRanking] = useState<RankingResponse | null>(null);
  const [tiers, setTiers] = useState<Tier[] | null>(null);

  function refreshRankingRun() {
    return api
      .fetchRankingCurrent()
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: CurrentRunResponse | null) => setRankingRun(payload))
      .catch(() => setRankingRun(null));
  }

  async function loadRanking(): Promise<boolean> {
    const [rankRes, tiersRes] = await Promise.all([api.fetchRanking(), api.fetchTiers()]);
    if (rankRes.ok) {
      setRanking(await rankRes.json());
      if (tiersRes.ok) setTiers((await tiersRes.json()).tiers);
      return true;
    }
    const problem = await readProblem(rankRes);
    onError(problem ? `Could not load the ranking: ${problem}` : "Could not load the ranking.");
    return false;
  }

  async function saveTiers(
    next: Tier[],
    acknowledgedKeys: string[] = [],
    acknowledgedRequestedKeys: string[] = [],
  ) {
    // Tie the save to the analysis we're viewing so the server rejects it (409) if
    // another member re-ranked since. No analysis loaded → nothing to save against.
    const analysisId = ranking?.analysisId ?? rankingRun?.analysisId;
    if (analysisId === undefined) return;
    setTiers(next);
    const response = await api.saveTiers(analysisId, next, acknowledgedKeys, acknowledgedRequestedKeys);
    if (response.ok) {
      const updated: RankingResponse = await response.json();
      setRanking(updated);
      // The requested pill reads from rankingRun.dimensions' flag set, which the tiers
      // PUT doesn't return — mirror the server's dismissal onto rankingRun so the pill
      // clears in the same round-trip (it's echoed on RankingResponse.requestedDimensionKeys).
      if (acknowledgedRequestedKeys.length > 0) {
        setRankingRun((run) =>
          run ? { ...run, requestedDimensionKeys: updated.requestedDimensionKeys } : run,
        );
      }
    } else {
      onError("Could not update the tiers.");
      loadRanking(); // reconcile back to the server's truth on failure
    }
  }

  async function acknowledgeNewDimensions(keys: string[]) {
    if (!tiers || keys.length === 0) return;
    await saveTiers(tiers, keys);
  }

  async function dismissRequested(keys: string[]) {
    if (!tiers || keys.length === 0) return;
    await saveTiers(tiers, [], keys);
  }

  // Persist pending free-text proposals for the current run — they feed the NEXT Rank's
  // discovery. Optimistically update rankingRun (where the composer reads proposal
  // state) for instant feedback; reconcile from the response.
  async function saveSeeds(next: { proposedDimensions?: string[] }) {
    if (!rankingRun) return;
    const optimistic = {
      ...rankingRun,
      ...(next.proposedDimensions !== undefined ? { proposedDimensions: next.proposedDimensions } : {}),
    };
    setRankingRun(optimistic);
    const response = await api.saveSeeds(rankingRun.analysisId, {
      proposedDimensions: next.proposedDimensions,
    });
    if (response.ok) {
      const echoed: { proposedDimensions: string[] } = await response.json();
      setRankingRun((run) =>
        run ? { ...run, proposedDimensions: echoed.proposedDimensions } : run,
      );
    } else {
      onError("Could not save the suggested criteria.");
      refreshRankingRun(); // reconcile back to server truth
    }
  }

  function addProposal(text: string) {
    if (!rankingRun) return;
    if (rankingRun.proposedDimensions.includes(text)) return;
    saveSeeds({ proposedDimensions: [...rankingRun.proposedDimensions, text] });
  }

  function removeProposal(text: string) {
    if (!rankingRun) return;
    saveSeeds({ proposedDimensions: rankingRun.proposedDimensions.filter((t) => t !== text) });
  }

  return {
    rankingRun,
    ranking,
    tiers,
    refreshRankingRun,
    loadRanking,
    saveTiers,
    acknowledgeNewDimensions,
    dismissRequested,
    addProposal,
    removeProposal,
  };
}
