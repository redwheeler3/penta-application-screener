import { act, waitFor } from "@testing-library/react";
import { renderCommitteeHook as renderHook, deferred } from "../testSupport";
import { beforeEach, expect, it, vi } from "vitest";
import type { CurrentRunResponse, RankingBoardResponse, RankingResponse, Tier } from "../types";
import { type RankingRunRead, useRanking } from "./useRanking";

const api = vi.hoisted(() => ({
  fetchRankingCurrent: vi.fn<ReturnType<typeof import("../api/ranking").createApi>["fetchRankingCurrent"]>(),
  fetchRankingBoard: vi.fn<ReturnType<typeof import("../api/ranking").createApi>["fetchRankingBoard"]>(),
  saveTiers: vi.fn<ReturnType<typeof import("../api/ranking").createApi>["saveTiers"]>(),
  changeProposal: vi.fn<ReturnType<typeof import("../api/ranking").createApi>["changeProposal"]>(),
}));

vi.mock("../api/ranking", () => ({
  createApi: () => api,
}));

const current = (analysisId: number): CurrentRunResponse => ({
  analysisId, dimensions: [], discoveryNarrative: null, newDimensionKeys: [],
  revivedDimensionKeys: [], requestedDimensionKeys: [], keptKeys: [], proposedDimensions: [],
});
const ranking = (analysisId: number, scoredCount = 0): RankingResponse => ({
  analysisId, scoredCount, candidates: [], weights: {}, newDimensionKeys: [],
  revivedDimensionKeys: [], requestedDimensionKeys: [], keptKeys: [], proposedDimensions: [],
});
const board = (analysisId: number, tiers: Tier[] = []): RankingBoardResponse => ({
  run: current(analysisId), ranking: ranking(analysisId), tiers,
});
const tier = (label: string): Tier[] => [{ id: "important", label, dimensionKeys: [] }];
beforeEach(() => vi.resetAllMocks());

it("keeps reads and later writes behind a pending acknowledgement body", async () => {
  const body = deferred<RankingResponse>();
  const response = Response.json(ranking(1));
  vi.spyOn(response, "json").mockReturnValue(body.promise);
  vi.mocked(api.fetchRankingBoard).mockResolvedValue(board(1, tier("Original")));
  vi.mocked(api.saveTiers).mockResolvedValue(response);
  vi.mocked(api.changeProposal).mockResolvedValue(Response.json({ proposedDimensions: ["Queued"] }));
  const { result } = renderHook(() => useRanking(1, vi.fn()));
  await act(() => result.current.loadRanking());
  let saving!: Promise<void>;
  await act(async () => { saving = result.current.saveTiers(tier("Edited")); });
  await act(async () => { void result.current.addProposal("Queued"); });
  await act(async () => expect(await result.current.loadRanking()).toBe(false));
  expect(api.fetchRankingBoard).toHaveBeenCalledOnce();
  expect(api.changeProposal).not.toHaveBeenCalled();
  expect(result.current.tiers).toEqual(tier("Edited"));
  await act(async () => { body.resolve(ranking(1)); await saving; });
  await waitFor(() => expect(api.changeProposal).toHaveBeenCalledOnce());
});

it("keeps saved proposals when an earlier board refresh finishes late", async () => {
  const earlier = deferred<RankingBoardResponse>();
  vi.mocked(api.fetchRankingBoard).mockResolvedValueOnce(board(1)).mockReturnValueOnce(earlier.promise);
  vi.mocked(api.changeProposal).mockResolvedValueOnce(Response.json({ proposedDimensions: ["Saved"] }))
    .mockResolvedValueOnce(Response.json({ proposedDimensions: ["Saved", "Second"] }));
  const { result } = renderHook(() => useRanking(1, vi.fn()));
  await act(() => result.current.loadRanking());
  let refreshing!: Promise<boolean>;
  act(() => { refreshing = result.current.loadRanking(); });
  await act(async () => { await result.current.addProposal("Saved"); });
  expect(result.current.rankingRun?.proposedDimensions).toEqual(["Saved"]);
  expect(result.current.rankingLoadState).toBe("ready");
  await act(async () => { earlier.resolve(board(1)); expect(await refreshing).toBe(false); });
  expect(result.current.rankingRun?.proposedDimensions).toEqual(["Saved"]);
  await act(async () => { await result.current.addProposal("Second"); });
  expect(vi.mocked(api.changeProposal).mock.calls[1][2]).toEqual({ operation: "add", text: "Second" });
});

