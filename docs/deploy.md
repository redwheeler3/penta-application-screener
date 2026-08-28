# Deploying the Penta Application Screener (M17)

The hosting decision, the full platform tradeoff analysis, and the rationale for keeping
SQLite live in [ADR 0012](adr/0012-hosting-platform-m17.md). This is the operational
runbook: how to stand the app up on Fly.io, wire secrets and the domain, deploy on every
push, and back up / restore the data.

**Shape of the deploy (why the steps are what they are):**

- **Single origin.** FastAPI serves the built Vite bundle, so there is *one* service, one
  hostname, and no CORS. The frontend calls the API with relative URLs in prod.
- **Fly auto-stop to zero.** The machine stops when idle (compute billing → ~$0) and
  cold-starts on the next request. A **persistent volume** holds the SQLite DB, so the data
  survives stop/start and redeploys. Realistic cost ~$1–5/mo.
- **Secrets, never baked in.** OAuth client, session secret, and model-provider keys are Fly
  secrets set at runtime; the image contains only code + the built frontend.

---

## Prerequisites (one time)

1. **Install flyctl** and sign in:
   ```
   brew install flyctl      # or: curl -L https://fly.io/install.sh | sh
   fly auth login
   ```
2. **A Google OAuth client** (see [google-cloud-oauth-setup.md](google-cloud-oauth-setup.md))
   — you'll add the prod redirect URI in step 5 below.
3. **A scoped AWS IAM user for Bedrock.** Because Fly is not on AWS, there's no IAM role — the
   app uses a static key. Create an IAM user with an inline policy allowing **only**
   `bedrock:InvokeModel` (and `bedrock:InvokeModelWithResponseStream`) on the Anthropic
   inference-profile ARNs in **us-east-1** and their permitted cross-region destinations,
   nothing else. Generate an access key for it.
   Direct routes are optional: obtain an OpenAI and/or Anthropic API key only when that route
   will be enabled. Their keys never replace or broaden the AWS policy.
4. **DNS access** for `pentacoop.com` (to add the A/AAAA records `fly certs add` prints).

---

## First deploy

Run from the repo root. `fly.toml` already carries the app name, region, volume mount,
auto-stop config, and `[env]` — so these steps just create the resources and set secrets.

### 1. Create the app

```
fly launch --no-deploy --copy-config
```
`--copy-config` uses the committed `fly.toml`; `--no-deploy` holds off until the volume and
secrets exist. If it offers to create a Postgres/Redis, decline — we use SQLite on a volume.
(If `launch` is fussy, `fly apps create penta-application-screener` then continue.)

### 2. Create the persistent volume

```
fly volumes create screener_data --region iad --size 1
```
Matches `[[mounts]] source = "screener_data"` in `fly.toml`, mounted at
`/app/backend/data`. 1 GB is far more than the ~20 MB DB needs (~$0.15/mo).

### 3. Set secrets

```
fly secrets set \
  SESSION_SECRET="$(openssl rand -hex 32)" \
  GOOGLE_CLIENT_ID="<google client id>" \
  GOOGLE_CLIENT_SECRET="<google client secret>" \
  AWS_ACCESS_KEY_ID="<bedrock IAM key id>" \
  AWS_SECRET_ACCESS_KEY="<bedrock IAM secret>"
```
Add `OPENAI_API_KEY="<key>"` and/or `ANTHROPIC_API_KEY="<key>"` to the same command when
enabling a direct route. The Admin Settings catalog disables a direct route when its secret is
absent; adding a secret does not change any saved model choice.
`GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` take precedence over the secrets *file*, so none
ships in the image. Non-secret config (`DATABASE_URL`, `FRONTEND_URL`, `GOOGLE_REDIRECT_URI`,
`AWS_REGION`) is already in `fly.toml [env]`.

### 4. Deploy

```
fly deploy
```
Fly builds the image **on its remote builders** (no local Docker needed) and boots it. On
start the container runs `alembic upgrade head` (idempotent) then uvicorn. Watch it:
```
fly logs
fly status
```
The `/health` check should go green once migrations finish (see the grace period in
`fly.toml`).

### 5. Custom domain

