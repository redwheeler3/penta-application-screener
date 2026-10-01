import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import * as api from "../api/dashboard";
import { deferred } from "../testSupport";
import { useDashboard } from "./useDashboard";

vi.mock("../api/dashboard", () => ({ fetchDashboard: vi.fn() }));
beforeEach(() => vi.resetAllMocks());

it("does not replace a new opening's dashboard with an old initial response", async () => {
  const old = deferred<Awaited<ReturnType<typeof api.fetchDashboard>>>();
  const workflow = {
    applicationsAvailable: true, screened: true, patternsDiscovered: true,
    candidatesScored: true, rankingCurrent: true,
  };
  vi.mocked(api.fetchDashboard).mockReturnValueOnce(old.promise).mockResolvedValueOnce({ workflow, coverage: {} });
  const { result, rerender } = renderHook(({ openingId }) => useDashboard(openingId), {
    initialProps: { openingId: 1 },
  });
  let initial!: Promise<void>;
  act(() => { initial = result.current.loadInitial(); });
  rerender({ openingId: 2 });
  await act(() => result.current.loadInitial());
  await act(async () => {
    old.resolve({ workflow: { ...workflow, rankingCurrent: false }, coverage: {} }); await initial;
  });
  expect(result.current.workflow.rankingCurrent).toBe(true);
  expect(result.current.loadState).toBe("ready");
});
