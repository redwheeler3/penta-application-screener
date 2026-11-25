import { afterEach, describe, expect, it, vi } from "vitest";

import { FlyWatchdog } from "../src/index";

function watchdog(machines: unknown[], alertStatus = 204) {
  const values = new Map<string, unknown>();
  const control = {
    machines, alertStatus, brokenBodies: 0, lookupStatus: 200, lookupError: null as Error | null,
    restartStatus: 204, restartError: null as Error | null,
  };
  const storage = {
    get: vi.fn(async (key: string) => structuredClone(values.get(key))),
    put: vi.fn(async (key: string, value: unknown) => { values.set(key, structuredClone(value)); }),
    delete: vi.fn(async (key: string) => values.delete(key)),
    setAlarm: vi.fn(async () => {}),
    deleteAlarm: vi.fn(async () => {}),
  };
  const fetch = vi.fn(async (url: string, _init?: RequestInit) => {
    if (url.endsWith("/machines")) {
      if (control.lookupError) throw control.lookupError;
      if (control.brokenBodies > 0) {
        control.brokenBodies--;
        return new Response(new ReadableStream({ start(c) { c.error(new TypeError("Disconnected response body")); } }));
      }
      return Response.json(control.machines, { status: control.lookupStatus });
    }
    if (url.endsWith("/restart")) {
      if (control.restartError) throw control.restartError;
      return new Response(null, { status: control.restartStatus });
    }
    return new Response(null, { status: control.alertStatus });
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

  // Lookup retries wait one second inside each poll; no real network or sleep is used.
  async function failedLookupPoll(instance: FlyWatchdog) {
    const poll = instance.alarm();
    await vi.advanceTimersByTimeAsync(1_000);
    await expect(poll).resolves.toBeUndefined();
  }

  it("retries an interrupted lookup body and requires two exhausted polls to alert", async () => {
    vi.useFakeTimers();
    const { instance, control, alerts, fetch } = watchdog([suspended]);
    control.brokenBodies = 1;
    await failedLookupPoll(instance);
    expect(fetch.mock.calls.filter(([url]) => url.endsWith("/machines"))).toHaveLength(2);
    expect(alerts()).toEqual([]);
    control.brokenBodies = 4;
    await failedLookupPoll(instance);
    expect(alerts()).toEqual([]);
    await failedLookupPoll(instance);
    expect(alerts()).toHaveLength(1);
    expect(alerts()[0]).toContain("two consecutive polls");
  });

  it("waits for the next scheduled host observation and clears isolated failures silently", async () => {
    vi.useFakeTimers();
    const { instance, control, alerts, storage } = watchdog([unreachable]);
    const startedAt = Date.now();
    await instance.alarm();
    expect(alerts()).toEqual([]);
    expect(storage.setAlarm).toHaveBeenLastCalledWith(startedAt + 30_000);
    vi.setSystemTime(startedAt + 30_000);
    control.machines = [suspended];
    await instance.alarm();
    control.machines = [unreachable];
    await instance.alarm();
    expect(alerts()).toEqual([]);
    await instance.alarm();
    expect(alerts()).toEqual([
      "Fly watchdog: Host unreachable for machine machine-id (last state: suspended).",
    ]);
  });

  it("does not erase a pending host failure when a lookup fails", async () => {
    vi.useFakeTimers();
    const { instance, control, alerts } = watchdog([unreachable]);
    await instance.alarm();
    control.lookupStatus = 503;
    await failedLookupPoll(instance);
    control.lookupStatus = 200;
    await instance.alarm();
    expect(alerts()).toHaveLength(1);
    expect(alerts()[0]).toContain("Host unreachable");
  });

  it("requires fresh host failure confirmation after a pause", async () => {
    const { instance, env, alerts } = watchdog([unreachable]);
    await instance.alarm();
    env.WATCHDOG_ENABLED = "false";
    await instance.alarm();
    env.WATCHDOG_ENABLED = "true";
    await instance.alarm();
    expect(alerts()).toEqual([]);
    await instance.alarm();
    expect(alerts()).toHaveLength(1);
  });

  it("does not clear pending host failure when host status is missing", async () => {
    const { instance, control, alerts } = watchdog([unreachable]);
    await instance.alarm();
    control.machines = [{ ...suspended, host_status: undefined }];
    await instance.alarm();
    control.machines = [unreachable];
    await instance.alarm();
    expect(alerts()).toHaveLength(1);
  });

  it.each(["timeout", "HTTP 503"])("announces persistent lookup failure once: %s", async (failure) => {
    vi.useFakeTimers();
    const { instance, createInstance, control, fetch, alerts, storage } = watchdog([suspended]);
    if (failure === "timeout") control.lookupError = new Error("The operation was aborted due to timeout");
    else control.lookupStatus = 503;
    const startedAt = Date.now();
    await failedLookupPoll(instance);
    expect(alerts()).toEqual([]);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(storage.setAlarm).toHaveBeenLastCalledWith(startedAt + 30_000);
    vi.setSystemTime(startedAt + 30_000);
    await failedLookupPoll(createInstance());
    expect(alerts()).toHaveLength(1);
    expect(alerts()[0]).toMatch(/^Fly watchdog: Unable to check machine status on two consecutive polls/);
    expect(alerts()[0]).toContain("Website status unknown");
    expect(alerts()[0]).toContain(failure);
    vi.setSystemTime(startedAt + 24 * 60 * 60_000);
    await failedLookupPoll(createInstance());
    expect(alerts()).toHaveLength(1);
    expect(storage.setAlarm).toHaveBeenCalledTimes(3);
    expect(console.error).toHaveBeenCalledTimes(3);
  });

  it("clears an isolated failed lookup without sending an outage or recovery alert", async () => {
    vi.useFakeTimers();
    const { instance, control, alerts } = watchdog([suspended]);
    control.lookupStatus = 503;
    await failedLookupPoll(instance);
    control.lookupStatus = 200;
    await instance.alarm();
    control.lookupStatus = 503;
    await failedLookupPoll(instance);
    expect(alerts()).toEqual([]);
  });

  it("stays quiet when the retry within a poll succeeds", async () => {
    vi.useFakeTimers();
    const { instance, fetch, alerts } = watchdog([suspended]);
    fetch.mockRejectedValueOnce(new Error("temporary connection failure"));
    await failedLookupPoll(instance);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(alerts()).toEqual([]);
  });

  it("confirms lookup recovery across instances, handles flicker, and re-arms notifications", async () => {
    vi.useFakeTimers();
    const { instance, createInstance, control, alerts } = watchdog([suspended]);
    control.lookupStatus = 503;
    await failedLookupPoll(instance);
    await failedLookupPoll(instance);
    control.lookupStatus = 200;
    await createInstance().alarm();
    expect(alerts()).toHaveLength(1);
    control.lookupStatus = 503;
    await failedLookupPoll(createInstance());
    control.lookupStatus = 200;
    await createInstance().alarm();
    expect(alerts()).toHaveLength(1);
    await createInstance().alarm();
    expect(alerts()[1]).toBe(
      "Fly watchdog: Machine status lookups are working again. Website availability has not been tested.",
    );
    control.lookupStatus = 503;
    await failedLookupPoll(instance);
    expect(alerts()).toHaveLength(2);
    await failedLookupPoll(instance);
    expect(alerts()).toHaveLength(3);
  });

  it("resets lookup confirmations across pauses and permanent errors", async () => {
    vi.useFakeTimers();
    const { instance, control, env, alerts } = watchdog([suspended]);
    control.lookupStatus = 503;
    await failedLookupPoll(instance);
    env.WATCHDOG_ENABLED = "false";
    await instance.alarm();
    env.WATCHDOG_ENABLED = "true";
    await failedLookupPoll(instance);
    expect(alerts()).toHaveLength(0);
    await failedLookupPoll(instance);
    control.lookupStatus = 200;
    await instance.alarm();
    control.lookupStatus = 401;
    await instance.alarm();
    control.lookupStatus = 200;
    await instance.alarm();
    expect(alerts()).toHaveLength(2); // Lookup outage, then immediate authentication error.
    env.WATCHDOG_ENABLED = "false";
    await instance.alarm();
    env.WATCHDOG_ENABLED = "true";
    await instance.alarm();
    expect(alerts()).toHaveLength(2);
    await instance.alarm();
    expect(alerts()).toHaveLength(3);
    expect(alerts()[2]).toContain("lookups are working again");
  });

  it("retries failed lookup alert and recovery delivery on later polls", async () => {
    vi.useFakeTimers();
    const { instance, control, alerts } = watchdog([suspended], 503);
    control.lookupStatus = 503;
    await failedLookupPoll(instance);
    await failedLookupPoll(instance);
    control.alertStatus = 204;
    await failedLookupPoll(instance);
    await failedLookupPoll(instance);
    expect(alerts()).toHaveLength(2);
    control.lookupStatus = 200;
    control.alertStatus = 503;
    await instance.alarm();
    await instance.alarm();
    control.alertStatus = 204;
    await instance.alarm();
    await instance.alarm();
    expect(alerts()).toHaveLength(4);
  });

  it("does not send lookup recovery if the outage alert was never delivered", async () => {
    vi.useFakeTimers();
    const { instance, control, alerts } = watchdog([suspended], 503);
    control.lookupStatus = 503;
    await failedLookupPoll(instance);
    await failedLookupPoll(instance);
    control.lookupStatus = 200;
    control.alertStatus = 204;
    await instance.alarm();
    await instance.alarm();
    expect(alerts()).toHaveLength(1);
  });

  it.each([401, 403, 404])("alerts immediately for permanent lookup failure HTTP %i", async (status) => {
    const { instance, control, alerts, fetch } = watchdog([suspended]);
    control.lookupStatus = status;
    await instance.alarm();
    expect(alerts()).toEqual([`Fly watchdog: Machine lookup failed (HTTP ${status}).`]);
    expect(fetch.mock.calls.filter(([url]) => url.endsWith("/machines"))).toHaveLength(1);
    await instance.alarm();
    expect(alerts()).toHaveLength(1);
    control.lookupStatus = 200;
    await instance.alarm();
    control.lookupStatus = status;
    await instance.alarm();
    expect(alerts()).toHaveLength(2);
  });

  it.each(["accepted", "rejected", "unknown"])("alerts on the first restart attempt: %s", async (outcome) => {
    const unhealthy = { ...suspended, state: "started", checks: [{ status: "critical" }] };
    const { instance, control, storage, fetch, alerts } = watchdog([unhealthy]);
    // A recent unrelated alert must never suppress a restart notification.
    await storage.put("last_error_alert_at", Date.now());
    if (outcome === "rejected") control.restartStatus = 503;
    if (outcome === "unknown") control.restartError = new Error("timeout");
    await instance.alarm();
    const expected = {
      accepted: "Restart requested for unhealthy machine machine-id; Fly accepted the request.",
      rejected: "Restart request for unhealthy machine machine-id failed (HTTP 503).",
      unknown: "Restart attempted for unhealthy machine machine-id; outcome unknown: timeout",
    };
    expect(alerts()).toEqual([`Fly watchdog: ${expected[outcome as keyof typeof expected]}`]);
    expect(fetch.mock.calls.filter(([url]) => url.endsWith("/restart"))).toHaveLength(1);
    await instance.alarm();
    expect(alerts()).toHaveLength(outcome === "accepted" ? 1 : 2);
    expect(fetch.mock.calls.filter(([url]) => url.endsWith("/machines"))).toHaveLength(2);
    expect(fetch.mock.calls.filter(([url]) => url.endsWith("/restart")))
      .toHaveLength(outcome === "accepted" ? 1 : 2);
  });

  it("alerts once for a continuous outage while continuing polls and logs", async () => {
    vi.useFakeTimers();
    const { instance, storage, fetch, control, alerts } = watchdog([unreachable]);
    await instance.alarm();
    expect(alerts()).toHaveLength(0);
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
    await instance.alarm();
    control.machines = [suspended];
    await instance.alarm();
    expect(alerts()).toHaveLength(1);
    await instance.alarm();
    await instance.alarm();
    expect(alerts()).toHaveLength(2);
    expect(alerts()[1]).toMatch(/Host reachable again.*suspended; website availability has not been tested/);
    control.machines = [unreachable];
    await instance.alarm();
    expect(alerts()).toHaveLength(2);
    await instance.alarm();
    expect(alerts()).toHaveLength(3);
  });

  it("announces running recovery only with passing service checks", async () => {
    const { instance, control, alerts } = watchdog([unreachable]);
    await instance.alarm();
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
    await instance.alarm();
    control.machines = [suspended];
    await instance.alarm();
    control.lookupStatus = 401;
    await instance.alarm();
    expect(alerts().at(-1)).toContain("HTTP 401");
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
    await instance.alarm();
    control.alertStatus = 204;
    await instance.alarm();
    await instance.alarm();
    expect(alerts()).toHaveLength(2);
  });

  it("retries failed recovery delivery without repeating the outage alert", async () => {
    const { instance, control, alerts } = watchdog([unreachable]);
    await instance.alarm();
    await instance.alarm();
    control.machines = [suspended];
    control.alertStatus = 503;
    await instance.alarm();
    await instance.alarm();
    control.machines = [unreachable];
    await instance.alarm();
    expect(alerts().filter((message) => message.includes("Host unreachable"))).toHaveLength(1);
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
    await instance.alarm();
    control.machines = [suspended];
    control.alertStatus = 204;
    await instance.alarm();
    await instance.alarm();
    expect(alerts()).toHaveLength(1);
  });

  it("alerts when no production machine can be identified", async () => {
    const { instance, alerts } = watchdog([]);
    await instance.alarm();
    expect(alerts()).toHaveLength(1);
    expect(alerts()[0]).toContain("found 0");
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
