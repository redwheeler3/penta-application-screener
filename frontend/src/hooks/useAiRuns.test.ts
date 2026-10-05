import { act } from "@testing-library/react";
import { renderCommitteeHook as renderHook, deferred } from "../testSupport";
import { beforeEach, expect, it, vi } from "vitest";
import { useAiRuns } from "./useAiRuns";
import type { CurrentRunResponse } from "../types";

const rankingApi = vi.hoisted(() => ({
  runRank: vi.fn<ReturnType<typeof import("../api/ranking").createApi>["runRank"]>(),
  scoreCurrent: vi.fn<ReturnType<typeof import("../api/ranking").createApi>["scoreCurrent"]>(),
  fetchRankEstimate: vi.fn<ReturnType<typeof import("../api/ranking").createApi>["fetchRankEstimate"]>(),
  fetchScoreCurrentEstimate: vi.fn<ReturnType<typeof import("../api/ranking").createApi>["fetchScoreCurrentEstimate"]>(),
}));
const screeningApi = vi.hoisted(() => ({
  runScreening: vi.fn<ReturnType<typeof import("../api/screening").createApi>["runScreening"]>(),
  fetchScreeningEstimate: vi.fn<ReturnType<typeof import("../api/screening").createApi>["fetchScreeningEstimate"]>(),
}));

vi.mock("../api/ranking", () => ({
  createApi: () => rankingApi,
}));
vi.mock("../api/screening", () => ({
  createApi: () => screeningApi,
}));

type Mode = "screening" | "discover" | "score-current";
const modes: Mode[] = ["screening", "discover", "score-current"];

function setup(mode: Mode, events: unknown[], finalNewline = true) {
  const response = new Response(events.map((event) => JSON.stringify(event)).join("\n") + (finalNewline ? "\n" : ""));
  const request = mode === "screening" ? screeningApi.runScreening
    : mode === "discover" ? rankingApi.runRank : rankingApi.scoreCurrent;
  vi.mocked(request).mockResolvedValue(response);
  const options = {
    openingId: 1,
    ranking: {
      currentRun: null, refreshCurrentRun: vi.fn().mockResolvedValue(null),
      load: vi.fn().mockResolvedValue(true), setDisplayedProposals: vi.fn(),
    },
    notifications: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
    refreshDashboard: vi.fn(), reloadApplications: vi.fn(), clearSelectedApplication: vi.fn(),
  };
  const { result, unmount } = renderHook(() => useAiRuns(options));
  return {
    result, options, unmount,
    run: () => mode === "screening" ? result.current.runScreening() : result.current.runRank(mode),
  };
}

beforeEach(() => vi.resetAllMocks());

it.each(modes)("cancels pending %s work when the authenticated workspace closes", async (mode) => {
  const { options, run, unmount } = setup(mode, []);
  const pending = deferred<Response>();
  const request = mode === "screening" ? screeningApi.runScreening
    : mode === "discover" ? rankingApi.runRank : rankingApi.scoreCurrent;
  vi.mocked(request).mockReturnValue(pending.promise);
  let running!: Promise<void>;
  act(() => { running = run(); });
  const signal = vi.mocked(request).mock.calls[0][1]!;
  unmount();
  expect(signal.aborted).toBe(true);
  await act(async () => { pending.resolve(new Response('{"type":"summary","dimensions":1,"scored":1}\n')); await running; });
  expect(options.notifications.success).not.toHaveBeenCalled();
  expect(options.notifications.error).not.toHaveBeenCalled();
  expect(options.refreshDashboard).not.toHaveBeenCalled();
});

it.each(modes)("reports an interrupted %s run without claiming completion", async (mode) => {
  const { result, options, run } = setup(mode, [{
    type: "progress", phase: mode === "screening" ? "screen" : "scores", processed: 1, total: 2,
  }]);
  await act(run);
  expect(options.notifications.error).toHaveBeenCalledOnce();
  expect(options.notifications.error.mock.calls[0][0]).toContain("interrupted before completion was confirmed");
  expect(options.notifications.success).not.toHaveBeenCalled();
  expect(result.current.screeningRunning).toBe(false);
  expect(result.current.rankRunning).toBe(false);
  expect(options.refreshDashboard).toHaveBeenCalledOnce();
});

