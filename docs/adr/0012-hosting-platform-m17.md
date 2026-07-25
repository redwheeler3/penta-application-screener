# 12. Hosting platform for go-live (M17)

- Status: **accepted** — Fly.io chosen (Jeff, 2026-07-25)
- Date: Milestone 17 planning (2026-07-25)

## Context

M15/M16 run locally on SQLite. M17 puts the screener in front of the real ~5-member
committee, so it needs a host. Two owner priorities, stated explicitly, drive the choice:

1. **Squeeze cost** — this is a small committee tool, not a business; the monthly bill should
   be as close to zero as is reasonable.
2. **Easy GitHub deploy** — deploy from the repo without a heavy ops burden.

And one decision already locked (Jeff, 2026-07-25): **keep SQLite on a persistent disk for
launch.** At ~5 users the data layer needs no change, costs pennies, and its only real cost
(single instance, no zero-downtime deploys) is irrelevant at this scale. Managed Postgres is a
later move, and only if the deferred atomic-shared-budget feature (M16 residual) is built.

### What the app demands from a host (from the codebase, not assumptions)

| Constraint | Evidence | Consequence |
|---|---|---|
| **Requests run for *minutes*** | Rank streams 5 sequential AI passes over the pool (`api/ranking/run.py` `_stream_criteria`) as NDJSON | Rules out short request-timeout hosts: Vercel/Netlify functions, Heroku's 30s router, **AWS App Runner's 120s cap**. |
| **Durable local disk** | 20MB SQLite (`backend/data/penta_screener.db`); WAL + busy_timeout set in `db/session.py` | Needs a real persistent volume that survives across requests/restarts. **This is the constraint that kills true scale-to-zero serverless** (see below). |
| **Bedrock coupling** | `StrandsProvider(region="us-west-2")` needs AWS creds at runtime | Off-AWS hosts need a static AWS access key stored as a secret (no IAM role). |
| **Two artifacts** | Vite bundle (~550KB) + FastAPI; wired cross-origin today via `VITE_API_BASE_URL` + CORS | Motivates the single-origin refactor (below). |
| **Tiny, bursty scale** | ~5 members, light concurrency (SPEC) | Smallest tier is fine; the cost *floor* dominates, which is why scale-to-zero is attractive. |

### The core tension: scale-to-zero vs. a durable SQLite file

The cheapest hosting model is **scale-to-zero** (pay ~nothing while idle). But "scales to
zero" generally means *the local disk goes away* when the instance stops — which is exactly
what a durable SQLite file cannot tolerate. This tension is what eliminates most of the
cheap-and-trendy options, and it's the single most important finding of the research.

The escape is a model where **compute stops but a provisioned volume stays attached** — which
is what Fly.io auto-stop Machines provide.

## Options considered (all figures verified against official sources, 2026-07-25)

Ranked by realistic monthly cost, holding the "keep SQLite-on-disk" constraint.

| Option | ~$/mo | SQLite-on-disk? | GitHub deploy | Long-stream limit | Verdict |
|---|---|---|---|---|---|
| **Fly.io auto-stop + volume** | **~$1–5** (idle floor ~$0.25–0.40) | ✅ volume persists across stop/start | CLI + GH Action; `fly.toml` + Dockerfile auto-generated | **60s idle** → needs heartbeat | **Recommended** |
| Hetzner VPS (CX22) | ~€3.79 (~$4) flat | ✅ native local disk | Self-managed; add Coolify/Dokku for git-push | none (you own the box) | Fallback: dead-simple, fixed cost, no heartbeat, but you self-manage |
| Google Cloud Run | **$0 idle** (generous free tier) | ❌ no safe disk | ✅ native source deploy, no Dockerfile | 60 min ✅ | Out on disk: GCS-FUSE / NFS mounts are **documented no-file-locking** → SQLite unsafe |
| Turso (libSQL) | $0–5 (free tier likely covers 5 users) | ⚠️ semantics only, DB in cloud | (pairs with any stateless host) | n/a | Only if "on-disk" is relaxed; small SQLAlchemy change (`sqlite+libsql://`) |
| Render | $7 flat | ✅ disk $0.25/GB/mo | ✅ native, auto-on-push; `render.yaml` | 100 min ✅ | Easiest deploy, but always-on floor is higher; no scale-to-zero |
| Railway | ~$5–12 usage | ✅ disk $0.15/GB/mo | ✅ native, auto-on-push | 15 min / 5 min idle | Close to Render; usage-based bill drifts |
| Cloudflare (Workers/Containers) | $5 floor | ❌ disk wiped on sleep | Wrangler/GH Action | Workers WASM; Containers sleep | Out: durability forces rewrite to Durable Objects / D1 HTTP API |
| AWS Lambda | ~$0 compute + EFS | ⚠️ EFS-only (NFS, VPC) | GH Action | 15 min via Function URLs | Out: SQLite only via EFS (fragile NFS locking, VPC), AWS-locked (owner rejected AWS) |
| AWS App Runner | ~$3–10 | ❌ no disk | ✅ native | **120s hard cap** | Out twice: **closed to new customers** + 120s kills the Rank stream |

### Why the eliminations are firm

