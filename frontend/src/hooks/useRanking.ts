import { useEffect, useState } from "react";
import * as api from "../api/ranking";
import { problemMessage, readProblemBody } from "../api/problems";
import type { CurrentRunResponse, RankingResponse, Tier } from "../types";

export interface RankingState {
  /** The current run's discovered dimensions, shown above the list once Rank has run;
   * null until discovery has run (or after a failed fetch). */
  rankingRun: CurrentRunResponse | null;
  /** The deterministic ranked shortlist; null means not yet fetched. */
  ranking: RankingResponse | null;
  /** Read state for the shortlist's initial load. Existing ranking data remains visible while
   * a later refresh is in flight. */
  rankingLoadState: "idle" | "loading" | "ready" | "error";
  /** The committee's importance tiers for the current run. */
  tiers: Tier[] | null;
  /** Re-fetch the current run's dimensions. Returns the promise so callers can await
   * it before rendering anything that resolves dimension keys to names. */
  refreshRankingRun: () => Promise<void>;
  /** Fetch the ranked shortlist + tier layout (pure math, no cost). Returns whether it
   * loaded; callers may switch to the Ranking tab immediately and render this hook's load
   * state while the initial response is in flight. */
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
  /** Set the displayed pending proposals directly (no persist) — a discover run consumes
   * them, so App clears them optimistically when the run starts and restores on failure.
   * The server is the source of truth; this only steers what the UI shows meanwhile. */
  setDisplayedProposals: (proposed: string[]) => void;
  /** True once we've detected the loaded ranking is no longer current — either a tier/seed
   * save was rejected (409 stale_analysis) or a focus-time check saw the current analysis id
   * drift. Drives a global "reload" toast; cleared by ``reloadStaleRanking``. */
  staleAnalysis: boolean;
  /** Cheaply check whether the loaded ranking is still current (compares the server's current
   * analysis id to the loaded one) and set ``staleAnalysis`` on drift. Called on tab focus /
   * visibility so a passively-viewing member learns another member re-ranked without a manual
   * refresh. No-op when nothing is loaded yet. */
  checkForStaleRanking: () => Promise<void>;
  /** Re-fetch the current analysis + ranking + tiers and clear the stale flag — the toast's
   * Reload action. Returns whether the reload succeeded. */
  reloadStaleRanking: () => Promise<boolean>;
}

/** The ranking cluster: the current run's dimensions, the ranked shortlist, and the
 * committee's tiers + free-text proposals — plus the pure-persistence handlers that keep
 * them in lockstep (a tier edit re-sorts; a proposal feeds the next Rank). Talks to the
 * api layer and surfaces failures through the injected ``onError``. The separate
 * ``useAiRuns`` hook owns the discover/score lifecycle and coordinates its refreshes. */
