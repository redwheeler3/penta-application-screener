import { act } from "@testing-library/react";
import { renderCommitteeHook as renderHook, deferred } from "../testSupport";
import { beforeEach, expect, it, vi } from "vitest";
import { useDashboard } from "./useDashboard";
import { publicClient } from "../api/client";

const api = vi.hoisted(() => ({
  fetchDashboard: vi.fn<ReturnType<typeof import("../api/dashboard").createApi>["fetchDashboard"]>(),
}));

vi.mock("../api/dashboard", () => ({
  createApi: () => api,
}));
beforeEach(() => vi.resetAllMocks());

const emptyWorkflow = {
  applicationsAvailable: false, screened: false, patternsDiscovered: false,
  candidatesScored: false, rankingCurrent: false,
};

it("uses the supported unscoped dashboard URL", async () => {
  const actual = await vi.importActual<typeof import("../api/dashboard")>("../api/dashboard");
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ analysisId: null, workflow: emptyWorkflow, coverage: {} }));
  try {
    await actual.createApi(publicClient).fetchDashboard(null);
    expect(fetch.mock.calls[0][0]).toMatch(/\/dashboard$/);
  } finally { fetch.mockRestore(); }
});

it("loads global actions without an opening and fences the preceding opening", async () => {
  const old = deferred<Awaited<ReturnType<typeof api.fetchDashboard>>>();
  const actions = { overdueOpeningsNeedingDecision: [], queuedEmailCount: 2, quotaBlockedEmailCount: 0,
    recentFailedEmailCount: 1, oldestQueuedEmailAt: null, newestQueuedEmailAt: null, lastEmailAttemptAt: null };
  api.fetchDashboard.mockReturnValueOnce(old.promise).mockResolvedValueOnce({
    analysisId: null, workflow: emptyWorkflow, coverage: {}, adminActions: actions,
  });
  const { result, rerender } = renderHook(({ openingId }) => useDashboard(openingId), {
    initialProps: { openingId: 1 as number | null },
  });
  let initial!: Promise<void>;
  act(() => { initial = result.current.loadInitial(); });
  rerender({ openingId: null });
  await act(() => result.current.loadInitial());
  await act(async () => { old.resolve({ analysisId: 1, workflow: { ...emptyWorkflow, applicationsAvailable: true }, coverage: {} }); await initial; });
  expect(api.fetchDashboard).toHaveBeenLastCalledWith(null);
  expect(result.current).toMatchObject({ loadState: "ready", workflow: emptyWorkflow, coverage: {}, adminActions: actions });
});

it("clears a previous opening's workflow while an unscoped load recovers", async () => {
  api.fetchDashboard.mockResolvedValueOnce({ analysisId: 1, workflow: { ...emptyWorkflow, rankingCurrent: true }, coverage: {} });
  const { result, rerender } = renderHook(({ openingId }) => useDashboard(openingId), {
    initialProps: { openingId: 1 as number | null },
  });
  await act(() => result.current.loadInitial());
  const unscoped = deferred<Awaited<ReturnType<typeof api.fetchDashboard>>>();
  api.fetchDashboard.mockReturnValueOnce(unscoped.promise);
  rerender({ openingId: null });
  let loading!: Promise<void>;
  act(() => { loading = result.current.loadInitial(); });
  expect(result.current.workflow).toEqual(emptyWorkflow);
  expect(result.current.loadState).toBe("loading");
  await act(async () => { unscoped.resolve({ analysisId: null, workflow: emptyWorkflow, coverage: {} }); await loading; });
  api.fetchDashboard.mockRejectedValueOnce(new Error("Offline"));
  await act(() => result.current.refresh());
  expect(result.current.loadState).toBe("ready");
  expect(result.current.workflow).toEqual(emptyWorkflow);
});

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


it.each(["initial-first", "refresh-first"])("settles replaced initial loading after a failed refresh (%s)", async (order) => {
  const initial = deferred<Awaited<ReturnType<typeof api.fetchDashboard>>>();
  const refreshed = deferred<Awaited<ReturnType<typeof api.fetchDashboard>>>();
  api.fetchDashboard.mockReturnValueOnce(initial.promise).mockReturnValueOnce(refreshed.promise);
  const { result } = renderHook(() => useDashboard(1));
  let loading!: Promise<void>;
  let refreshing!: Promise<void>;
  act(() => { loading = result.current.loadInitial(); refreshing = result.current.refresh(); });
  const settleInitial = async () => { initial.resolve({ analysisId: null, coverage: {}, workflow: {
    applicationsAvailable: true, screened: false, patternsDiscovered: false, candidatesScored: false, rankingCurrent: false,
  } }); await loading; };
  const settleRefresh = async () => { refreshed.reject(new Error("Offline")); await refreshing; };
  await act(order === "initial-first" ? settleInitial : settleRefresh);
  await act(order === "initial-first" ? settleRefresh : settleInitial);
  expect(result.current.loadState).toBe("error");
  api.fetchDashboard.mockResolvedValue({ analysisId: null, coverage: {}, workflow: {
    applicationsAvailable: true, screened: false, patternsDiscovered: false, candidatesScored: false, rankingCurrent: false,
  } });
  await act(() => result.current.refresh());
  expect(result.current.loadState).toBe("ready");
  api.fetchDashboard.mockRejectedValue(new Error("Offline again"));
  await act(() => result.current.refresh());
  expect(result.current.loadState).toBe("ready");
  expect(result.current.workflow.applicationsAvailable).toBe(true);
});
