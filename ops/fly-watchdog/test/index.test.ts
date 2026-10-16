import { afterEach, describe, expect, it, vi } from "vitest";

import { FlyWatchdog } from "../src/index";

function watchdog(machines: unknown[], alertStatus = 204) {
  const values = new Map<string, unknown>();
  const control = { machines, alertStatus, lookupStatus: 200 };
  const storage = {
    get: vi.fn(async (key: string) => structuredClone(values.get(key))),
    put: vi.fn(async (key: string, value: unknown) => { values.set(key, structuredClone(value)); }),
    delete: vi.fn(async (key: string) => values.delete(key)),
    setAlarm: vi.fn(async () => {}),
    deleteAlarm: vi.fn(async () => {}),
  };
  const fetch = vi.fn(async (url: string, _init?: RequestInit) => {
    if (url.endsWith("/machines")) return Response.json(control.machines, { status: control.lookupStatus });
    return new Response(null, { status: url.endsWith("/restart") ? 204 : control.alertStatus });
  });
  vi.stubGlobal("fetch", fetch);
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.spyOn(console, "log").mockImplementation(() => {});
  const env = {
    WATCHDOG: {} as DurableObjectNamespace,
    FLY_APP_NAME: "test-app",
    FLY_API_TOKEN: "test-token",
    ALERT_WEBHOOK_URL: "https://alerts.example.test/",
    WATCHDOG_ENABLED: "true",
  };
  const createInstance = () => new FlyWatchdog({ storage } as unknown as DurableObjectState, env);
  const alerts = () => fetch.mock.calls.filter(([url]) => url === env.ALERT_WEBHOOK_URL)
    .map(([, init]) => JSON.parse(init!.body as string).content as string);
  return { instance: createInstance(), createInstance, storage, fetch, control, alerts, env };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
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

  it("alerts once for a continuous outage while continuing polls and logs", async () => {
    vi.useFakeTimers();
    const { instance, storage, fetch, control, alerts } = watchdog([unreachable]);
    await instance.alarm();
    vi.setSystemTime(Date.now() + 24 * 60 * 60_000);
    control.machines = [{ ...unreachable, host_status: "unknown" }];
    await instance.alarm();
    control.machines = [unreachable];
    await instance.alarm();
    expect(alerts()).toHaveLength(1);
    expect(fetch.mock.calls.some(([url]) => url.endsWith("/restart"))).toBe(false);
    expect(storage.setAlarm).toHaveBeenCalledTimes(3);
    expect(console.error).toHaveBeenCalledTimes(3);
  });

  it("preserves delivered alerts and recovery confirmations across instance recreation", async () => {
    const { instance, createInstance, control, alerts } = watchdog([unreachable]);
    await instance.alarm();
    await createInstance().alarm();
    expect(alerts()).toHaveLength(1);
    control.machines = [suspended];
    await createInstance().alarm();
    expect(alerts()).toHaveLength(1);
    await createInstance().alarm();
    expect(alerts()).toHaveLength(2);
  });

  it("announces confirmed suspended recovery once, then re-arms for a new outage", async () => {
    const { instance, control, alerts } = watchdog([unreachable]);
    await instance.alarm();
    control.machines = [suspended];
    await instance.alarm();
    expect(alerts()).toHaveLength(1);
    await instance.alarm();
    await instance.alarm();
    expect(alerts()).toHaveLength(2);
    expect(alerts()[1]).toMatch(/host reachable again.*suspended; website availability has not been tested/);
    control.machines = [unreachable];
    await instance.alarm();
    expect(alerts()).toHaveLength(3);
  });

  it("announces running recovery only with passing service checks", async () => {
    const { instance, control, alerts } = watchdog([unreachable]);
    await instance.alarm();
    control.machines = [{ ...suspended, state: "started", checks: [{ status: "warning" }] }];
    await instance.alarm();
    await instance.alarm();
    expect(alerts()).toHaveLength(1);
    control.machines = [{ ...suspended, state: "started", checks: [{ status: "passing" }] }];
    await instance.alarm();
    await instance.alarm();
    expect(alerts()[1]).toContain("running and Fly service checks are passing");
  });

  it("requires fresh confirmations after an outage flicker", async () => {
    const { instance, control, alerts } = watchdog([unreachable]);
    await instance.alarm();
    control.machines = [suspended];
    await instance.alarm();
    control.machines = [unreachable];
    await instance.alarm();
    control.machines = [suspended];
    await instance.alarm();
    expect(alerts()).toHaveLength(1);
    await instance.alarm();
    expect(alerts()).toHaveLength(2);
  });

  it("does not count failed lookups or watchdog pauses as recovery evidence", async () => {
    const { instance, control, alerts, env } = watchdog([unreachable]);
    await instance.alarm();
    control.machines = [suspended];
    await instance.alarm();
    control.lookupStatus = 401;
    await expect(instance.alarm()).rejects.toThrow(/HTTP 401/);
    control.lookupStatus = 200;
    await instance.alarm();
    expect(alerts().filter((message) => message.includes("reachable again"))).toHaveLength(0);
    env.WATCHDOG_ENABLED = "false";
    await instance.alarm();
    env.WATCHDOG_ENABLED = "true";
    await instance.alarm();
    expect(alerts().filter((message) => message.includes("reachable again"))).toHaveLength(0);
    await instance.alarm();
    expect(alerts().filter((message) => message.includes("reachable again"))).toHaveLength(1);
  });

  it("requires two confirmations for the same recovery machine", async () => {
    const { instance, control, alerts } = watchdog([unreachable]);
    await instance.alarm();
    control.machines = [suspended];
    await instance.alarm();
    control.machines = [{ ...suspended, id: "replacement" }];
    await instance.alarm();
    expect(alerts()).toHaveLength(1);
    await instance.alarm();
    expect(alerts()[1]).toContain("replacement");
  });

  it("retries a failed outage notification, then suppresses repeats after delivery", async () => {
    const { instance, control, alerts } = watchdog([unreachable], 503);
    await instance.alarm();
    control.alertStatus = 204;
    await instance.alarm();
    await instance.alarm();
    expect(alerts()).toHaveLength(2);
  });

  it("retries failed recovery delivery without repeating the outage alert", async () => {
    const { instance, control, alerts } = watchdog([unreachable]);
    await instance.alarm();
    control.machines = [suspended];
    control.alertStatus = 503;
    await instance.alarm();
    await instance.alarm();
    control.machines = [unreachable];
    await instance.alarm();
    expect(alerts().filter((message) => message.includes("is unreachable"))).toHaveLength(1);
    control.machines = [suspended];
    control.alertStatus = 204;
    await instance.alarm();
    await instance.alarm();
    await instance.alarm();
    expect(alerts()).toHaveLength(3);
  });

  it("does not send an unpaired recovery when outage delivery never succeeded", async () => {
    const { instance, control, alerts } = watchdog([unreachable], 503);
    await instance.alarm();
    control.machines = [suspended];
    control.alertStatus = 204;
    await instance.alarm();
    await instance.alarm();
    expect(alerts()).toHaveLength(1);
  });

  it("alerts when no production machine can be identified", async () => {
    const { instance, alerts } = watchdog([]);
    await expect(instance.alarm()).rejects.toThrow(/found 0/);
    expect(alerts()).toHaveLength(1);
  });

  it("leaves a healthy suspended machine asleep without an alert", async () => {
    const { instance, storage, fetch, alerts } = watchdog([suspended]);
    await instance.alarm();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(alerts()).toHaveLength(0);
    expect(storage.setAlarm).toHaveBeenCalledOnce();
    expect(console.error).not.toHaveBeenCalled();
  });
});
