# Penta Fly watchdog

This scheduler protects the single production Fly Machine while preserving suspend-to-zero.
It calls the Fly Machines API only; it never sends an HTTP request to Penta.

- A Durable Object polls the Machine state every 30 seconds using a persisted alarm.
- The next alarm is anchored to the start of the poll, so retry time does not postpone the
  following health decision. An overrun gets a one-second minimum before the next poll.
- The once-per-minute Cloudflare Cron Trigger only ensures that alarm exists after deployment
  or recovery; it does not determine the health-check cadence.
- Suspended, stopped, startup, and `warning` Machines are ignored. A `started` Machine with an
  explicitly `critical` service check is restarted, at most once every two minutes.
- Host availability is checked before the Machine's last state. An `unreachable` or `unknown`
  host raises an operator alert even when the Machine was suspended. Fly returns partial
  metadata in `incomplete_config` for unavailable hosts; that metadata identifies the app
  Machine. Missing or multiple app Machines also raise an alert instead of silently skipping.
- A host outage cannot be repaired by restarting its Machine. Its local database volume is
  also unavailable: check Fly incidents/support, then choose between waiting for the host and
  an approved snapshot restore. The watchdog never restores a database automatically.
- A timed-out or transient HTTP-failed Machine lookup is retried once after one second before
  alerting. Restart requests are never retried inside the same poll; after an ambiguous
  transport failure, the next poll re-checks Machine state before deciding whether recovery
  is still required.
- Public Worker and preview URLs are disabled. Recovery attempts are recorded in Cloudflare
  Worker logs. `ALERT_WEBHOOK_URL` is optional for a Discord webhook.
- Host outages send one successfully delivered notification per continuous outage. `unknown`
  and `unreachable` are the same outage; persisted notification state survives object restarts
  and deployments. Polling and error logs continue while repeat host notifications are suppressed.
- After two consecutive observations of the same Machine on an explicitly `ok` host, send one
  recovery notification. The Machine must be suspended or running with all reported service
  checks passing (at least one check is required). Startup, stopped, warning, failed lookup,
  and paused-watchdog observations reset the confirmation count. Suspended recovery says
  **Fly host reachable again** and explicitly does not claim the website has been tested.
- Failed outage or recovery delivery is retried on later polls. A new host-outage alert is
  armed after confirmed recovery and successful recovery notification; an outage that was
  never successfully announced clears after confirmed recovery without an unpaired recovery
  message. Other watchdog errors retain their five-minute alert cooldown.

## Routine commands

Run watchdog commands from this directory:

```powershell
npm run check
npm test
npx wrangler deploy
npx wrangler secret list
```

Deploy the Penta application separately, from the repository root, only when a production
application release is intended:

```powershell
flyctl deploy --remote-only
```

Do not use `flyctl deploy --build-only` as a no-impact context check: with the Fly CLI used for
this app it created a production release. The Docker context is deliberately allowlisted in
`.dockerignore` to `Dockerfile`, `backend/`, and `frontend/`; update that allowlist if the
Dockerfile ever needs another path.

`FLY_API_TOKEN` is an app-scoped Fly deploy token stored only as a Cloudflare secret. Rotate it
by revoking the old Fly token, creating a replacement for `penta-application-screener`, then
running `npx wrangler secret put FLY_API_TOKEN`. Never place a token in this repository or chat.

### Pause watchdog recovery

To pause recovery without waking Penta, set the `WATCHDOG_ENABLED` secret to `false`:

```powershell
npx wrangler secret put WATCHDOG_ENABLED
```

Enter `false` at the prompt. While paused, the once-per-minute Cron still reaches the Durable
Object, but it clears its 30-second alarm and makes no Fly API calls.

### Resume watchdog recovery

Run the same command and enter `true`:

```powershell
npx wrangler secret put WATCHDOG_ENABLED
```

The next minute's Cron activation restores the 30-second alarm. Deleting this secret also
restores the default enabled state.

### Observability

Workers Logs are enabled at 100% sampling for this Worker, including Durable Object requests,
alarms, errors, and recovery messages. In Cloudflare, open **Workers & Pages →
`penta-fly-watchdog` → Logs** for the combined stream, or **Durable Objects → `FlyWatchdog` →
Logs** to focus on its scheduler. Logs are retained according to the Cloudflare account plan.

To investigate a recovery, inspect Cloudflare Worker logs and compare them with:

```powershell
flyctl machines list --app penta-application-screener
flyctl logs --app penta-application-screener --no-tail
```

When Wrangler runs inside a managed workspace sandbox, route its local debug log to the
repository's ignored log directory instead of the Windows profile:

```powershell
New-Item -ItemType Directory -Path ..\..\.dev-logs\wrangler -Force | Out-Null
$env:WRANGLER_LOG_PATH = (Resolve-Path ..\..\.dev-logs\wrangler).Path
npx wrangler deploy --dry-run
```
