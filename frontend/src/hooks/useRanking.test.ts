import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import * as api from "../api/ranking";
import { deferred } from "../testSupport";
import type { CurrentRunResponse, RankingResponse, Tier } from "../types";
import { useRanking } from "./useRanking";

vi.mock("../api/ranking", () => ({
  fetchRankingCurrent: vi.fn(), fetchRanking: vi.fn(), fetchTiers: vi.fn(),
  saveTiers: vi.fn(), saveSeeds: vi.fn(),
}));

const current = (analysisId: number): CurrentRunResponse => ({
  analysisId, dimensions: [], discoveryNarrative: null, newDimensionKeys: [],
  revivedDimensionKeys: [], requestedDimensionKeys: [], keptKeys: [], proposedDimensions: [],
});
const ranking = (analysisId: number, scoredCount = 0): RankingResponse => ({
  analysisId, scoredCount, candidates: [], weights: {}, newDimensionKeys: [],
  revivedDimensionKeys: [], requestedDimensionKeys: [], keptKeys: [], proposedDimensions: [],
});
const tier = (label: string): Tier[] => [{ id: "important", label, dimensionKeys: [] }];
beforeEach(() => vi.resetAllMocks());

it("ignores old current-analysis and board responses after an opening change", async () => {
  const oldCurrent = deferred<CurrentRunResponse>();
  const oldRanking = deferred<RankingResponse>();
  vi.mocked(api.fetchRankingCurrent).mockReturnValueOnce(oldCurrent.promise).mockResolvedValueOnce(current(2));
  vi.mocked(api.fetchRanking).mockReturnValueOnce(oldRanking.promise).mockResolvedValueOnce(ranking(2));
  vi.mocked(api.fetchTiers).mockResolvedValue({ tiers: [] });
  const { result, rerender } = renderHook(({ openingId }) => useRanking(openingId, vi.fn()), {
    initialProps: { openingId: 1 },
  });
  let firstCurrent!: Promise<CurrentRunResponse | null>;
  let firstRanking!: Promise<boolean>;
  act(() => {
    firstCurrent = result.current.refreshRankingRun(); firstRanking = result.current.loadRanking();
  });
  rerender({ openingId: 2 });
  await act(async () => { await result.current.refreshRankingRun(); await result.current.loadRanking(); });
  await act(async () => {
    oldCurrent.resolve(current(1)); oldRanking.resolve(ranking(1));
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
  vi.mocked(api.saveSeeds).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  vi.mocked(api.saveTiers).mockResolvedValue(Response.json(ranking(1)));
  const { result } = renderHook(() => useRanking(1, vi.fn()));
  await act(() => result.current.refreshRankingRun());
  let save!: Promise<void>;
  await act(async () => {
    result.current.addProposal("First"); result.current.addProposal("Second");
    save = result.current.saveTiers(tier("Important"));
  });
  expect(api.saveSeeds).toHaveBeenCalledTimes(1);
  expect(api.saveTiers).not.toHaveBeenCalled();
  await act(async () => { first.resolve(Response.json({ proposedDimensions: ["First"] })); });
  expect(vi.mocked(api.saveSeeds).mock.calls[1][2].proposedDimensions).toEqual(["First", "Second"]);
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
  vi.mocked(api.fetchRanking).mockResolvedValue(ranking(1));
  vi.mocked(api.fetchTiers).mockResolvedValue({ tiers: tier("Persisted") });
  const onError = vi.fn();
  const { result } = renderHook(() => useRanking(1, onError));
  await act(() => result.current.refreshRankingRun());
  await act(() => result.current.saveTiers(tier("Unsaved")));
  expect(onError).toHaveBeenCalledWith("Blocked");
  expect(result.current.tiers?.[0].label).toBe("Persisted");
});

it("reloads a newer analysis when the loaded ranking is stale", async () => {
  vi.mocked(api.fetchRankingCurrent).mockResolvedValueOnce(current(1)).mockResolvedValueOnce(current(2));
  vi.mocked(api.fetchRanking).mockResolvedValue(ranking(2));
  vi.mocked(api.fetchTiers).mockResolvedValue({ tiers: tier("Current") });
  const { result } = renderHook(() => useRanking(1, vi.fn()));
  await act(() => result.current.refreshRankingRun());
  await act(async () => { expect(await result.current.reloadStaleRanking()).toBe(true); });
  expect(result.current.ranking?.analysisId).toBe(2);
});
