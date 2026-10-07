import { act } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { deferred, renderCommitteeHook as renderHook } from "../testSupport";
import { useAiRuns } from "./useAiRuns";

const modes = ["screening", "discover", "score-current"] as const;
type Mode = typeof modes[number];

function setup() {
  const options = {
    openingId: 1,
    ranking: {
      currentRun: { analysisId: 1, dimensions: [], proposedDimensions: ["Personal proposal"] },
      load: vi.fn().mockResolvedValue(true), setDisplayedProposals: vi.fn(), invalidateReads: vi.fn(),
    },
    notifications: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
    refreshDashboard: vi.fn(), reloadApplications: vi.fn(),
    clearSelectedApplication: vi.fn(), refreshDisplayedRanking: vi.fn(),
  };
  const hook = renderHook((props) => useAiRuns(props), { initialProps: options });
  return { ...hook, options,
    run: (mode: Mode) => mode === "screening"
      ? hook.result.current.runScreening() : hook.result.current.runRank(mode) };
}

function stalledRequest() {
  const fetchMock = vi.fn((_url: unknown, init: RequestInit) => new Promise<Response>((_resolve, reject) => {
    init.signal!.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
  }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

// Keep the actual API modules and identity client: network failures become 503
// responses there, rather than throwing from the hook's mocked API dependency.
it.each(modes.flatMap((mode) => (["reject", "timeout", "server"] as const).map((failure) => [mode, failure] as const)))(
  "reconciles uncertain %s %s failure through the actual client", async (mode, failure) => {
    vi.useFakeTimers();
    const fetchMock = failure === "timeout" ? stalledRequest() : vi.fn().mockImplementation(async () => {
      if (failure === "reject") throw new TypeError("Synthetic lost response");
      return Response.json({ detail: "Synthetic server failure" }, { status: 502 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const { options, result, run } = setup();
    let running!: Promise<void>;
    act(() => { running = run(mode); });
    await act(async () => {
      if (failure === "timeout") await vi.advanceTimersByTimeAsync(30_000);
      await running;
    });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("X-Penta-Identity")).toBe("committee:1");
    expect(options.notifications.success).not.toHaveBeenCalled();
    expect(options.notifications.error).toHaveBeenCalledOnce();
    expect(options.refreshDashboard).toHaveBeenCalledOnce();
    expect(result.current.screeningRunning || result.current.rankRunning).toBe(false);
    if (mode === "screening") {
      for (const callback of [options.reloadApplications, options.clearSelectedApplication,
        options.refreshDisplayedRanking]) expect(callback).toHaveBeenCalledOnce();
      expect(options.ranking.load).not.toHaveBeenCalled();
    } else {
      expect(options.ranking.load).toHaveBeenCalledOnce();
      // The server may have consumed them; only recovery can establish their state.
      expect(options.ranking.setDisplayedProposals.mock.calls).toEqual(mode === "discover" ? [[[]]] : []);
    }
  },
);

it.each(modes.flatMap((mode) => [403, 409].map((status) => [mode, status] as const)))(
  "does not reconcile definite %s rejection HTTP %s", async (mode, status) => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => Response.json({
      code: "run_in_progress", detail: "Synthetic definite rejection",
    }, { status })));
    const { options, run } = setup();
    await act(() => run(mode));
    expect(options.notifications.error).toHaveBeenCalledOnce();
    expect(options.refreshDashboard).not.toHaveBeenCalled();
    expect(options.ranking.load).not.toHaveBeenCalled();
    expect(options.reloadApplications).not.toHaveBeenCalled();
    expect(options.ranking.setDisplayedProposals.mock.calls).toEqual(
      mode === "discover" ? [[[]], [["Personal proposal"]]] : [],
    );
  },
);

it.each(modes)("keeps %s caller cancellation distinct from lost transport", async (mode) => {
  const fetchMock = stalledRequest();
  const { options, run, unmount } = setup();
  let running!: Promise<void>;
  act(() => { running = run(mode); });
  unmount();
  await act(async () => { await running; });
  expect((fetchMock.mock.calls[0][1] as RequestInit).signal!.aborted).toBe(true);
  expect(options.notifications.error).not.toHaveBeenCalled();
  expect(options.refreshDashboard).not.toHaveBeenCalled();
  expect(options.ranking.load).not.toHaveBeenCalled();
});

it.each(modes)("does not reconcile an old opening's uncertain %s response", async (mode) => {
  const response = deferred<Response>();
  vi.stubGlobal("fetch", vi.fn().mockReturnValue(response.promise));
  const { options, run, rerender } = setup();
  let running!: Promise<void>;
  act(() => { running = run(mode); });
  rerender({ ...options, openingId: 2 });
  options.ranking.setDisplayedProposals.mockClear();
  await act(async () => {
    response.resolve(Response.json({ detail: "Synthetic uncertain failure" }, { status: 503 }));
    await running;
  });
  expect(options.notifications.error).not.toHaveBeenCalled();
  expect(options.refreshDashboard).not.toHaveBeenCalled();
  expect(options.ranking.load).not.toHaveBeenCalled();
  expect(options.clearSelectedApplication).not.toHaveBeenCalled();
  expect(options.ranking.setDisplayedProposals).not.toHaveBeenCalled();
});
