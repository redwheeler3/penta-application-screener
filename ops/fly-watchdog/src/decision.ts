export const POLL_INTERVAL_MS = 30_000;
export const RESTART_COOLDOWN_MS = 120_000;
const MINIMUM_NEXT_POLL_DELAY_MS = 1_000;
const RETRYABLE_LOOKUP_STATUSES = new Set([408, 429, 500, 502, 503, 504]);

export function nextPollAt(pollStartedAt: number, now: number): number {
  return Math.max(pollStartedAt + POLL_INTERVAL_MS, now + MINIMUM_NEXT_POLL_DELAY_MS);
}

export function shouldRetryLookupStatus(status: number): boolean {
  return RETRYABLE_LOOKUP_STATUSES.has(status);
}

export type FlyMachine = {
  id: string;
  state: string;
  config?: { metadata?: Record<string, string> };
  checks?: Array<{ status: string }>;
};

export function watchdogEnabled(value: string | undefined): boolean {
  return value !== "false";
}

export function appMachine(machines: FlyMachine[]): FlyMachine | undefined {
  return machines.find((machine) => machine.config?.metadata?.fly_process_group === "app");
}

export function needsRestart(machine: FlyMachine | undefined, now: number, lastRestartAt: number | null): boolean {
  if (machine?.state !== "started") return false;
  if (lastRestartAt !== null && now - lastRestartAt < RESTART_COOLDOWN_MS) return false;
  // Fly can report a transient `warning` while a healthy Machine is being evaluated.
  // Only `critical` is an explicit failed service check that warrants a restart.
  return Boolean(machine.checks?.some((check) => check.status === "critical"));
}
