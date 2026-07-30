import { describe, expect, it } from "vitest";

import { appMachine, needsRestart, RESTART_COOLDOWN_MS, type FlyMachine } from "../src/decision";

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

  it("ignores suspended, starting, and healthy machines", () => {
    expect(needsRestart({ ...healthy, state: "suspended" }, 1, null)).toBe(false);
    expect(needsRestart({ ...healthy, state: "starting" }, 1, null)).toBe(false);
    expect(needsRestart(healthy, 1, null)).toBe(false);
  });

  it("restarts an unhealthy running machine once per cooldown window", () => {
    const unhealthy = { ...healthy, checks: [{ status: "critical" }] };
    expect(needsRestart(unhealthy, RESTART_COOLDOWN_MS, null)).toBe(true);
    expect(needsRestart(unhealthy, RESTART_COOLDOWN_MS, 1)).toBe(false);
  });
});
