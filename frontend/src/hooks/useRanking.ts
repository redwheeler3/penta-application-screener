import { useCommitteeApi } from "../api/identity";
import { useCallback, useEffect, useRef, useState } from "react";
import * as rankingApi from "../api/ranking";
import { problemMessage, readProblemBody } from "../api/problems";
import type { CurrentRunResponse, RankingBoardResponse, RankingResponse, Tier } from "../types";
import { type RequestIsCurrent, useRequestScope } from "./useRequestScope";

export type RankingRunRead =
  | { status: "loaded"; run: CurrentRunResponse | null }
  | { status: "superseded" | "error" };

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
  refreshRankingRun: () => Promise<RankingRunRead>;
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
  addProposal: (text: string) => Promise<boolean>;
  removeProposal: (text: string) => void;
  /** Set the displayed pending proposals directly (no persist) — a discover run consumes
   * them, so the run controls clear them optimistically and restore on failure.
   * The server is the source of truth; this only steers what the UI shows meanwhile. */
  setDisplayedProposals: (proposed: string[]) => void;
  /** Fence reads that began before this workspace started AI work. */
  invalidateReads: () => void;
  /** True once we've detected the loaded ranking is no longer current — either a tier/seed
   * save was rejected (409 stale_analysis) or a focus-time check saw the current analysis id
   * drift. Drives a global "reload" toast; cleared by ``reloadStaleRanking``. */
  staleAnalysis: boolean;
  /** Reconcile a displayed board without replacing newer optimistic edits. */
  refreshRankingView: () => Promise<void>;
  /** Observe the analysis identity already returned by the scoped dashboard read. */
  observeCurrentAnalysis: (analysisId: number | null) => void;
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
  const api = useCommitteeApi(rankingApi);

  const [rankingRun, setRankingRun] = useState<CurrentRunResponse | null>(null);
  const [ranking, setRanking] = useState<RankingResponse | null>(null);
  const [tiers, setTiers] = useState<Tier[] | null>(null);
  const [rankingLoadState, setRankingLoadState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [staleAnalysis, setStaleAnalysis] = useState(false);

  const currentReads = useRequestScope(openingId);
  const boardReads = useRequestScope(openingId);
  const analysisId = ranking?.analysisId ?? rankingRun?.analysisId;
  const mutationKey = `${openingId}:${analysisId ?? "none"}`;
  const mutations = useRequestScope(mutationKey);
  const mutationQueue = useRef<Promise<void>>(Promise.resolve());
  const pendingMutations = useRef(new Set<RequestIsCurrent>());
  const tierSaveVersion = useRef(0);
  const proposalSaveVersion = useRef(0);
  const runRef = useRef(rankingRun);
  const boardRef = useRef(ranking);
  const tiersRef = useRef(tiers);
  runRef.current = rankingRun;
  boardRef.current = ranking;
  tiersRef.current = tiers;

  useEffect(() => {
    setRankingRun(null);
    setRanking(null);
    setTiers(null);
    runRef.current = null;
    boardRef.current = null;
    tiersRef.current = null;
    setRankingLoadState("idle");
    setStaleAnalysis(false);
  }, [openingId]);

  const invalidateReads = useCallback(() => {
    currentReads.invalidate();
    boardReads.invalidate();
    setRankingLoadState((state) => state === "loading"
      ? boardRef.current !== null ? "ready" : "idle" : state);
  }, [currentReads, boardReads]);

  const markStale = useCallback(() => {
    // A newer observation supersedes every older read, including a pending Reload.
    invalidateReads();
    setStaleAnalysis(true);
  }, [invalidateReads]);

  // Both controls update one member record. Serialize requests so the server receives
  // edits in order; scope checks discard queued work for a board the member has left.
  function enqueueMutation(isCurrent: RequestIsCurrent, request: () => Promise<Response>) {
    pendingMutations.current.add(isCurrent);
    invalidateReads();
    const result = mutationQueue.current.then(async () => {
      if (!isCurrent()) return undefined;
      const response = await request();
      // A write remains pending through its acknowledgement, not only its headers.
      // Board reads must not replace an optimistic draft while this body is waiting.
      return response.ok
        ? { ok: true, payload: await response.json(), problem: null }
        : { ok: false, payload: null, problem: await readProblemBody(response) };
    });
    mutationQueue.current = result.then(() => {}, () => {});
    return result.finally(() => { pendingMutations.current.delete(isCurrent); });
  }

  const hasPendingMutations = useCallback(() => {
    return [...pendingMutations.current].some((isCurrent) => isCurrent());
  }, []);

  const adoptBoard = useCallback((board: RankingBoardResponse) => {
    currentReads.invalidate();
    runRef.current = board.run;
    boardRef.current = board.ranking;
    tiersRef.current = board.tiers;
    setRankingRun(board.run);
    setRanking(board.ranking);
    setTiers(board.tiers);
    setRankingLoadState("ready");
    setStaleAnalysis(false);
  }, [currentReads]);

  function handleSaveFailure(body: Awaited<ReturnType<typeof readProblemBody>>, isCurrent: RequestIsCurrent) {
    if (!isCurrent()) return { handled: true, message: null };
    if (body?.code === "stale_analysis") {
      markStale();
      return { handled: true, message: null };
    }
    return { handled: false, message: problemMessage(body) };
  }

  const observeCurrentAnalysis = useCallback((currentId: number | null) => {
    const loadedId = boardRef.current?.analysisId ?? runRef.current?.analysisId;
    // A dashboard read describes the board it started beside, not a newer board
    // adopted while that request was waiting.
    if (currentReads.isFor(openingId) && analysisId != null && loadedId === analysisId
      && !hasPendingMutations() && currentId !== loadedId) {
      markStale();
    }
  }, [analysisId, currentReads, hasPendingMutations, markStale, openingId]);

  const refreshRankingView = useCallback(async (): Promise<void> => {
    const loadedId = boardRef.current?.analysisId;
    if (openingId === null || !boardReads.isFor(openingId) || loadedId == null || hasPendingMutations()) return;
    const isCurrent = boardReads.begin();
    try {
      const board = await api.fetchRankingBoard(openingId);
      if (!isCurrent()) return;
      if (board.run.analysisId !== loadedId) markStale();
      else adoptBoard(board);
    } catch {
      /* Keep the displayed board; focus/intake refresh retries. */
    }
  }, [adoptBoard, api, boardReads, hasPendingMutations, markStale, openingId]);

  async function refreshRankingRun(): Promise<RankingRunRead> {
    if (openingId === null || !currentReads.isFor(openingId) || hasPendingMutations()) {
      return { status: "superseded" };
    }
    const isCurrent = currentReads.begin();
    try {
      const run = await api.fetchRankingCurrent(openingId);
      if (!isCurrent()) return { status: "superseded" };
      // A displayed board owns its criteria snapshot. Replace it through a full
      // board read, including consolidation changes within the same analysis.
      if (boardRef.current !== null) return { status: "loaded", run };
      runRef.current = run;
      setRankingRun(run);
      return { status: "loaded", run };
    } catch {
      // Preserve the loaded board on a transient refresh failure.
      if (isCurrent() && boardRef.current === null) setRankingLoadState("error");
      return { status: isCurrent() ? "error" : "superseded" };
    }
  }

  async function loadRanking(): Promise<boolean> {
    if (openingId === null || !boardReads.isFor(openingId) || hasPendingMutations()) return false;
    const isCurrent = boardReads.begin();
    currentReads.invalidate();
    setRankingLoadState("loading");
    try {
      const board = await api.fetchRankingBoard(openingId);
      if (!isCurrent()) return false;
      adoptBoard(board);
      return true;
    } catch {
      if (!isCurrent()) return false;
      onError("Could not load the ranking. Please try again.");
      setRankingLoadState("error");
      return false;
    }
  }

  async function reloadAfterSaveFailure(isLatest: RequestIsCurrent, requiresBoard = false) {
    // Let already-queued edits settle before reading their combined server state.
    await mutationQueue.current;
    if (!isLatest()) return;
    if (requiresBoard || boardRef.current !== null) await loadRanking();
    else await refreshRankingRun();
  }

  async function saveTiers(
    next: Tier[], acknowledgedKeys: string[] = [], acknowledgedRequestedKeys: string[] = [],
  ): Promise<void> {
    if (openingId === null || analysisId == null || !mutations.isFor(mutationKey)) return;
    const inScope = mutations.capture();
    const version = ++tierSaveVersion.current;
    const isLatest = () => inScope() && version === tierSaveVersion.current;
    tiersRef.current = next;
    setTiers(next);
    try {
      const response = await enqueueMutation(inScope, () => api.saveTiers(
        openingId, analysisId, next, acknowledgedKeys, acknowledgedRequestedKeys,
      ));
      if (!response || !isLatest()) return;
      if (response.ok) {
        const updated = response.payload as RankingResponse;
        if (!isLatest()) return;
        boardReads.invalidate();
        boardRef.current = updated;
        setRanking(updated);
        setRankingLoadState("ready");
      } else {
        const { handled, message } = handleSaveFailure(response.problem, isLatest);
        if (!handled && isLatest()) {
          onError(message ?? "Could not update the tiers.");
          await reloadAfterSaveFailure(isLatest, true);
        }
      }
    } catch {
      if (!isLatest()) return;
      onError("Could not update the tiers.");
      await reloadAfterSaveFailure(isLatest, true);
    }
  }

  async function acknowledgeNewDimensions(keys: string[]) {
    if (!tiersRef.current || keys.length === 0) return;
    await saveTiers(tiersRef.current, keys);
  }

  async function dismissRequested(keys: string[]) {
    if (!tiersRef.current || keys.length === 0) return;
    await saveTiers(tiersRef.current, [], keys);
  }

  async function changeProposal(operation: "add" | "remove", text: string): Promise<boolean> {
    const run = runRef.current;
    if (!run || openingId === null || !mutations.isFor(mutationKey)) return false;
    const proposedDimensions = operation === "add"
      ? [...new Set([...run.proposedDimensions, text])]
      : run.proposedDimensions.filter((proposal) => proposal !== text);
    const inScope = mutations.capture();
    const version = ++proposalSaveVersion.current;
    const isLatest = () => inScope() && version === proposalSaveVersion.current;
    const optimistic = { ...run, proposedDimensions };
    runRef.current = optimistic;
    setRankingRun(optimistic);
    try {
      const response = await enqueueMutation(inScope, () => api.changeProposal(
        openingId, run.analysisId, { operation, text },
      ));
      if (!response || !inScope()) return false;
      if (response.ok) {
        const echoed = response.payload as { proposedDimensions: string[] };
        if (!isLatest()) return true;
        currentReads.invalidate();
        setRankingRun((current) => {
          if (!current) return current;
          const updated = { ...current, proposedDimensions: echoed.proposedDimensions };
          runRef.current = updated;
          return updated;
        });
        return true;
      } else {
        const { handled, message } = handleSaveFailure(response.problem, isLatest);
        if (!handled && isLatest()) {
          onError(message ?? "Could not save the suggested criteria.");
          await reloadAfterSaveFailure(isLatest);
        }
      }
    } catch {
      if (!isLatest()) return false;
      onError("Could not save the suggested criteria.");
      await reloadAfterSaveFailure(isLatest);
    }
    return false;
  }

  function addProposal(text: string): Promise<boolean> {
    return changeProposal("add", text.trim());
  }

  function removeProposal(text: string): void {
    void changeProposal("remove", text);
  }

  function setDisplayedProposals(proposedDimensions: string[]) {
    proposalSaveVersion.current += 1;
    invalidateReads();
    const run = runRef.current;
    if (!run) return;
    const updated = { ...run, proposedDimensions };
    runRef.current = updated;
    setRankingRun(updated);
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
    invalidateReads,
    staleAnalysis,
    refreshRankingView,
    reloadStaleRanking: loadRanking,
    observeCurrentAnalysis,
  };
}
