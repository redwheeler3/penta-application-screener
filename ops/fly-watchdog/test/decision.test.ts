import { describe, expect, it } from "vitest";

import {
  appMachine,
  needsRestart,
  nextPollAt,
  POLL_INTERVAL_MS,
  RESTART_COOLDOWN_MS,
  shouldRetryLookupStatus,
  type FlyMachine,
  watchdogEnabled,
} from "../src/decision";

const healthy: FlyMachine = {
  id: "machine-id",
  state: "started",
  config: { metadata: { fly_process_group: "app" } },
  checks: [{ status: "passing" }],
};

describe("watchdog decisions", () => {
  it("selects the app machine without a hard-coded machine id", () => {
    expect(appMachine([{ ...healthy, config: { metadata: { fly_process_group: "worker" } } }, healthy])).toBe(healthy);
  });

  it("ignores suspended, starting, healthy, and warning machines", () => {
    expect(needsRestart({ ...healthy, state: "suspended" }, 1, null)).toBe(false);
    expect(needsRestart({ ...healthy, state: "starting" }, 1, null)).toBe(false);
    expect(needsRestart(healthy, 1, null)).toBe(false);
    expect(needsRestart({ ...healthy, checks: [{ status: "warning" }] }, 1, null)).toBe(false);
  });

  it("restarts an unhealthy running machine once per cooldown window", () => {
    const unhealthy = { ...healthy, checks: [{ status: "critical" }] };
    expect(needsRestart(unhealthy, RESTART_COOLDOWN_MS, null)).toBe(true);
    expect(needsRestart(unhealthy, RESTART_COOLDOWN_MS, 1)).toBe(false);
  });

  it("is enabled by default and pauses only when explicitly disabled", () => {
    expect(watchdogEnabled(undefined)).toBe(true);
    expect(watchdogEnabled("true")).toBe(true);
    expect(watchdogEnabled("false")).toBe(false);
  });

  it("keeps the polling cadence anchored to the start of each poll", () => {
    expect(nextPollAt(1_000, 2_000)).toBe(1_000 + POLL_INTERVAL_MS);
    expect(nextPollAt(1_000, 40_000)).toBe(41_000);
  });

  it("retries only transient Machine lookup responses", () => {
    for (const status of [408, 429, 500, 502, 503, 504]) {
      expect(shouldRetryLookupStatus(status)).toBe(true);
    }
    for (const status of [400, 401, 403, 404, 501]) {
      expect(shouldRetryLookupStatus(status)).toBe(false);
    }
  });
});
