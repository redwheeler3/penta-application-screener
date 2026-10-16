import { DurableObject } from "cloudflare:workers";

import {
  appMachine,
  hostRecovered,
  hostUnavailable,
  needsRestart,
  nextPollAt,
  shouldRetryLookupStatus,
  type FlyMachine,
  watchdogEnabled,
} from "./decision";
import { retryOnce } from "./retry";

export interface Env {
  WATCHDOG: DurableObjectNamespace;
  FLY_API_TOKEN: string;
  FLY_APP_NAME: string;
  ALERT_WEBHOOK_URL?: string;
  WATCHDOG_ENABLED?: string;
}

const LAST_RESTART_AT_KEY = "last_restart_at";
const LAST_ERROR_ALERT_AT_KEY = "last_error_alert_at";
const HOST_OUTAGE_KEY = "host_outage";
const FLY_REQUEST_TIMEOUT_MS = 10_000;
const FLY_LOOKUP_RETRY_DELAY_MS = 1_000;
const ERROR_ALERT_COOLDOWN_MS = 5 * 60_000;

type HostOutage = {
  alertDelivered: boolean;
  recoveryChecks: number;
  recoveryMachineId: string | null;
};

function errorDetail(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown error.";
}

function flyRequest(url: string, token: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${token}`);
  return fetch(url, {
    ...init,
    headers,
    signal: AbortSignal.timeout(FLY_REQUEST_TIMEOUT_MS),
  });
}

export class FlyWatchdog extends DurableObject<Env> {
  async fetch(): Promise<Response> {
    if (!watchdogEnabled(this.env.WATCHDOG_ENABLED)) {
      await this.resetHostRecoveryChecks();
      await this.ctx.storage.deleteAlarm();
      return new Response(null, { status: 204 });
    }

    await this.ensurePolling();
    return new Response(null, { status: 204 });
  }

  async alarm(): Promise<void> {
    if (!watchdogEnabled(this.env.WATCHDOG_ENABLED)) {
      await this.resetHostRecoveryChecks();
      await this.ctx.storage.deleteAlarm();
      return;
    }

    const pollStartedAt = Date.now();
    try {
      await this.pollMachine();
    } catch (error) {
      await this.resetHostRecoveryChecks();
      await this.notifyError(error);
      throw error;
    } finally {
      if (watchdogEnabled(this.env.WATCHDOG_ENABLED)) {
        await this.ctx.storage.setAlarm(nextPollAt(pollStartedAt, Date.now()));
      }
    }
  }

  private async ensurePolling(): Promise<void> {
    if ((await this.ctx.storage.getAlarm()) === null) {
      await this.ctx.storage.setAlarm(Date.now());
    }
  }

  private async pollMachine(): Promise<void> {
    let response: Response;
    try {
      response = await retryOnce(
        async () => {
          const lookup = await flyRequest(
            `https://api.machines.dev/v1/apps/${this.env.FLY_APP_NAME}/machines`,
            this.env.FLY_API_TOKEN,
          );
          if (shouldRetryLookupStatus(lookup.status)) {
            throw new Error(`Fly machine lookup failed (HTTP ${lookup.status}).`);
          }
          return lookup;
        },
        FLY_LOOKUP_RETRY_DELAY_MS,
      );
    } catch (error) {
      throw new Error(`Fly machine lookup failed after two attempts: ${errorDetail(error)}`, {
        cause: error,
      });
    }
    if (!response.ok) {
      throw new Error(`Fly machine lookup failed (HTTP ${response.status}).`);
    }

    const machine = appMachine((await response.json()) as FlyMachine[]);
    if (hostUnavailable(machine)) {
      await this.notifyHostOutage(machine);
      return;
    }
    await this.notifyHostRecovery(machine);
    const lastRestartAt = await this.ctx.storage.get<number>(LAST_RESTART_AT_KEY);
    if (!needsRestart(machine, Date.now(), lastRestartAt ?? null)) return;

    let restart: Response;
    try {
      restart = await flyRequest(
        `https://api.machines.dev/v1/apps/${this.env.FLY_APP_NAME}/machines/${machine.id}/restart`,
        this.env.FLY_API_TOKEN,
        { method: "POST" },
      );
    } catch (error) {
      // The request may have reached Fly even when its response did not reach us. Do not
      // repeat it inside this poll; the next poll must inspect current state first.
      throw new Error(
        `Fly machine restart request failed with an unknown outcome; ` +
          `the next poll will re-check state: ${errorDetail(error)}`,
        { cause: error },
      );
    }
    if (!restart.ok) {
      throw new Error(`Fly machine restart failed (HTTP ${restart.status}).`);
    }

    await this.ctx.storage.put(LAST_RESTART_AT_KEY, Date.now());
    const message = `Restarted unhealthy Fly machine ${machine.id}.`;
    console.log(message);
    await this.sendAlert(message);
  }

  private async notifyHostOutage(machine: FlyMachine): Promise<void> {
    const message = `Fly host for machine ${machine.id} is ${machine.host_status} ` +
      `(last state: ${machine.state}). Restart cannot repair an unavailable host. ` +
      "Check Fly incidents/support; database snapshot recovery requires operator approval.";
    console.error(message);
    const outage = await this.ctx.storage.get<HostOutage>(HOST_OUTAGE_KEY) ?? {
      alertDelivered: false, recoveryChecks: 0, recoveryMachineId: null,
    };
    outage.recoveryChecks = 0;
    outage.recoveryMachineId = null;
    await this.ctx.storage.put(HOST_OUTAGE_KEY, outage);
    if (!outage.alertDelivered && await this.sendAlert(message)) {
      outage.alertDelivered = true;
      await this.ctx.storage.put(HOST_OUTAGE_KEY, outage);
      console.log("Host outage alert delivered.");
    }
  }

  private async resetHostRecoveryChecks(): Promise<void> {
    const outage = await this.ctx.storage.get<HostOutage>(HOST_OUTAGE_KEY);
    if (outage && outage.recoveryChecks > 0) {
      outage.recoveryChecks = 0;
      outage.recoveryMachineId = null;
      await this.ctx.storage.put(HOST_OUTAGE_KEY, outage);
    }
  }

  private async notifyHostRecovery(machine: FlyMachine): Promise<void> {
    const outage = await this.ctx.storage.get<HostOutage>(HOST_OUTAGE_KEY);
    if (!outage) return;
    if (!hostRecovered(machine)) {
      await this.resetHostRecoveryChecks();
      return;
    }
    outage.recoveryChecks = outage.recoveryMachineId === machine.id
      ? Math.min(outage.recoveryChecks + 1, 2) : 1;
    outage.recoveryMachineId = machine.id;
    await this.ctx.storage.put(HOST_OUTAGE_KEY, outage);
    if (outage.recoveryChecks < 2) return;

    const message = `Fly host reachable again for machine ${machine.id}. ` +
      (machine.state === "suspended"
        ? "Machine is suspended; website availability has not been tested."
        : "Machine is running and Fly service checks are passing.");
    if (!outage.alertDelivered || await this.sendAlert(message)) {
      await this.ctx.storage.delete(HOST_OUTAGE_KEY);
      if (outage.alertDelivered) console.log("Host recovery alert delivered.");
    }
  }

  private async notifyError(error: unknown): Promise<void> {
    const detail = errorDetail(error);
    console.error(`Fly watchdog error: ${detail}`);
    const lastAlertAt = await this.ctx.storage.get<number>(LAST_ERROR_ALERT_AT_KEY);
    if (lastAlertAt && Date.now() - lastAlertAt < ERROR_ALERT_COOLDOWN_MS) return;

    if (await this.sendAlert(`Fly watchdog error: ${detail}`)) {
      await this.ctx.storage.put(LAST_ERROR_ALERT_AT_KEY, Date.now());
    }
  }

  private async sendAlert(message: string): Promise<boolean> {
    if (!this.env.ALERT_WEBHOOK_URL) return false;

    try {
      const response = await fetch(this.env.ALERT_WEBHOOK_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: message }),
        signal: AbortSignal.timeout(FLY_REQUEST_TIMEOUT_MS),
      });
      if (!response.ok) {
        console.error(`Watchdog alert delivery failed (HTTP ${response.status}).`);
      }
      return response.ok;
    } catch (error) {
      console.error("Watchdog alert delivery failed.", error);
      return false;
    }
  }
}

export default {
  async scheduled(_controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    const id = env.WATCHDOG.idFromName("production");
    ctx.waitUntil(env.WATCHDOG.get(id).fetch("https://watchdog.internal/activate"));
  },
} satisfies ExportedHandler<Env>;