it.each(["http", "network"])("reconciles a failed proposal with the displayed board after a %s failure", async (failure) => {
  const saved = board(1);
  saved.run.proposedDimensions = ["Existing"];
  saved.ranking.proposedDimensions = ["Existing"];
  vi.mocked(api.fetchRankingBoard).mockResolvedValue(saved);
  if (failure === "http") vi.mocked(api.changeProposal).mockResolvedValue(new Response(null, { status: 503 }));
  else vi.mocked(api.changeProposal).mockRejectedValue(new Error("Synthetic network failure"));
  const error = vi.fn();
  const { result } = renderHook(() => useRanking(1, error));
  await act(() => result.current.loadRanking());
  await act(async () => { await result.current.addProposal("Rejected"); });
  await waitFor(() => expect(api.fetchRankingBoard).toHaveBeenCalledTimes(2));
  expect(error).toHaveBeenCalledOnce();
  expect(api.fetchRankingCurrent).not.toHaveBeenCalled();
  expect(result.current.rankingRun?.proposedDimensions).toEqual(["Existing"]);
  expect(result.current.rankingLoadState).toBe("ready");
});

it("waits for queued tier saves before reconciling a failed proposal", async () => {
  const proposal = deferred<Response>();
  const tiers = deferred<Response>();
  vi.mocked(api.fetchRankingBoard).mockResolvedValueOnce(board(1))
    .mockResolvedValueOnce(board(1, tier("Accepted")));
  vi.mocked(api.changeProposal).mockReturnValue(proposal.promise);
  vi.mocked(api.saveTiers).mockReturnValue(tiers.promise);
  const { result } = renderHook(() => useRanking(1, vi.fn()));
  await act(() => result.current.loadRanking());
  await act(async () => { void result.current.addProposal("Rejected"); });
  let saving!: Promise<void>;
  act(() => { saving = result.current.saveTiers(tier("Accepted")); });
  await act(async () => proposal.resolve(new Response(null, { status: 503 })));
  expect(api.saveTiers).toHaveBeenCalledOnce();
  expect(api.fetchRankingBoard).toHaveBeenCalledOnce();
  await act(async () => { tiers.resolve(Response.json(ranking(1))); await saving; });
  await waitFor(() => expect(api.fetchRankingBoard).toHaveBeenCalledTimes(2));
  expect(result.current.tiers).toEqual(tier("Accepted"));
  expect(result.current.rankingRun?.proposedDimensions).toEqual([]);
});

it("ignores old current-analysis and board responses after an opening change", async () => {
  const oldCurrent = deferred<CurrentRunResponse>();
  const oldRanking = deferred<RankingBoardResponse>();
  vi.mocked(api.fetchRankingCurrent).mockReturnValueOnce(oldCurrent.promise).mockResolvedValueOnce(current(2));
  vi.mocked(api.fetchRankingBoard).mockReturnValueOnce(oldRanking.promise).mockResolvedValueOnce(board(2));
  const { result, rerender } = renderHook(({ openingId }) => useRanking(openingId, vi.fn()), {
    initialProps: { openingId: 1 },
  });
  let firstCurrent!: Promise<RankingRunRead>;
  let firstRanking!: Promise<boolean>;
  act(() => {
    firstCurrent = result.current.refreshRankingRun(); firstRanking = result.current.loadRanking();
  });
  rerender({ openingId: 2 });
  await act(async () => { await result.current.refreshRankingRun(); await result.current.loadRanking(); });
  await act(async () => {
    oldCurrent.resolve(current(1)); oldRanking.resolve(board(1));
    await Promise.all([firstCurrent, firstRanking]);
  });
  expect(result.current.rankingRun?.analysisId).toBe(2);
  expect(result.current.ranking?.analysisId).toBe(2);
});

