import { act } from "@testing-library/react";
import { renderCommitteeHook as renderHook, deferred } from "../testSupport";
import { beforeEach, expect, it, vi } from "vitest";
import { useDashboard } from "./useDashboard";

const api = vi.hoisted(() => ({
  fetchDashboard: vi.fn<ReturnType<typeof import("../api/dashboard").createApi>["fetchDashboard"]>(),
}));

vi.mock("../api/dashboard", () => ({
  createApi: () => api,
}));
beforeEach(() => vi.resetAllMocks());

it("does not replace a new opening's dashboard with an old initial response", async () => {
  const old = deferred<Awaited<ReturnType<typeof api.fetchDashboard>>>();
  const workflow = {
    applicationsAvailable: true, screened: true, patternsDiscovered: true,
    candidatesScored: true, rankingCurrent: true,
  };
  vi.mocked(api.fetchDashboard).mockReturnValueOnce(old.promise).mockResolvedValueOnce({ analysisId: 2, workflow, coverage: {} });
  const observed = vi.fn();
  const { result, rerender } = renderHook(({ openingId }) => useDashboard(openingId, observed), {
    initialProps: { openingId: 1 },
  });
  let initial!: Promise<void>;
  act(() => { initial = result.current.loadInitial(); });
  rerender({ openingId: 2 });
  await act(() => result.current.loadInitial());
  await act(async () => {
    old.resolve({ analysisId: 1, workflow: { ...workflow, rankingCurrent: false }, coverage: {} }); await initial;
  });
  expect(result.current.workflow.rankingCurrent).toBe(true);
  expect(result.current.loadState).toBe("ready");
  expect(observed).toHaveBeenCalledExactlyOnceWith(2);
});