```
fly certs add screener.pentacoop.com
```
It prints the DNS records to create. We used **A + AAAA** records (Fly recommended these for
this app) at the DNS provider (Squarespace/Google Domains for pentacoop.com) — host `screener`:
```
A     screener → 66.241.125.99
AAAA  screener → 2a09:8280:1::154:fc20:0
```
(A CNAME to `<your-app>.fly.dev` also works; A/AAAA is what we used. The **A record alone** is
enough — AAAA is a bonus. Get the current values from the `fly certs add` output, since the
app's IPs can change.) Fly auto-issues and renews a free Let's Encrypt cert. Verify:
```
fly certs check screener.pentacoop.com
```
This uses Fly's **free shared IPv4 + IPv6** — no dedicated IP ($2/mo) needed for a subdomain.
On Cloudflare, set the records to **DNS-only (grey cloud)**, not proxied, or cert validation
fails.

### 6. Point Google OAuth at prod

In the Google Cloud console, add the authorized redirect URI:
```
https://screener.pentacoop.com/auth/google/callback
```
(matches `GOOGLE_REDIRECT_URI` in `fly.toml`). Add `https://screener.pentacoop.com` to authorized
JavaScript origins too.

### 7. Seed the first admin

On every startup the app reads the bootstrap admin file (`initial_admins_file`, default
`config/initial-admins.txt` — one email per line, `#` comments) and promotes each listed email
to admin via `seed_initial_admins` (idempotent, additive: it never revokes). The file is
gitignored (real emails), so it isn't in the image — provide it once on the volume, then
restart so the lifespan hook seeds it:
```
fly ssh console
# in the container — the file path is relative to /app/backend:
mkdir -p /app/backend/config
printf 'you@example.com\n' > /app/backend/config/initial-admins.txt
exit
fly apps restart penta-application-screener      # startup seeds the admin
```
> Put it under `data/` if you want it to survive a machine replacement, and point
> `INITIAL_ADMINS_FILE` at it via `fly.toml [env]` — `config/` is on the image layer, so a
> redeploy wipes a file written there, whereas `data/` is the volume. For a one-time seed the
> above is fine (the admin entry itself lives in the DB on the volume, so it persists even
> after the file is gone). After the first admin exists, manage the allowlist in-app.

## Deploying

Deploys are **manual and deliberate** — there is no push-triggered CD. Pushing to `main`
records code; it does not ship. To release, run:
```
fly deploy --remote-only
```
This keeps "commit/push" and "deploy to the live committee app" as separate decisions: the
tree can be green and pushed without a half-finished change reaching real users, and a deploy
happens only when you choose to run the command. The build runs on Fly's remote builders, so no
local Docker/Finch is needed.

The Docker context is intentionally allowlisted by `.dockerignore` to only `Dockerfile`,
`backend/`, and `frontend/`; local caches, documentation, and operational tooling never upload
to Fly. If the Dockerfile later copies another path, add it to that allowlist. Do **not** use
`flyctl deploy --build-only` as a harmless context check: the Fly CLI used for this app created
a production release when it was used. Use `flyctl deploy --remote-only` only when a release is
intended.

### Scale-to-zero watchdog (M19)

The Cloudflare Durable Object watchdog is maintained separately in
[`ops/fly-watchdog/`](../ops/fly-watchdog/). It polls Fly's Machines API every 30 seconds without
making an HTTP request to Penta, so an idle Machine remains suspended. Its once-per-minute Cron
only restores the persisted alarm if needed.

To temporarily pause recovery, from `ops/fly-watchdog/` run:

```powershell
npx wrangler secret put WATCHDOG_ENABLED
```

Enter `false`. To resume, run it again and enter `true`. While paused, the watchdog makes no
Fly API calls; the Cron remains only as a negligible-cost resume mechanism. See the
[watchdog README](../ops/fly-watchdog/README.md) for validation, alerts, and token rotation.

---

## Deploying from another machine

The "first deploy" above is a **one-time account setup** (app, volume, secrets, domain, OAuth)
— it lives on Fly + Google + DNS, **not** on any laptop. So a second machine that just needs to
*deploy* requires almost nothing, because all state already exists remotely — just flyctl:
```
brew install flyctl            # or: curl -L https://fly.io/install.sh | sh
fly auth login                 # opens a browser; same Fly account
git clone <this repo> && cd penta-application-screener
fly deploy --remote-only       # builds on Fly's remote builders — no local Docker/Finch
```
That's it. `fly auth login` ties the machine to your Fly account, where the app, volume, and
**secrets already live** — you do **not** re-enter AWS/Google/session secrets, and you do **not**
recreate the volume or DNS. `--remote-only` means the build happens on Fly, so **no Docker or
Finch is needed locally** on either machine.

### What a second machine does NOT need (deploy vs. local dev)

Deploying is not the same as running the app locally. For a *deploy*, skip all of this — it's
only for **local development** on a machine:

| Item | Needed to deploy? | Needed for local dev? |
|---|---|---|
| `flyctl` + `fly auth login` | Only for Path B (not Path A) | No |
| Repo clone + `git push` access | Yes | Yes |
| Local Docker / Finch | **No** (Fly builds remotely) | No |
| `.env.local`, `backend/secrets/*.json` (Google) | **No** (prod uses Fly secrets) | Yes |
| Local SQLite DB / `uv sync` / `npm install` | **No** | Yes (`./setup.sh`) |
| AWS keys / IAM user | **No** (already a Fly secret) | Yes (ambient AWS creds) |

So: **new machine, deploy only → install flyctl, `fly auth login`, clone, `fly deploy`** (or just
push to `main`). New machine for *local dev* → follow the README's Setup + recreate the
gitignored secrets. The two are independent.

---

## Backups and restore

**In prod, Fly volume snapshots are the backup mechanism.** The app's own post-rank
auto-snapshot is a *local-only* safety net from the heavy-iteration days and is **disabled in
prod** via `LOCAL_DB_BACKUPS = "false"` in `fly.toml [env]` (it would otherwise pile `.db`
files onto the volume on every rank, duplicating what volume snapshots already cover). It
stays on for local dev with no config.

### Fly volume snapshots (the prod backup)

Fly snapshots the volume daily. Production retention is configured for 30 days. Manage them:
```
fly volumes snapshots list <volume-id>      # volume id from `fly volumes list`
fly volumes snapshots create <volume-id>    # on-demand, e.g. before a big change
```
Restore by creating a new volume from a snapshot, then attaching it:
```
fly volumes create screener_data --snapshot-id <snap-id> --region iad --size 1
```
Production recovery intentionally restores the selected snapshot as-is. There is no separate
cross-snapshot deletion-ledger reconciliation: a restore can therefore reintroduce applicant data
deleted after the snapshot was taken. That exposure is bounded by the 30-day snapshot-retention
window and is the accepted disaster-recovery tradeoff for this small deployment. The local
`restore-db` scripts provide stronger deletion-ledger handling for local backups; that behavior does
not apply to a Fly volume replacement.

For a true off-Fly copy (belt and suspenders), pull a consistent snapshot down on demand. Treat the
download as sensitive applicant data and delete it within the same 30-day retention window.
`VACUUM INTO` gives a clean copy even while the app is live:
```
fly ssh console -C "sh -c 'cd /app/backend && uv run python -c \"import sqlite3; \
sqlite3.connect(\\\"data/penta_screener.db\\\").execute(\\\"VACUUM INTO \\\\\\\"/tmp/snap.db\\\\\\\"\\\")\"'"
fly ssh sftp get /tmp/snap.db ./screener-$(date +%Y%m%d).db
```
(Or, if you ever flip `LOCAL_DB_BACKUPS` on temporarily, `restore-db.sh` and the tagged
snapshots in `data/backups/` work the same in the container as locally.)

---

## Routine operations

### Vacancy-list production cutover

#### Historical application opening prerequisite

The production database initially contains the submitted Google Form application pool without an
opening participation. Before scheduling the vacancy-list handoff, implement and verify the guarded
historical-opening migration command described in the specification. It must create the already-
closed opening with its original open and close dates and future move-in date, attach every
submitted, non-withdrawn application using its submission timestamp, and refresh retention in one
transaction. This command is not implemented yet; do not substitute manual SQL or the normal
opening-creation endpoint.

Dry-run output must report the opening details, target application count, existing participation
count, active vacancy-subscription count, consent-receipt count, and queued-email count. Apply only
when the target count matches the complete Google Form pool and no target participation already
exists. After applying, verify the opening is closed, every target application is attached, and the
vacancy-subscription, consent-receipt, and queued-email counts are unchanged. This operation must not
call the normal opening-creation endpoint because that endpoint immediately queues the vacancy
audience.

The Google form and built-in form must not accept responses at the same time during migration. A
full export applied with `--allow-upsert` could replace a newer built-in preference with an older
Google response, while exporting before Google closes could omit a late response. Use the explicit
freeze and handoff below.

#### 1. Rehearse before the cutover window

Export the current Google response sheet as CSV and validate it locally without writing anything:

```sh
cd backend
uv run python scripts/import_vacancy_subscriptions.py path/to/export.csv
```

The dry run requires the timestamp, email, and preference columns, validates every address and
consent timestamp, asserts normalized-email uniqueness, and reports the total plus overlapping 1BR,
2BR, and 3BR counts. If the sheet's preference heading differs, pass
`--preferences-column "Exact heading"`. Resolve every reported row before scheduling cutover. This
export is a rehearsal only; Google may receive more responses afterward.

#### 2. Prepare production without changing the public form

Deploy the application service and its database migration while the public website still points to
Google. Verify application health, administrator access, SocketLabs usage reporting, and the vacancy
report. The production vacancy list must be empty before the authoritative import. Remove any
controlled test subscription through the narrow administrator interface rather than relying on an
upsert during migration.

#### 3. Freeze Google and take the authoritative export

Pause the Google form so it no longer accepts responses. Leave the public website online; its
signup is briefly unavailable until the website deployment in step 5. Export the response sheet
again after the pause and run the same dry-run command against this final file.

If validation fails, re-enable Google responses and end the cutover attempt. Resolve the source
data and begin a later attempt with another fresh export. Do not edit an exported CSV into a second
source of truth.

#### 4. Import and reconcile

Transfer the final validated file to production using an encrypted transfer or short-lived remote
copy and apply it without `--allow-upsert`:

```sh
uv run python scripts/import_vacancy_subscriptions.py path/to/export.csv --apply
```

The importer refuses to write into a non-empty list unless `--allow-upsert` is deliberately passed.
Do not use that option for the cutover. Reconcile the Notifications report total, overlapping bedroom
counts, and monthly chart against the final Google export. Remove the transferred CSV immediately
after the import because it contains personal information.

If the import or reconciliation fails, do not deploy the website form. Re-enable Google responses,
diagnose the mismatch, restore the vacancy list to an empty pre-cutover state through an explicitly
approved production operation, and restart later from a fresh export.

#### 5. Switch the public website

Deploy the public website with the built-in vacancy form. Verify the reviewed signup notice and
Privacy Policy, then submit one controlled address. Confirm it appears in the administrator report
and exact-address lookup, replace its unit-size selection once, and delete it through the
administrator interface. Confirm the report returns to the imported totals.

The production gate also includes the application declaration, withdrawal flow, and common email
footer. Verify those surfaces with controlled records without creating an opening or notifying the
imported audience. An application-intake opening preview is safe to inspect; confirming it is the
real application-open event and durably queues its matching notices. Do not exercise direct fill
with a real retained applicant merely as a smoke test because it changes that application's outcome
and retention.

After the controlled checks pass, remove the Google form from public use and retire the response
sheet from operational handling. No migration email is sent. Update the milestone documentation to
mark M22 complete.

| Task | Command |
|---|---|
| Tail logs | `fly logs` |
| App / machine status | `fly status` |
| Open a shell in the container | `fly ssh console` |
| Restart | `fly apps restart penta-application-screener` |
| Run a one-off (e.g. a migration by hand) | `fly ssh console -C "sh -c 'cd /app/backend && alembic upgrade head'"` |
| Rotate a secret | `fly secrets set KEY=newvalue` (triggers a redeploy) |
| Scale memory if needed | edit `[[vm]] memory` in `fly.toml`, then `fly deploy` |

---

## Notes / gotchas

- **Cold start.** With auto-stop to zero, the first request after idle wakes the machine
  (single-digit seconds) — expected for a bursty ~5-member committee tool.
- **Long streams + the 60s idle timeout.** The Rank stream can be silent for stretches during
  the opaque AI passes; the app emits a keepalive every 15s (see `HEARTBEAT_SECONDS` in
  `app/api/ranking/run.py`) so Fly's 60s idle timeout can't sever it. No action needed — just
  don't remove the heartbeat.
- **Single instance.** The volume ties the app to one machine (fine for this scale), and a
  deploy is a brief restart, not zero-downtime. Acceptable for ~5 users.
- **Secrets over env.** Never put a real secret in `fly.toml [env]` — it's committed. Use
  `fly secrets`.