it("sends rapid tier edits in order and displays only the latest response", async () => {
  const first = deferred<Response>();
  const second = deferred<Response>();
  vi.mocked(api.fetchRankingCurrent).mockResolvedValue(current(1));
  vi.mocked(api.saveTiers).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  const { result } = renderHook(() => useRanking(1, vi.fn()));
  await act(() => result.current.refreshRankingRun());
  let firstSave!: Promise<void>;
  let secondSave!: Promise<void>;
  await act(async () => {
    firstSave = result.current.saveTiers(tier("First"));
    secondSave = result.current.saveTiers(tier("Second"));
  });
  expect(api.saveTiers).toHaveBeenCalledTimes(1);
  await act(async () => { first.resolve(Response.json(ranking(1, 1))); await firstSave; });
  expect(api.saveTiers).toHaveBeenCalledTimes(2);
  expect(result.current.tiers?.[0].label).toBe("Second");
  expect(result.current.ranking).toBeNull();
  await act(async () => { second.resolve(Response.json(ranking(1, 2))); await secondSave; });
  expect(result.current.ranking?.scoredCount).toBe(2);
  expect(vi.mocked(api.saveTiers).mock.calls[1][2][0].label).toBe("Second");
});

it("retains rapid proposal edits and serializes them with tier edits", async () => {
  const first = deferred<Response>();
  const second = deferred<Response>();
  vi.mocked(api.fetchRankingCurrent).mockResolvedValue(current(1));
  vi.mocked(api.changeProposal).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  vi.mocked(api.saveTiers).mockResolvedValue(Response.json(ranking(1)));
  const { result } = renderHook(() => useRanking(1, vi.fn()));
  await act(() => result.current.refreshRankingRun());
  let save!: Promise<void>;
  await act(async () => {
    result.current.addProposal("First"); result.current.addProposal("Second");
    save = result.current.saveTiers(tier("Important"));
  });
  expect(api.changeProposal).toHaveBeenCalledTimes(1);
  expect(api.saveTiers).not.toHaveBeenCalled();
  await act(async () => { first.resolve(Response.json({ proposedDimensions: ["First"] })); });
  expect(vi.mocked(api.changeProposal).mock.calls[1][2]).toEqual({ operation: "add", text: "Second" });
  expect(result.current.rankingRun?.proposedDimensions).toEqual(["First", "Second"]);
  await act(async () => {
    second.resolve(Response.json({ proposedDimensions: ["First", "Second"] })); await save;
  });
  expect(api.saveTiers).toHaveBeenCalledOnce();
  expect(result.current.rankingRun?.proposedDimensions).toEqual(["First", "Second"]);
});

it("discards queued writes and late mutation errors after leaving an opening", async () => {
  const first = deferred<Response>();
  vi.mocked(api.fetchRankingCurrent).mockResolvedValue(current(1));
  vi.mocked(api.saveTiers).mockReturnValueOnce(first.promise);
  const onError = vi.fn();
  const { result, rerender } = renderHook(({ openingId }) => useRanking(openingId, onError), {
    initialProps: { openingId: 1 },
  });
  await act(() => result.current.refreshRankingRun());
  let firstSave!: Promise<void>;
  let secondSave!: Promise<void>;
  await act(async () => {
    firstSave = result.current.saveTiers(tier("First")); secondSave = result.current.saveTiers(tier("Second"));
  });
  rerender({ openingId: 2 });
  vi.mocked(api.fetchRankingCurrent).mockResolvedValue(current(2));
  await act(() => result.current.refreshRankingRun());
  expect(result.current.rankingRun?.analysisId).toBe(2);
  await act(async () => {
    first.resolve(Response.json({ code: "stale_analysis" }, { status: 409 }));
    await Promise.all([firstSave, secondSave]);
  });
  expect(api.saveTiers).toHaveBeenCalledOnce();
  expect(result.current.ranking).toBeNull();
  expect(result.current.staleAnalysis).toBe(false);
  expect(onError).not.toHaveBeenCalled();
});

it("does not start old-opening reads through a callback retained by an async operation", async () => {
  vi.mocked(api.fetchRankingCurrent).mockResolvedValue(current(1));
  const { result, rerender } = renderHook(({ openingId }) => useRanking(openingId, vi.fn()), {
    initialProps: { openingId: 1 },
  });
  const oldRefresh = result.current.refreshRankingRun;
  rerender({ openingId: 2 });
  await act(() => oldRefresh());
  expect(api.fetchRankingCurrent).not.toHaveBeenCalled();
});