export function useRanking(
  openingId: number | null,
  onError: (message: string) => void,
): RankingState {
  const [rankingRun, setRankingRun] = useState<CurrentRunResponse | null>(null);
  const [ranking, setRanking] = useState<RankingResponse | null>(null);
  const [tiers, setTiers] = useState<Tier[] | null>(null);
  const [rankingLoadState, setRankingLoadState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [staleAnalysis, setStaleAnalysis] = useState(false);

  useEffect(() => {
    // Every value in this hook belongs to one opening. Clear the prior board
    // synchronously when the opening changes so an unrelated mutation cannot try to
    // refresh or save the previous opening's ranking.
    setRankingRun(null);
    setRanking(null);
    setTiers(null);
    setRankingLoadState("idle");
    setStaleAnalysis(false);
  }, [openingId]);

  // Read the single-use problem body once. A stale analysis opens the reload toast;
  // other failures return their message to the caller.
  async function handleSaveFailure(
    response: Response,
  ): Promise<{ handled: boolean; message: string | null }> {
    const body = await readProblemBody(response);
    if (body?.code === "stale_analysis") {
      setStaleAnalysis(true);
      return { handled: true, message: null };
    }
    return { handled: false, message: problemMessage(body) };
  }

  // Refresh the complete board before clearing the stale flag.
  async function reloadStaleRanking(): Promise<boolean> {
    await refreshRankingRun();
    const ok = await loadRanking();
    if (ok) setStaleAnalysis(false);
    return ok;
  }

  // Passive staleness check (tab focus / visibility). Compares the server's current analysis
  // id to the one this browser has loaded; if they differ, another member re-ranked and this
  // view is stale. One cheap GET; no-op if nothing is loaded, already flagged stale, or the
  // fetch fails (a transient error shouldn't nag). The reload itself stays a deliberate action
  // (the toast), so a member mid-tiering isn't yanked.
  async function checkForStaleRanking(): Promise<void> {
    if (openingId === null) return;
    const loadedId = ranking?.analysisId ?? rankingRun?.analysisId;
    if (loadedId === undefined || loadedId === null || staleAnalysis) return;
    try {
      const current = await api.fetchRankingCurrent(openingId);
      if (current && current.analysisId !== loadedId) setStaleAnalysis(true);
    } catch {
      /* transient — try again on the next focus */
    }
  }

  function refreshRankingRun() {
    if (openingId === null) {
      setRankingRun(null);
      return Promise.resolve();
    }
    return api
      .fetchRankingCurrent(openingId)
      .then(setRankingRun)
      .catch(() => setRankingRun(null));
  }

  async function loadRanking(): Promise<boolean> {
    if (openingId === null) return false;
    setRankingLoadState("loading");
    try {
      const [nextRanking, nextTiers] = await Promise.all([
        api.fetchRanking(openingId),
        api.fetchTiers(openingId),
      ]);
      setRanking(nextRanking);
      setTiers(nextTiers.tiers);
      setRankingLoadState("ready");
      return true;
    } catch {
      onError("Could not load the ranking. Please try again.");
    }
    setRankingLoadState("error");
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
    if (openingId === null) return;
    const response = await api.saveTiers(
      openingId, analysisId, next, acknowledgedKeys, acknowledgedRequestedKeys,
    );
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
      // Not a stale-analysis rejection — a genuine failure (e.g. a rank in progress blocked
      // the save so a late edit can't vanish). Surface the server's reason and reconcile to
      // its truth, which reverts the optimistic setTiers above — the edit didn't persist.
      const { handled, message } = await handleSaveFailure(response);
      if (!handled) {
        onError(message ?? "Could not update the tiers.");
        loadRanking();
      }
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
    if (!rankingRun || openingId === null) return;
    const optimistic = {
      ...rankingRun,
      ...(next.proposedDimensions !== undefined ? { proposedDimensions: next.proposedDimensions } : {}),
    };
    setRankingRun(optimistic);
    const response = await api.saveSeeds(openingId, rankingRun.analysisId, {
      proposedDimensions: next.proposedDimensions,
    });
    if (response.ok) {
      const echoed: { proposedDimensions: string[] } = await response.json();
      setRankingRun((run) =>
        run ? { ...run, proposedDimensions: echoed.proposedDimensions } : run,
      );
    } else {
      const { handled, message } = await handleSaveFailure(response);
      if (!handled) {
        onError(message ?? "Could not save the suggested criteria.");
        refreshRankingRun(); // reconcile back to server truth (reverts the optimistic set)
      }
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

  function setDisplayedProposals(proposed: string[]) {
    setRankingRun((run) => (run ? { ...run, proposedDimensions: proposed } : run));
  }

  return {
    rankingRun,
    ranking,
    rankingLoadState,
    tiers,
    refreshRankingRun,
    loadRanking,
    saveTiers,
    acknowledgeNewDimensions,
    dismissRequested,
    addProposal,
    removeProposal,
    setDisplayedProposals,
    staleAnalysis,
    checkForStaleRanking,
    reloadStaleRanking,
  };
}
