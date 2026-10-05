import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../api/emailDelivery";
import { useEmailDeliveryStatus } from "./useEmailDeliveryStatus";

vi.mock("../api/emailDelivery", () => ({
  fetchCachedEmailDeliveryStatus: vi.fn(),
  refreshEmailDeliveryStatus: vi.fn(),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe("useEmailDeliveryStatus", () => {
  beforeEach(() => vi.resetAllMocks());

  it("makes no advisory requests until its consuming surface is visible", async () => {
    const cached = deferred<{ available: boolean; delayed: boolean }>();
    vi.mocked(api.fetchCachedEmailDeliveryStatus).mockReturnValue(cached.promise);
    const { result, rerender } = renderHook(({ enabled }) => useEmailDeliveryStatus(enabled), {
      initialProps: { enabled: false },
    });
    expect(api.fetchCachedEmailDeliveryStatus).not.toHaveBeenCalled();
    expect(api.refreshEmailDeliveryStatus).not.toHaveBeenCalled();

    rerender({ enabled: true });
    expect(api.fetchCachedEmailDeliveryStatus).toHaveBeenCalledOnce();
    const signal = vi.mocked(api.fetchCachedEmailDeliveryStatus).mock.calls[0][0];
    rerender({ enabled: false });
    expect(signal?.aborted).toBe(true);
    await act(async () => cached.resolve({ available: true, delayed: true }));
    expect(result.current).toBe(false);
    expect(api.refreshEmailDeliveryStatus).not.toHaveBeenCalled();
  });

  it("renders cached status before applying the refreshed value", async () => {
    const refresh = deferred<{ available: boolean; delayed: boolean }>();
    vi.mocked(api.fetchCachedEmailDeliveryStatus).mockResolvedValue({ available: true, delayed: true });
    vi.mocked(api.refreshEmailDeliveryStatus).mockReturnValue(refresh.promise);

    const { result } = renderHook(useEmailDeliveryStatus);
    await waitFor(() => expect(result.current).toBe(true));

    await act(async () => refresh.resolve({ available: true, delayed: false }));
    await waitFor(() => expect(result.current).toBe(false));
  });

  it("retains cached status when refresh is unavailable", async () => {
    vi.mocked(api.fetchCachedEmailDeliveryStatus).mockResolvedValue({ available: true, delayed: true });
    vi.mocked(api.refreshEmailDeliveryStatus).mockResolvedValue({ available: false, delayed: false });

    const { result } = renderHook(useEmailDeliveryStatus);

    await waitFor(() => expect(result.current).toBe(true));
  });
});
