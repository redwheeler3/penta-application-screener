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
- **Secrets, never baked in.** OAuth client, session secret, and AWS keys are Fly secrets set
  at runtime; the image contains only code + the built frontend.

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
   inference-profile ARNs in **us-west-2**, nothing else. Generate an access key for it.
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
fly volumes create screener_data --region sjc --size 1
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

### 8. M18: least-privilege Google auth (Picker sheet-linking)

M18 changed how the applications sheet is connected: members log in with **identity only** (no
Drive/Sheets scope), and an admin links the sheet via the **Google Picker**, granting only
`drive.file` (access to the one picked file). The sheet is read during sync with that admin's
token. Extra prod setup beyond the OAuth steps above:

1. **Enable the Google Picker API** in the prod project (APIs & Services → Library).
2. **Browser API key for the Picker** — the key is committed in `fly.toml [build.args]`
   (`VITE_GOOGLE_PICKER_API_KEY`) and baked into the frontend at build time (it's a browser
   key — public by design). **Restrict it** in Google Cloud: Application restrictions →
   HTTP referrers → add `https://screener.pentacoop.com/*`; API restrictions → Google Picker
   API only. (`VITE_GOOGLE_CLIENT_ID` + `VITE_GOOGLE_PROJECT_NUMBER` are also build args — the
   project number is **required** by the Picker's `setAppId` for `drive.file` to authorize a
   picked file; without it, linking silently fails.)
3. **Consent screen scopes** — add `.../auth/drive.file`. Once M18 is fully live you can
   **remove** `spreadsheets.readonly` and `documents` (the sensitive scopes) so the app's
   footprint is entirely non-sensitive — but only after confirming login + linking work.
4. **OAuth client `postmessage`** — the Picker uses the GIS code model (`ux_mode: popup`),
   whose code exchange posts `redirect_uri=postmessage`. This works as long as
   `https://screener.pentacoop.com` is an **Authorized JavaScript origin** on the OAuth client
   (add it alongside the redirect URI in step 6). No literal `postmessage` entry is needed.
5. **Re-link the sheet after deploy (one-time).** The prod DB's existing sheet link predates
   M18, so its stored reader token lacks `drive.file` — sync will fail until you re-link.
   After deploying: sign in as admin → **Admin Settings → Configuration → Change response
   sheet** → grant → pick the sheet in the Picker. That stores a fresh `drive.file` reader
   token, and sync works again. (Trivial here — Jeff is the only admin.)

> Deploy ordering note: because login drops to identity-only in the same release, sync is
> broken between deploy and re-link. Since the committee isn't actively using it mid-deploy,
> just re-link promptly after the deploy completes.

---

## Continuous deployment

`.github/workflows/fly-deploy.yml` deploys on every push to `main` (and on manual dispatch),
via `flyctl deploy --remote-only`. Set the deploy token once:
```
fly tokens create deploy -x 999999h
gh secret set FLY_API_TOKEN --body "<token>"
```
After that, merging to `main` ships. A newer push supersedes an in-flight deploy
(`concurrency` in the workflow).

---

## Deploying from another machine

The "first deploy" above is a **one-time account setup** (app, volume, secrets, domain, OAuth)
— it lives on Fly + Google + DNS, **not** on any laptop. So a second machine that just needs to
*deploy* requires almost nothing, because all state already exists remotely. Two paths:

**Path A — just `git push` (simplest, nothing to install).** CD is already wired: any push to
`main` triggers the GitHub Actions deploy. From a second machine you only need `git` and push
access to the repo. This is the recommended default — you may never need flyctl on the second
box at all.

**Path B — deploy directly with flyctl** (for `fly logs`, `fly ssh`, manual `fly deploy`):
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

Fly snapshots the volume daily and retains them (default 5 days). Manage them:
```
fly volumes snapshots list <volume-id>      # volume id from `fly volumes list`
fly volumes snapshots create <volume-id>    # on-demand, e.g. before a big change
```
Restore by creating a new volume from a snapshot, then attaching it:
```
fly volumes create screener_data --snapshot-id <snap-id> --region sjc --size 1
```
For a true off-Fly copy (belt and suspenders), pull a consistent snapshot down on demand —
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
