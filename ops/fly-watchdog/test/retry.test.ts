import { describe, expect, it, vi } from "vitest";

import { retryOnce } from "../src/retry";

describe("retryOnce", () => {
  it("returns without waiting when the first attempt succeeds", async () => {
    const operation = vi.fn().mockResolvedValue("ok");
    const wait = vi.fn().mockResolvedValue(undefined);

    await expect(retryOnce(operation, 1_000, wait)).resolves.toBe("ok");
    expect(operation).toHaveBeenCalledTimes(1);
    expect(wait).not.toHaveBeenCalled();
  });

  it("waits and retries once after a failed first attempt", async () => {
    const operation = vi.fn().mockRejectedValueOnce(new Error("transient")).mockResolvedValue("ok");
    const wait = vi.fn().mockResolvedValue(undefined);

    await expect(retryOnce(operation, 1_000, wait)).resolves.toBe("ok");
    expect(operation).toHaveBeenCalledTimes(2);
    expect(wait).toHaveBeenCalledOnce();
    expect(wait).toHaveBeenCalledWith(1_000);
  });

  it("returns the final error after exactly two failed attempts", async () => {
    const finalError = new Error("still unavailable");
    const operation = vi.fn().mockRejectedValueOnce(new Error("transient")).mockRejectedValue(finalError);
    const wait = vi.fn().mockResolvedValue(undefined);

    await expect(retryOnce(operation, 1_000, wait)).rejects.toBe(finalError);
    expect(operation).toHaveBeenCalledTimes(2);
  });
});
