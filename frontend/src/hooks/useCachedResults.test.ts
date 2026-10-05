import { act, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { deferred, renderCommitteeHook as renderHook } from "../testSupport";
import { useCachedResults } from "./useCachedResults";

const refresh = vi.hoisted(() => vi.fn<ReturnType<typeof import("../api/cachedResults").createApi>["refreshCachedResults"]>());
vi.mock("../api/cachedResults", () => ({ createApi: () => ({ refreshCachedResults: refresh }) }));
beforeEach(() => vi.resetAllMocks());

it("reuses cached results immediately without blocking or prompting, and refreshes changed views", async () => {
  const changed = vi.fn();
  refresh.mockResolvedValue(true);
  renderHook(() => useCachedResults(1, false, changed));
  await waitFor(() => expect(changed).toHaveBeenCalledOnce());
  expect(refresh).toHaveBeenCalledWith(1, expect.any(AbortSignal));
});

it("ignores an earlier opening's refresh and aborts it on navigation", async () => {
  const earlier = deferred<boolean>();
  refresh.mockReturnValueOnce(earlier.promise).mockResolvedValue(false);
  const changed = vi.fn();
  const { rerender } = renderHook(({ id }) => useCachedResults(id, false, changed), { initialProps: { id: 1 } });
  const signal = refresh.mock.calls[0][1];
  rerender({ id: 2 });
  expect(signal.aborted).toBe(true);
  await act(async () => earlier.resolve(true));
  expect(changed).not.toHaveBeenCalled();
  expect(refresh).toHaveBeenCalledTimes(2);
});

it("pauses background adoption with the session and suppresses late callbacks", async () => {
  const earlier = deferred<boolean>();
  refresh.mockReturnValue(earlier.promise);
  const changed = vi.fn();
  const { rerender } = renderHook(({ paused }) => useCachedResults(1, paused, changed), { initialProps: { paused: false } });
  rerender({ paused: true });
  expect(refresh.mock.calls[0][1].aborted).toBe(true);
  await act(async () => earlier.resolve(true));
  expect(changed).not.toHaveBeenCalled();
  expect(refresh).toHaveBeenCalledOnce();
});

it("quietly retains existing views on a failed refresh and retries on the next intake refresh", async () => {
  refresh.mockRejectedValueOnce(new Error("Offline")).mockResolvedValueOnce(true);
  const changed = vi.fn();
  const { result } = renderHook(() => useCachedResults(1, false, changed));
  await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
  expect(changed).not.toHaveBeenCalled();
  await act(() => result.current());
  expect(changed).toHaveBeenCalledOnce();
});
