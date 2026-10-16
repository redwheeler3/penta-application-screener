import { afterEach, describe, expect, it, vi } from "vitest";

import { FlyWatchdog } from "../src/index";

function watchdog(machines: unknown[], alertStatus = 204) {
  const values = new Map<string, number>();
  const storage = {
    get: vi.fn(async (key: string) => values.get(key)),
    put: vi.fn(async (key: string, value: number) => { values.set(key, value); }),
    setAlarm: vi.fn(async () => {}),
  };
  const fetch = vi.fn(async (url: string) => url.startsWith("https://api.machines.dev/")
    ? Response.json(machines)
    : new Response(null, { status: alertStatus }));
  vi.stubGlobal("fetch", fetch);
  vi.spyOn(console, "error").mockImplementation(() => {});
  const instance = new FlyWatchdog({ storage } as unknown as DurableObjectState, {
    WATCHDOG: {} as DurableObjectNamespace,
    FLY_APP_NAME: "test-app",
    FLY_API_TOKEN: "test-token",
    ALERT_WEBHOOK_URL: "https://alerts.example.test/",
  });
  return { instance, storage, fetch };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("watchdog alarms", () => {
  const suspended = {
    id: "machine-id",
    state: "suspended",
    host_status: "ok",
    config: { metadata: { fly_process_group: "app" } },
  };
  const unreachable = {
    ...suspended,
    host_status: "unreachable",
    config: null,
    incomplete_config: suspended.config,
  };

  it("alerts on an unavailable host, schedules another poll, and never tries a restart", async () => {
    const { instance, storage, fetch } = watchdog([unreachable]);
    await expect(instance.alarm()).rejects.toThrow(/host.*unreachable/);
    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      "https://api.machines.dev/v1/apps/test-app/machines",
      "https://alerts.example.test/",
    ]);
    expect(storage.setAlarm).toHaveBeenCalledOnce();
    expect(console.error).toHaveBeenCalledWith(expect.stringMatching(/host.*unreachable/));

    // The next poll still logs the outage, but a delivered alert has a cooldown.
    await expect(instance.alarm()).rejects.toThrow(/host.*unreachable/);
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it("retries alert delivery next poll when the webhook fails", async () => {
    const { instance, storage, fetch } = watchdog([unreachable], 503);
    await expect(instance.alarm()).rejects.toThrow(/host.*unreachable/);
    await expect(instance.alarm()).rejects.toThrow(/host.*unreachable/);
    expect(fetch).toHaveBeenCalledTimes(4);
    expect(storage.put).not.toHaveBeenCalled();
    expect(storage.setAlarm).toHaveBeenCalledTimes(2);
  });

  it("alerts when no production machine can be identified", async () => {
    const { instance, fetch } = watchdog([]);
    await expect(instance.alarm()).rejects.toThrow(/found 0/);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("leaves a healthy suspended machine asleep without an alert", async () => {
    const { instance, storage, fetch } = watchdog([suspended]);
    await instance.alarm();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(storage.setAlarm).toHaveBeenCalledOnce();
    expect(console.error).not.toHaveBeenCalled();
  });
});
