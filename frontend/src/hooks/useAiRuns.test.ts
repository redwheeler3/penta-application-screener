import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import * as rankingApi from "../api/ranking";
import * as screeningApi from "../api/screening";
import { useAiRuns } from "./useAiRuns";

vi.mock("../api/ranking", () => ({
  runRank: vi.fn(), scoreCurrent: vi.fn(), fetchRankEstimate: vi.fn(), fetchScoreCurrentEstimate: vi.fn(),
}));
vi.mock("../api/screening", () => ({ runScreening: vi.fn(), fetchScreeningEstimate: vi.fn() }));

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
  const { result } = renderHook(() => useAiRuns(options));
  return {
    result, options,
    run: () => mode === "screening" ? result.current.runScreening() : result.current.runRank(mode),
  };
}

beforeEach(() => vi.resetAllMocks());

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
