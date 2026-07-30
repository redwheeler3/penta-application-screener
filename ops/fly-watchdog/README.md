# Penta Fly watchdog

This scheduler protects the single production Fly Machine while preserving suspend-to-zero.
It calls the Fly Machines API only; it never sends an HTTP request to Penta.

- A Durable Object polls the Machine state every 30 seconds using a persisted alarm.
- The once-per-minute Cloudflare Cron Trigger only ensures that alarm exists after deployment
  or recovery; it does not determine the health-check cadence.
- Suspended, stopped, and startup Machines are ignored. A `started` Machine with any
  non-passing service check is restarted, at most once every two minutes.
- Public Worker and preview URLs are disabled. Recovery attempts are recorded in Cloudflare
  Worker logs. `ALERT_WEBHOOK_URL` is optional for a Discord webhook.

## Operations

Run from this directory.

```powershell
npm run check
npm test
npx wrangler deploy
npx wrangler secret list
```

`FLY_API_TOKEN` is an app-scoped Fly deploy token stored only as a Cloudflare secret. Rotate it
by revoking the old Fly token, creating a replacement for `penta-application-screener`, then
running `npx wrangler secret put FLY_API_TOKEN`. Never place a token in this repository or chat.

To investigate a recovery, inspect Cloudflare Worker logs and compare them with:

```powershell
flyctl machines list --app penta-application-screener
flyctl logs --app penta-application-screener --no-tail
```
