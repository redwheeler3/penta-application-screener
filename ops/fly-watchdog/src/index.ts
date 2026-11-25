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
const HOST_FAILURE_CHECKS_KEY = "host_failure_checks";
const LOOKUP_OUTAGE_KEY = "lookup_outage";
const FLY_REQUEST_TIMEOUT_MS = 10_000;
const FLY_LOOKUP_RETRY_DELAY_MS = 1_000;
const ERROR_ALERT_COOLDOWN_MS = 5 * 60_000;

type HostOutage = {
  alertDelivered: boolean;
  recoveryChecks: number;
  recoveryMachineId: string | null;
};

type LookupOutage = {
  failureChecks: number;
  alertDelivered: boolean;
  recoveryChecks: number;
};

class TransientLookupError extends Error {}

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
      await this.pauseConfirmations();
      await this.ctx.storage.deleteAlarm();
      return new Response(null, { status: 204 });
    }

    await this.ensurePolling();
    return new Response(null, { status: 204 });
  }

  async alarm(): Promise<void> {
    if (!watchdogEnabled(this.env.WATCHDOG_ENABLED)) {
      await this.pauseConfirmations();
      await this.ctx.storage.deleteAlarm();
      return;
    }

    const pollStartedAt = Date.now();
    try {
      await this.pollMachine();
    } catch (error) {
      await this.resetHostRecoveryChecks();
      await this.notifyError(error);
      // The persisted alarm owns retries. Throwing would also request platform retries,
      // which could count as another failed poll before the next 30-second interval.
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
    let response: { status: number; body: string | null };
    try {
      response = await retryOnce(
        async () => {
          const lookup = await flyRequest(
            `https://api.machines.dev/v1/apps/${this.env.FLY_APP_NAME}/machines`,
            this.env.FLY_API_TOKEN,
          );
          if (shouldRetryLookupStatus(lookup.status)) {
            throw new Error(`HTTP ${lookup.status}.`);
          }
          return { status: lookup.status, body: lookup.ok ? await lookup.text() : null };
        },
        FLY_LOOKUP_RETRY_DELAY_MS,
      );
    } catch (error) {
      throw new TransientLookupError(`Machine lookup failed after two attempts: ${errorDetail(error)}`, {
        cause: error,
      });
    }
    if (response.body === null) {
      throw new Error(`Machine lookup failed (HTTP ${response.status}).`);
    }

    const machine = appMachine(JSON.parse(response.body) as FlyMachine[]);
    await this.notifyLookupRecovery();
    await this.ctx.storage.delete(LAST_ERROR_ALERT_AT_KEY);
    if (hostUnavailable(machine)) {
      await this.notifyHostOutage(machine);
      return;
    }
    await this.notifyHostRecovery(machine);
    const lastRestartAt = await this.ctx.storage.get<number>(LAST_RESTART_AT_KEY);
    if (!needsRestart(machine, Date.now(), lastRestartAt ?? null)) return;

    await this.restartMachine(machine);
  }

  private async restartMachine(machine: FlyMachine): Promise<void> {
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
      const message = `Restart attempted for unhealthy machine ${machine.id}; ` +
        `outcome unknown: ${errorDetail(error)}`;
      console.error(message);
      await this.sendAlert(message);
      return;
    }
    if (!restart.ok) {
      const message = `Restart request for unhealthy machine ${machine.id} failed (HTTP ${restart.status}).`;
      console.error(message);
      await this.sendAlert(message);
      return;
    }

    await this.ctx.storage.put(LAST_RESTART_AT_KEY, Date.now());
    const message = `Restart requested for unhealthy machine ${machine.id}; Fly accepted the request.`;
    console.log(message);
    await this.sendAlert(message);
  }

  private async notifyHostOutage(machine: FlyMachine): Promise<void> {
    const message = `Host ${machine.host_status} for machine ${machine.id} (last state: ${machine.state}).`;
    console.error(message);
    await this.resetHostRecoveryChecks();
    const failureChecks = Math.min(
      (await this.ctx.storage.get<number>(HOST_FAILURE_CHECKS_KEY) ?? 0) + 1, 2,
    );
    await this.ctx.storage.put(HOST_FAILURE_CHECKS_KEY, failureChecks);
    if (failureChecks < 2) return;
    const outage = await this.ctx.storage.get<HostOutage>(HOST_OUTAGE_KEY) ?? {
      alertDelivered: false, recoveryChecks: 0, recoveryMachineId: null,
    };
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
    if (machine.host_status === "ok") await this.ctx.storage.delete(HOST_FAILURE_CHECKS_KEY);
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

    const message = `Host reachable again for machine ${machine.id}. ` +
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
    console.error(`Fly watchdog: ${detail}`);
    if (error instanceof TransientLookupError) {
      await this.notifyLookupOutage(detail);
      return;
    }
    await this.resetLookupChecks();
    const lastAlertAt = await this.ctx.storage.get<number>(LAST_ERROR_ALERT_AT_KEY);
    if (lastAlertAt && Date.now() - lastAlertAt < ERROR_ALERT_COOLDOWN_MS) return;

    if (await this.sendAlert(detail)) {
      await this.ctx.storage.put(LAST_ERROR_ALERT_AT_KEY, Date.now());
    }
  }

  private async notifyLookupOutage(detail: string): Promise<void> {
    const outage = await this.ctx.storage.get<LookupOutage>(LOOKUP_OUTAGE_KEY) ?? {
      failureChecks: 0, alertDelivered: false, recoveryChecks: 0,
    };
    outage.failureChecks = Math.min(outage.failureChecks + 1, 2);
    outage.recoveryChecks = 0;
    await this.ctx.storage.put(LOOKUP_OUTAGE_KEY, outage);
    if (outage.failureChecks < 2 || outage.alertDelivered) return;
    if (await this.sendAlert(`Unable to check machine status on two consecutive polls. ` +
      `Website status unknown. ${detail}`)) {
      outage.alertDelivered = true;
      await this.ctx.storage.put(LOOKUP_OUTAGE_KEY, outage);
    }
  }

  private async notifyLookupRecovery(): Promise<void> {
    const outage = await this.ctx.storage.get<LookupOutage>(LOOKUP_OUTAGE_KEY);
    if (!outage) return;
    if (!outage.alertDelivered) {
      await this.ctx.storage.delete(LOOKUP_OUTAGE_KEY);
      return;
    }
    outage.failureChecks = 0;
    outage.recoveryChecks = Math.min(outage.recoveryChecks + 1, 2);
    await this.ctx.storage.put(LOOKUP_OUTAGE_KEY, outage);
    if (outage.recoveryChecks < 2) return;
    if (await this.sendAlert("Machine status lookups are working again. Website availability has not been tested.")) {
      await this.ctx.storage.delete(LOOKUP_OUTAGE_KEY);
    }
  }

  private async resetLookupChecks(): Promise<void> {
    const outage = await this.ctx.storage.get<LookupOutage>(LOOKUP_OUTAGE_KEY);
    if (!outage) return;
    if (!outage.alertDelivered) {
      await this.ctx.storage.delete(LOOKUP_OUTAGE_KEY);
      return;
    }
    outage.failureChecks = 0;
    outage.recoveryChecks = 0;
    await this.ctx.storage.put(LOOKUP_OUTAGE_KEY, outage);
  }

  private async pauseConfirmations(): Promise<void> {
    await this.ctx.storage.delete(HOST_FAILURE_CHECKS_KEY);
    await this.resetHostRecoveryChecks();
    await this.resetLookupChecks();
  }

  private async sendAlert(message: string): Promise<boolean> {
    if (!this.env.ALERT_WEBHOOK_URL) return false;

    try {
      const response = await fetch(this.env.ALERT_WEBHOOK_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: `Fly watchdog: ${message}` }),
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