- **App Runner** — AWS closed it to new customers in 2026 (steers to ECS Express Mode), *and*
  its 120s request timeout would kill every Rank. Dead on arrival.
- **Cloud Run** — the best *serverless* option (60-min streaming, $0 idle, effortless deploy)
  but has no persistent block volume; both durable mounts (GCS FUSE, Filestore/NFS) are
  **officially documented as having no file locking**, so SQLite is unsafe and slow. Viable
  only if we abandon SQLite (→ Cloud SQL) — which contradicts the locked storage decision.
- **Cloudflare** — Python Workers are beta/WASM/no-disk; Containers explicitly wipe disk on
  sleep. Durability forces a rewrite to Durable Object storage or D1's HTTP API.
- **Lambda** — can stream to 15 min via Function URLs and *can* persist SQLite, but only via
  EFS (NFS locking fragility, VPC complexity, always-on EFS cost, AWS lock-in the owner
  rejected).
- **Turso** — keeps SQLite *semantics* but the DB lives in Turso's cloud, not on our disk, so
  it does not satisfy "SQLite-on-a-disk." A clean fallback *if* that constraint is relaxed;
  migration is modest (`sqlalchemy-libsql` dialect, WAL-mode export, partial-PRAGMA caveat).

## Decision

**Host on Fly.io with auto-stop Machines and a persistent volume for the SQLite database.**

It is the cheapest option that keeps SQLite on a durable disk (~$1–5/mo, near-zero when idle),
requires no data-layer change, and deploys from GitHub via a committed `fly.toml` + a
`superfly/flyctl-actions` workflow. Compute stops when idle; the volume persists across
stop/start, so the DB survives.

**Accepted cost — the 60s idle timeout + heartbeat.** Fly's proxy closes a connection with no
bytes in either direction for 60s. Our Rank stream is *mostly* chatty — the per-candidate
scoring loop emits a `ProgressEvent` per applicant (`run.py:405`) — but the discovery /
decompose / identity-match / consolidate passes are each a single blocking Sonnet call where
the generator can sit silent past 60s on a large pool. So M17 must add a **heartbeat**: emit a
keepalive line (e.g. `{"type":"ping"}\n`, ignored by the client) every ~30–50s during those
gaps. This is **small-to-moderate** work, not a one-liner: the blocking pass call has to run
off the generator thread (or be periodically interruptible) while a ticker emits pings. It is
also portability insurance — it makes the stream robust on any proxy.

**Fallback: Hetzner CX22 (~€3.79/mo flat)** if we decide we do not want to run *any*
heartbeat/timeout logic. It has no request-timeout issue and native durable SQLite, at the
cost of self-managing the box (mitigated by Coolify/Dokku for git-push deploys) and a fixed
24/7 bill with no scale-to-zero.

## Consequences / M17 work (independent of the platform pick)

1. **Single-origin refactor** — serve the built Vite bundle from FastAPI (`StaticFiles`),
   collapsing two services into one. Removes CORS (`main.py:84` localhost pin), simplifies the
   session cookie to same-site, and halves hosting surface. ~15 lines.
2. **Prod-harden auth/session** — `https_only=True` on the session cookie (`main.py:83` is
   `False` today), real `SESSION_SECRET`, prod `FRONTEND_URL` / `GOOGLE_REDIRECT_URI`, and a
   new authorized redirect URI in Google Cloud Console.
3. **Bedrock creds** — a dedicated IAM user scoped to *only* `bedrock:InvokeModel` in
   `us-west-2`, its key stored as a Fly secret (`fly secrets set`). Small, well-understood
   surface — no IAM role available off-AWS.
4. **Deploy config** — `fly.toml` (auto-stop, `min_machines_running=0`, volume mount),
   auto-generated Dockerfile, `alembic upgrade head` on boot, GH Actions workflow.
5. **Heartbeat** in the Rank/Screen streams (per the decision above).
6. **Backup story** — today's local snapshot scripts (`backup-db.sh`) → a scheduled Fly volume
   snapshot + an off-box copy.
7. **Custom domain** — `screener.pentacoop.com` via `fly certs add` + a CNAME to the app's
   `.fly.dev` hostname. Free: Fly auto-issues/renews a Let's Encrypt cert, and the CNAME path
   uses Fly's free shared IPv4 + IPv6 (a *dedicated* IPv4 is a $2/mo add-on we do **not** need
   for a subdomain). Prod `FRONTEND_URL` / `GOOGLE_REDIRECT_URI` and the Google Console
   authorized redirect URI use this hostname.

None are blockers; they are the standard localhost→prod checklist plus the one heartbeat item.

## Notes

- Research method: two rounds of verified web research (2026-07-25) across Render, Railway,
  Fly.io, AWS App Runner, Google Cloud Run, Cloudflare (Workers + Containers), AWS Lambda,
  Turso, and Hetzner — pricing, request-timeout limits, disk/volume support, GitHub-deploy
  ergonomics, and Bedrock credential story. Source URLs captured in the M17 research
  transcript.
- This ADR is **proposed**, not accepted: it records the analysis and recommendation so the
  decision can be made deliberately. Promote to **accepted** once the platform is chosen.
