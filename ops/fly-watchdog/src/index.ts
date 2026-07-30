import { DurableObject } from "cloudflare:workers";

import {
  appMachine,
  needsRestart,
  POLL_INTERVAL_MS,
  type FlyMachine,
  watchdogEnabled,
} from "./decision";

export interface Env {
  WATCHDOG: DurableObjectNamespace;
  FLY_API_TOKEN: string;
  FLY_APP_NAME: string;
  ALERT_WEBHOOK_URL?: string;
  WATCHDOG_ENABLED?: string;
}

const LAST_RESTART_AT_KEY = "last_restart_at";
const LAST_ERROR_ALERT_AT_KEY = "last_error_alert_at";
const FLY_REQUEST_TIMEOUT_MS = 10_000;
const ERROR_ALERT_COOLDOWN_MS = 5 * 60_000;

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
      await this.ctx.storage.deleteAlarm();
      return new Response(null, { status: 204 });
    }

    await this.ensurePolling();
    return new Response(null, { status: 204 });
  }

  async alarm(): Promise<void> {
    if (!watchdogEnabled(this.env.WATCHDOG_ENABLED)) {
      await this.ctx.storage.deleteAlarm();
      return;
    }

    try {
      await this.restartIfUnhealthy();
    } catch (error) {
      await this.notifyError(error);
      throw error;
    } finally {
      if (watchdogEnabled(this.env.WATCHDOG_ENABLED)) {
        await this.ctx.storage.setAlarm(Date.now() + POLL_INTERVAL_MS);
      }
    }
  }

  private async ensurePolling(): Promise<void> {
    if ((await this.ctx.storage.getAlarm()) === null) {
      await this.ctx.storage.setAlarm(Date.now());
    }
  }

  private async restartIfUnhealthy(): Promise<void> {
    const response = await flyRequest(
      `https://api.machines.dev/v1/apps/${this.env.FLY_APP_NAME}/machines`,
      this.env.FLY_API_TOKEN,
    );
    if (!response.ok) {
      throw new Error(`Fly machine lookup failed (HTTP ${response.status}).`);
    }

    const machine = appMachine((await response.json()) as FlyMachine[]);
    const lastRestartAt = await this.ctx.storage.get<number>(LAST_RESTART_AT_KEY);
    if (!machine || !needsRestart(machine, Date.now(), lastRestartAt ?? null)) return;

    const restart = await flyRequest(
      `https://api.machines.dev/v1/apps/${this.env.FLY_APP_NAME}/machines/${machine.id}/restart`,
      this.env.FLY_API_TOKEN,
      { method: "POST" },
    );
    if (!restart.ok) {
      throw new Error(`Fly machine restart failed (HTTP ${restart.status}).`);
    }

    await this.ctx.storage.put(LAST_RESTART_AT_KEY, Date.now());
    const message = `Restarted unhealthy Fly machine ${machine.id}.`;
    console.log(message);
    await this.sendAlert(message);
  }

  private async notifyError(error: unknown): Promise<void> {
    const lastAlertAt = await this.ctx.storage.get<number>(LAST_ERROR_ALERT_AT_KEY);
    if (lastAlertAt && Date.now() - lastAlertAt < ERROR_ALERT_COOLDOWN_MS) return;

    const detail = error instanceof Error ? error.message : "Unknown error.";
    await this.ctx.storage.put(LAST_ERROR_ALERT_AT_KEY, Date.now());
    await this.sendAlert(`Fly watchdog error: ${detail}`);
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