it("reconciles a failed latest tier save without getting stuck in the queue", async () => {
  vi.mocked(api.fetchRankingCurrent).mockResolvedValue(current(1));
  vi.mocked(api.saveTiers).mockResolvedValue(Response.json({ detail: "Blocked" }, { status: 409 }));
  vi.mocked(api.fetchRankingBoard).mockResolvedValue(board(1, tier("Persisted")));
  const onError = vi.fn();
  const { result } = renderHook(() => useRanking(1, onError));
  await act(() => result.current.refreshRankingRun());
  await act(() => result.current.saveTiers(tier("Unsaved")));
  expect(onError).toHaveBeenCalledWith("Blocked");
  expect(result.current.tiers?.[0].label).toBe("Persisted");
});

it("reloads a newer analysis when the loaded ranking is stale", async () => {
  vi.mocked(api.fetchRankingCurrent).mockResolvedValueOnce(current(1)).mockResolvedValueOnce(current(2));
  vi.mocked(api.fetchRankingBoard).mockResolvedValue(board(2, tier("Current")));
  const { result } = renderHook(() => useRanking(1, vi.fn()));
  await act(() => result.current.refreshRankingRun());
  await act(async () => { expect(await result.current.reloadStaleRanking()).toBe(true); });
  expect(result.current.ranking?.analysisId).toBe(2);
});

it("adopts criteria, tiers, and ranking together when a different analysis is returned", async () => {
  vi.mocked(api.fetchRankingCurrent).mockResolvedValueOnce(current(1));
  vi.mocked(api.fetchRankingBoard).mockResolvedValueOnce(board(2, tier("Current")));
  const { result } = renderHook(() => useRanking(1, vi.fn()));
  await act(() => result.current.refreshRankingRun());
  await act(() => result.current.loadRanking());
  expect(result.current.rankingRun?.analysisId).toBe(2);
  expect(result.current.ranking?.analysisId).toBe(2);
  expect(result.current.tiers).toEqual(tier("Current"));
});

it("does not replace only the criteria of a displayed board during a lightweight refresh", async () => {
  vi.mocked(api.fetchRankingBoard).mockResolvedValueOnce(board(1));
  vi.mocked(api.fetchRankingCurrent).mockResolvedValueOnce(current(2));
  const { result } = renderHook(() => useRanking(1, vi.fn()));
  await act(() => result.current.loadRanking());
  await act(() => result.current.refreshRankingRun());
  expect(result.current.rankingRun?.analysisId).toBe(1);
  expect(result.current.ranking?.analysisId).toBe(1);
});

it("distinguishes successful absence from failed and superseded criteria reads", async () => {
  const pending = deferred<CurrentRunResponse>();
  vi.mocked(api.fetchRankingCurrent).mockReturnValueOnce(pending.promise)
    .mockResolvedValueOnce(null).mockRejectedValueOnce(new Error("offline"));
  vi.mocked(api.fetchRankingBoard).mockResolvedValue(board(1));
  const { result } = renderHook(() => useRanking(1, vi.fn()));
  let reading!: ReturnType<typeof result.current.refreshRankingRun>;
  act(() => { reading = result.current.refreshRankingRun(); });
  await act(() => result.current.loadRanking());
  await act(async () => {
    pending.resolve(current(1));
    expect(await reading).toEqual({ status: "superseded" });
  });
  await act(async () => {
    expect(await result.current.refreshRankingRun()).toEqual({ status: "loaded", run: null });
    expect(await result.current.refreshRankingRun()).toEqual({ status: "error" });
  });
  expect(result.current.ranking?.analysisId).toBe(1);
});

it("offers recovery when initial criteria fail instead of leaving ranking loading forever", async () => {
  vi.mocked(api.fetchRankingCurrent).mockRejectedValue(new Error("offline"));
  const { result } = renderHook(() => useRanking(1, vi.fn()));
  await act(async () => expect(await result.current.refreshRankingRun()).toEqual({ status: "error" }));
  expect(result.current.rankingLoadState).toBe("error");
  vi.mocked(api.fetchRankingBoard).mockResolvedValue(board(1));
  await act(() => result.current.loadRanking());
  expect(result.current.rankingLoadState).toBe("ready");
});
