import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useFetchResource } from "./useFetchResource";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe("useFetchResource", () => {
  it("loads, reports failure, and retries in place", async () => {
    const onError = vi.fn();
    const fetcher = vi.fn<() => Promise<string>>()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce("ready");
    const { result } = renderHook(() => useFetchResource(fetcher, { onError }));

    await waitFor(() => expect(result.current.state).toBe("error"));
    expect(onError).toHaveBeenCalledOnce();

    await act(() => result.current.reload());
    expect(result.current.state).toBe("ready");
    expect(result.current.data).toBe("ready");
  });

  it("reloads for a changed key and ignores the superseded response", async () => {
    const first = deferred<string>();
    const second = deferred<string>();
    const fetcher = vi.fn<(key: number) => Promise<string>>()
      .mockImplementation((key) => key === 1 ? first.promise : second.promise);
    const { result, rerender } = renderHook(
      ({ key }) => useFetchResource(() => fetcher(key), { reloadKey: key }),
      { initialProps: { key: 1 } },
    );

    rerender({ key: 2 });
    await act(async () => second.resolve("second"));
    await waitFor(() => expect(result.current.data).toBe("second"));

    await act(async () => first.resolve("first"));
    expect(result.current.data).toBe("second");
  });
});