it.each(modes)("accepts a final %s summary without a newline", async (mode) => {
  const summary = mode === "screening"
    ? { type: "summary", analyzed: 1, cached: 0, flagged: 0, failed: 0, totalCostUsd: 0.01 }
    : { type: "summary", dimensions: 2, scored: 1, failed: 0, totalCostUsd: 0.01 };
  const { options, run } = setup(mode, [summary], false);
  await act(run);
  expect(options.notifications.success).toHaveBeenCalledOnce();
  expect(options.notifications.error).not.toHaveBeenCalled();
});

it.each(modes)("preserves a reported fatal %s error without adding an interruption error", async (mode) => {
  const { options, run } = setup(mode, [{ type: "error", phase: "criteria", message: "Synthetic failure." }]);
  await act(run);
  expect(options.notifications.error).toHaveBeenCalledExactlyOnceWith("Synthetic failure.");
  expect(options.notifications.success).not.toHaveBeenCalled();
});

it("requires a screening summary after per-applicant errors", async () => {
  const { options, run } = setup("screening", [{
    type: "item_error", phase: "screen", applicationId: 1, message: "Synthetic item failure.",
  }]);
  await act(run);
  expect(options.notifications.error.mock.calls[0][0]).toContain("interrupted");
  expect(options.notifications.success).not.toHaveBeenCalled();
});

it.each(["discover", "score-current"] as const)("releases %s controls before the derived board refresh finishes", async (mode) => {
  const { result, options, run } = setup(mode, [{
    type: "summary", dimensions: 2, scored: 1, failed: 0, totalCostUsd: 0.01,
  }]);
  const board = deferred<boolean>();
  options.ranking.load.mockReturnValue(board.promise);
  await act(run);
  expect(result.current.rankRunning).toBe(false);
  expect(result.current.rankRefreshing).toBe(true);
  expect(options.ranking.load).toHaveBeenCalledOnce();
  expect(options.ranking.refreshCurrentRun).not.toHaveBeenCalled();
  await act(async () => { board.resolve(true); });
  expect(result.current.rankRefreshing).toBe(false);
});

it.each([false, true])("does not restore an earlier opening's proposals after navigation (return=%s)", async (returnToOpening) => {
  const pending = deferred<Response>();
  vi.mocked(rankingApi.runRank).mockReturnValue(pending.promise);
  const setDisplayedProposals = vi.fn();
  const initial = {
    openingId: 1,
    ranking: { currentRun: { proposedDimensions: ["A proposal"] } as CurrentRunResponse,
      load: vi.fn().mockResolvedValue(true), setDisplayedProposals },
    notifications: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
    refreshDashboard: vi.fn(), reloadApplications: vi.fn(), clearSelectedApplication: vi.fn(),
  };
  const { result, rerender } = renderHook((options) => useAiRuns(options), { initialProps: initial });
  let running!: Promise<void>;
  act(() => { running = result.current.runRank("discover"); });
  rerender({ ...initial, openingId: 2 });
  if (returnToOpening) rerender(initial);
  setDisplayedProposals.mockClear();
  await act(async () => { pending.resolve(Response.json({ detail: "Synthetic failure" }, { status: 409 })); await running; });
  expect(setDisplayedProposals).not.toHaveBeenCalled();
  expect(result.current.rankRunning).toBe(false);
});

it("does not close a new opening's candidate when earlier screening completes", async () => {
  const pending = deferred<Response>();
  vi.mocked(screeningApi.runScreening).mockReturnValue(pending.promise);
  const initial = {
    openingId: 1, ranking: { currentRun: null, load: vi.fn().mockResolvedValue(true), setDisplayedProposals: vi.fn() },
    notifications: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
    refreshDashboard: vi.fn(), reloadApplications: vi.fn(), clearSelectedApplication: vi.fn(),
  };
  const { result, rerender } = renderHook((options) => useAiRuns(options), { initialProps: initial });
  let running!: Promise<void>;
  act(() => { running = result.current.runScreening(); });
  rerender({ ...initial, openingId: 2 });
  await act(async () => {
    pending.resolve(new Response(JSON.stringify({ type: "summary", analyzed: 1, cached: 0, flagged: 0, failed: 0, totalCostUsd: 0 })));
    await running;
  });
  expect(initial.clearSelectedApplication).not.toHaveBeenCalled();
  expect(initial.reloadApplications).not.toHaveBeenCalled();
  expect(initial.refreshDashboard).not.toHaveBeenCalled();
  expect(result.current.screeningRunning).toBe(false);
});
