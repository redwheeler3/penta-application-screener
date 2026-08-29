# Changelog

All notable resolved milestone work for the Penta Application Screener (Python/FastAPI + React/TS housing co-op application screener). Organized by milestone, newest first. This file holds resolved history extracted from `SPEC.md`; the SPEC itself tracks current-state design only.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/). Commit hashes are preserved where the SPEC or git history cites them.

---

## Milestone 22 — Built-In Vacancy Notifications (Production Cutover Pending)

Implemented the one-notice vacancy subscription flow, administrator reconciliation and narrow
management tools, opening-audience preview, live SocketLabs usage, and retry-safe delivery. Opening
an application cycle now durably queues its matching notice audience in the same transaction, while
direct selection can fill a home from a retained applicant without reopening applications or
sending a vacancy notice.

The final software prerequisite is complete: `scripts.create_historical_opening` dry-runs the exact
historical opening facts and reports the target application, existing participation, active
subscription, consent-receipt, queued-email, and matching-opening counts. Apply requires the exact
reconciled application count, refuses prior participation or a duplicate opening, attaches every
submitted non-withdrawn application at its original submission timestamp, refreshes retention, and
verifies notification state is unchanged before the transaction commits.

The milestone remains operationally open until the explicitly approved production cutover in
[docs/deploy.md](docs/deploy.md#vacancy-list-production-cutover): activate the applicant hostname,
create the historical opening, freeze and import the authoritative Google vacancy export, reconcile
it, switch the public website, and retire the Google form and sheet. No production operation is
part of this repository change.

---

## Milestone 21 — Built-In Applications And Committee Access

Replaced the external Google Form/Sheet intake path with the first-party applicant experience at
`applications.pentacoop.com`. One retained application can participate in multiple current or later
openings, while private drafts and archived-only applications remain outside ordinary committee and
AI workflows. Applicant and committee access use revocable server-side sessions, transactional
email is provider-neutral and retry-aware, and opening closeout drives unsuccessful notices and
retention.

All seven implementation stages are complete: canonical intake, email and sessions, the applicant
form, publication and opening participation, committee intake, retention and closeout, and
deployment preparation. The applicant hostname's Fly certificate, DNS, and live verification remain
part of the M22 production cutover. Production relies on daily Fly volume snapshots retained for 30
days. A separate
deletion-preserving Fly restore procedure was deliberately declined because restore-only
reconciliation state and ordering rules would make the disaster path more fragile. Restoring a
snapshot can reintroduce deletions made after it was taken, bounded by the backup window. Local
restores retain their deletion-ledger safeguard.

---

## Milestone 20 — Multi-Provider AI Routing And Model Bake-Off

Evaluated GPT-5.6 Luna and Terra against the existing Claude Haiku and Sonnet controls using
committed synthetic golden suites and production-shaped Rank runs, then made provider routing an
admin-controlled runtime choice. The deployed defaults remain Bedrock Haiku/Sonnet; direct
Luna-low and Terra-low were credential- and schema-verified from the production Fly Machine on
2026-08-22 without reading application data or changing settings. Detailed measurements and
reproduction commands are in [ADR 0013](docs/adr/0013-openai-model-selection.md); the routing
decision is in [ADR 0014](docs/adr/0014-multi-provider-model-routing.md).

- **3caba5a / aa32f1d — evaluate GPT through Bedrock and persist effort per pass.** Added Luna and
  Terra to the provider boundary, made reasoning explicit, and stored the selected effort beside
  each pass's model so provider defaults cannot silently change a measured configuration.
- **Quality selection.** Luna-low matched Haiku on the repeated Screening suite (51/51) and, after
  one provider-neutral scoring-calibration sentence, passed all 25/25 scoring judgments over five
  repeats. Terra-low passed all 45/45 decomposition, matching, and consolidation judgments over
  three repeats. Medium reasoning added no golden-quality gain and increased one production-shaped
  run from $0.6906 to $0.9177, so `low` remains the selected effort.
- **Production-shaped evidence.** Direct Luna-low/Terra-low completed two full synthetic Ranks with
  all 40 applicants scored, no failed calls, and no invariant violations. Discovery varied as
  expected, so dimension count and baseline overlap remained human-review signals rather than
  automatic quality scores.
- **f45abcd / c5c7e51 — add and validate direct OpenAI and Anthropic routes.** The same prompts,
  schemas, persistence, cost ledger, and observability path now work through Bedrock Claude,
  Bedrock GPT, direct OpenAI, or direct Anthropic. A direct Anthropic async-client lifecycle bug was
  fixed within the adapter; the corrected 10-worker control suite completed 111 calls with no
  transport or schema errors.
- **f4aa5f8 — share caches across equivalent routes.** Exact provider-native IDs remain in settings,
  traces, and cost rows, while provider-neutral pinned-model identities drive caches and Rank
  freshness. A route-only switch preserves valid work; a model or effective-reasoning change
  invalidates it.
- **c40d02f — preserve OpenAI audit observability.** Reasoning summaries and user-visible preambles
  flow through the existing streamed and persisted narrative path and are labelled as exposed audit
  text, not raw private chain of thought.
- **Admin routing.** The model catalog constrains valid route/model combinations, the UI disables
  direct routes whose server-side secret is absent, and installing a secret cannot change a live
  workload. Direct OpenAI is an availability choice for this production account, not the cheapest
  transport in isolation.

## Milestone 18 — Least-Privilege Google Auth

Split the OAuth footprint for eventual Google app verification and to stop showing members a scary Drive/Sheets consent screen. **Members now log in identity-only** (openid/email/profile — no Drive or Sheets scope); **an admin links the response sheet via the Google Picker**, granting only `drive.file` (access to the one picked file). Sync reads the sheet with that admin's designated-reader token, so members never need a Drive/Sheets scope. Verified against the deployed app (2026-07-26): a non-admin sign-in's callback granted only identity scopes, and every post-login call succeeded.

- **1313755 — designated sheet-reader + reader-scope plumbing (step 1).** Added `google_sheet_reader_user_id` to settings; sync and the settings title-read use that designated reader's token, falling back to the viewing user. Split scopes in config: identity-only `google_oauth_scopes` for login vs. identity + `drive.file` `google_sheet_reader_scopes` for the admin link flow.
- **2bc61cc — backend connect-sheet incremental auth + link-sheet endpoint.** `/settings/exchange-sheet-code` (exchanges the GIS auth code for tokens, `redirect_uri=postmessage`) and `/settings/link-sheet` (verifies the picked file is readable with the admin's token, then records the sheet id + marks the admin the designated reader). Both `require_admin`.
- **d03e528 — Google Picker sheet-linking + identity-only member login (step 2).** Frontend Picker flow; member login dropped to identity-only.
- **75bf7c5 — Picker via GIS code model + `setAppId` (the fix that made it work).** The `drive.file` scope requires `setAppId(<cloud project number>)` on the Picker for a picked file to be authorized — without it, linking a *different* sheet silently failed to read. Settled on the GIS code model (`initCodeClient`, `ux_mode: popup`) exchanged server-side for a refresh token (durable sync). (Earlier UX iterations: `56cd116` smoothed the connect-sheet return + cleaned orphan Picker DOM nodes; `815023c` tidied the Response-sheet section spacing/typography.)
- **97fc0bd — derive credential scopes from the token's own grant** rather than a static config list, so a token carries the scopes it was actually granted.
- **7b043d2 — wire Google Picker build args + go-live checklist.** `VITE_GOOGLE_PICKER_API_KEY` / `_CLIENT_ID` / `_PROJECT_NUMBER` as Docker build args (Vite bakes `VITE_*` at build time); deploy.md §8 documents the prod Google setup (enable Picker API, restrict the browser key, add `drive.file` to consent, re-link after deploy).
- **e3de5b5 — don't 500 the Settings page on a stale/revoked sheet token.** `build_settings_response` catches `(HttpError, RefreshError)` and drops the title (a nice-to-have label) rather than failing the page — seen right after deploy, pre-relink.
- **710bbf6 — exclude NESTED `.env` files from the Docker build.** A root-anchored `.dockerignore` pattern missed `frontend/.env.local`, which leaked `VITE_API_BASE_URL=http://localhost:8000` into the prod bundle and sent prod's API calls (incl. login) to localhost; fixed with `**/.env*` globs.
- **Post-M18 UI fixes** — `c082e6e`: linking a sheet now updates app state immediately (the linked sheet no longer vanishes on a tab switch) and refreshes the workflow bar (a sheet change poisons sync → amber shows without a manual refresh).

## Milestone 17 — Hosting / Go-Live (Fly.io)

Put the app in front of the real ~5-member committee — pure **infra**, sequenced after the M16 concurrency software. Now **live at screener.pentacoop.com**. Platform decision + full verified tradeoff analysis (9 platforms priced and timeout-checked) in [ADR 0012](docs/adr/0012-hosting-platform-m17.md); operational runbook in [docs/deploy.md](docs/deploy.md). All items verified against the deployed app (2026-07-26).

- **Platform: Fly.io** — auto-stop Machines + a persistent volume, the cheapest option (~$1–5/mo, near-zero idle) that keeps the DB on a durable disk. **Storage: keep SQLite on the volume** (zero data-layer change; fine for ~5 users) — retires the earlier "M17 may re-touch the data layer" tradeoff.
- **bc012b1 — single-origin refactor.** FastAPI serves the built Vite bundle via `StaticFiles`, so one origin, no CORS in prod (frontend calls the API with relative URLs). A two-stage Dockerfile builds the bundle.
- **89d3710 — Fly deploy scaffolding + prod auth hardening.** `fly.toml`, Dockerfile, `.github/workflows/fly-deploy.yml` (push to `main` ships); `https_only` cookie derived from `frontend_url` scheme; `SESSION_SECRET` + Google client + AWS keys as Fly secrets (never in the image); Bedrock via a static IAM key scoped to `bedrock:InvokeModel` in us-west-2 (no IAM role off-AWS).
- **9f86270 — stream heartbeat.** `HEARTBEAT_SECONDS = 15` emits a keepalive during the silent Sonnet passes, a 4× margin under Fly's 60s idle timeout on the multi-minute Rank stream (the blocking pass runs off the generator thread). Tested (`test_stream_heartbeat.py`).
- **306bbd0 — deploy runbook + make the post-rank auto-backup local-only.** Prod backup is scheduled Fly volume snapshots + an on-demand off-box `VACUUM INTO` copy; the local post-rank auto-snapshot is disabled in prod via `LOCAL_DB_BACKUPS = "false"`.
- **c1c810c — suspend (not stop) the idle machine** for sub-second resume.
- **Deploy shakeout fixes** — `bde3c35`/`2619d06`/`0ded43f` (app name, valid region `sjc`, co-op domain); `e57b2e4` (anchor `.dockerignore` globs so `backend/.venv` is excluded); `101645d` (deploy-from-another-machine docs + correct DNS record type); `0cb4943` (ADR 0012 marked deployed & verified); `10f9b3f` (first-Rank cost estimate assumes 35 dimensions, not a stale 15).

## Milestone 16 — Concurrency & Correctness

Multi-member introduced real concurrent writes — a **software** concern (guards, leases, atomic accounting) independent of where the DB lives. A concurrency audit (2026-07-24) classified the hazards; the load-bearing hardening landed and the residual items were deliberately deferred.

- **d5653d4 — serialize AI runs + harden SQLite for multi-member use.** A single DB-backed **run lease** (`RunLock` + `services/run_lock`, atomic conditional UPDATE, 15-min TTL steal so a crashed run self-heals) serializes Screen / full Rank / score-current and returns 409 `run_in_progress` if another holds it — closing the one genuinely destructive overlap (two concurrent full Ranks stranding the loser's `MemberRanking`) and concurrent-Screen double-billing. DB-backed (not in-process) so it survives multiple web workers. Plus SQLite `WAL` + `busy_timeout=5000` (`app/db/session.py`): readers don't block the writer, a colliding writer waits up to 5s instead of failing instantly.
- **92c4835 / 7826641 / e91d6e5 — stale-view detection.** The deferred M15 1b "this ranking was refreshed by another member" UX: a global toast with a Reload action (`stale_analysis` 409 on save + a cheap current-analysis-id check on tab focus/visibility, no standing poll), suppressed during the member's own run to avoid a self-inflicted false positive.
- **9a0df80 — workflow polish** — refresh the step badge on click, clearer run messages.
- **78840d0 — recorded the concurrency status** so the deferrals read as decisions, not oversights. **Deferred (deliberate):** (1) an atomic shared spending budget — its motivation (N runs racing past the cap) is already closed by the run lease, and a true committee-wide budget is genuine feature work needing product decisions; the per-run cap + near-100% cache hit-rate is the working control. (2) settings last-write-wins — rare and low-consequence at ~5 trusted members; optimistic concurrency would be over-engineering.

## Milestone 15 — Multi-Member Independent Screening

Made the app multi-member (~5 committee screeners) as an **isolation** feature, not a merge one (ADR 0011): each member screens independently — own eligibility rules, overrides, dimension tiering, ranking, notes — layered on a **shared compute-once substrate** (the applicant pool, the AI-discovered dimension set, and the expensive per-(applicant × dimension) scores). No merge formula, no disagreement flags, no criteria comparison, no cross-member visibility — the committee debates in a meeting with each member's own list in hand. Sharing rides on the content-addressed score cache (`(raw_row_hash, dimension_key, model, prompt_version)`, no member id), so an applicant scored once for any member is free for every other. Sliced into independently-migrated steps, each tree-green (ruff + pytest + `npm run build`), every DB change round-trip-verified on a copy with the live DB backed up before applying.

### Phase 1 — the data-model split + per-member eligibility

- **1a — Access allowlist + `require_admin` + config bootstrap** (`fdf7639`). Going multi-user made an access gate a safety prerequisite (an ungated deploy would expose applicant PII to any Google account). Additive `access_allowlist` table of `(email, role)`; the allowlist *is* role management (no separate promote/demote); OAuth login must match an entry or be denied (retires the "first login = admin" rule). Initial admins seeded from a gitignored `config/initial-admins.txt` at startup (idempotent, survives a DB reset, bootstrap-only). First genuinely admin-only surface — the deferred `require_admin` gate landed here.
- **1b — `RankingRun` → shared `Analysis` + per-member `MemberRanking`.** The choke-point split; `get_current_analysis()` replaced the `max(id)` `get_current_run`. A member's tier view of an analysis they didn't tier is materialized lazily by `get_or_create_member_ranking`, seeded by carrying their prior tiers forward (pure JSON, no AI). Tier/seed saves carry the viewed `analysisId` and 409 `stale_analysis` if it isn't current (inert at one member; makes the endpoint honest for real concurrency).
- **1c — per-member eligibility + union pool.** Eligibility became per-member via **compute-on-read**: `MemberEligibility` stores only a member's sparse overrides; effective eligibility = their override if present, else the machine verdict (`resolve_machine_status` over hard-filter reasons + cached flags). `status`/`status_source`/`reviewed_fingerprint` left `Application` (pure derivations that happened to be stored). The four pool filters became the **union** (eligible for ≥1 member); per-member staleness reduced to a cache-gap check (ADR 0011).
- **1d — settings split (numeric rules per-member) + tab reorg** (`50dc6f2`). Income/age/children/`disabled_rules` split off the shared `app_settings` blob into a shared **committee-default** row + sparse copy-on-write `member_rules` — the divergence that makes 1c's verdict actually differ per member. Infra config (sheet id, AI settings) stayed one shared row. Settings tab split by audience into **Eligibility Settings** (member; funnel) and **Admin Settings** (admin-only; gear, subtabs); Observability + Evals gated admin-only.
- **1e — pet policy as deterministic per-member facts.** Pets were judged inside the shared screening prompt (a `pet_policy` flag), so making them per-member was a screening-pass redesign. Pet judgment moved out of AI arithmetic: the shared pass now EXTRACTS neutral pet *facts* (`ScreeningReport.pets`) and a per-member deterministic hard filter decides pass/fail, so pet limits diverge without fragmenting the shared screening cache. `screening_prompt_version()` became argless (a pet-limit change is now a hard-filter change judged on read, not a cache invalidation). Migration `f6a7b8c9d0e1` moved the pet keys into `committee_default_rules` + backfilled `member_rules`. Real-Bedrock run confirmed extraction is reliable across multi-pet / exotic / negation phrasings (2026-07-24).
- **1f — admin-editable committee defaults + member reset-to-default** (`cfef0fb`). `DELETE /eligibility-rules` (member reset), `GET`/`PUT /eligibility-rules/committee-default` (PUT `require_admin`). Member Eligibility Settings shows a lazy "compared to committee default" divergence diff + Reset button; admin gets a Committee Defaults subtab. **Divergence model — whole-ruleset fork (Model A):** a member's `MemberRules` row is one complete JSON blob (a ruleset reviewed as a whole), not a sparse per-field patch — so an admin editing the default has **zero** side effects on diverged members (no reconciliation, no write-fanout), and Reset is a single atomic row delete. Rejected per-field override (Model B) because it would silently mint rule combinations no member reviewed.
- **1g — restore the two-phase eligibility mental model after pets.** A pet verdict needs the AI to read free-text first, so it lands at Screen, not Sync — which made the workflow read "some rules resolve at Sync, one shows up later." Fix was to put pets in the honest bucket, not relocate computation: **Move 1** (`resolve_machine_status` partitions reason codes — non-pet → `RULES`/Sync-knowable, pet-or-flag → `AI`); **Move 2** members can mute AI checks (the 9 flag categories + pets) the same way they mute deterministic rules, via `active_flags`; **Move 3** renamed `disabled_rules` → `disabled_checks` (one flat set spanning reason codes + flag categories; migration `b8c9d0e1f2a3`). Plus detail-page panel convergence (findings grouped by source; pets rendered as AI-style evidence cards with a neutral `PetFacts.reasoning`).

### Screening scope, evals, and workflow legibility (M15-era)

- **Screen scoped to the union of all members' rules + forced-eligible** (`cff73e1`). Screen previously scoped on the committee default alone, so a diverged member's rules-eligible applicants went unscreened (Screen 26/26 while Rank showed the union /41). New `rules_eligible_application_ids` widens Screen to the rules-only union, matching Rank; also folds in any applicant a member forced ELIGIBLE (they're in an active review pool, so the AI evidence matters most). Screen's denominator is now the pre-AI rules-eligible pool — "applicants needing an AI pass," a superset of the post-screen eligible count.
- **Screening eval hardening** — contested modeled as a bool that softens a MISS to amber (not a category list), for both fires/absent shapes (`7788b89`, `444da5e`); pipe-input sugar for any-of `fires` (`025d8af`); the suite made fully stable on Haiku via prompt tuning (no Sonnet bump). Dropped redundant flag categories; aligned flag labels to enum names.
- **Sync no longer false-ambers on eligibility-rule changes** (`ab76b7d`) — `settings_fingerprint` narrowed to the sheet id, since a rule change reclassifies on read with no re-sync needed.
- **Housekeeping** — dropped dead `SyncRun.eligible_count` / `filtered_out_count` (latent since 1c made eligibility compute-on-read; `457758d`); renamed internal "insights" → observability / AIQualityView (`c06bf81`).

### Future UX enhancements (built)

- **Re-rank nudge after a proposal** (`6975a7d`). A proposed axis is inert until a discovery run grounds it, and nothing else in the workflow changed when one was added — so it looked broken. The Rank step now ambers on a pending proposal (its own signal — proposals are deliberately absent from `rank_inputs_fingerprint`), and the Rank card leads with "Discover new criteria" as the primary action, naming the proposals. Frontend-only. Also fixed a stale card warning ("current criteria not rediscovered will be lost") — kept axes are MUST-survive, so only ignored ones can drop.
- **In-app member→admin feedback channel** (`8450d4f`, `1ae0187`). A member sends free-text feedback from any page via a low-key corner composer; it surfaces in an admin Feedback subtab. Each item carries the context the member was in (route, active tab, current ranking, and — from an applicant detail — which applicant, resolved to the current name on read), stamped server-side with identity + app version + time. Resolve keeps history (hidden by default, reopenable); the admin context chip links to the applicant/view. PII posture matches the rest of the app: login-gated write, admin-only read, never fed to AI, never logged or exported. New `feedback` table (migrations `4d135cde3491`, `725bae661bc1`).

### Phase 2 — per-member ranking respects the whole committee

- **Re-rank kept axes + discovery seeds scoped to the whole committee** (`83508be`). A re-rank read only the *triggering* member's kept axes and proposals, so one member's Rank could drop an axis another relied on or ignore their proposal. New `committee_kept_keys` (union of every member's kept axes, from each member's most-recent tiering — a member who skipped the last run still protects theirs) and `committee_proposed_dimensions` (union of all members' proposals, deduped case-insensitively) now feed the decomposition MUST-survive set and discovery seeds. Tier carry-forward stays per-member. Consolidation (per-member survivor tier), weight-0 for untiered axes, and the shared "Requested" pill unchanged — all per ADR 0011. No schema change.

### Phase 3 — per-member overrides + notes (verified)

- Both were already fully per-member from 1c (overrides: `MemberEligibility`; notes: `ApplicationNote`, both unique on `(application_id, user_id)`, scoped to `require_current_user`, notes provably absent from AI prompts/analysis/ranking/shared responses). Added the one missing guard — an API-level test that two members hold opposite overrides on the same applicant, each invisible to the other (`953b618`).

### Phase 4 — observability triggered-by-member stamp

- **Stamped the triggering member on shared runs** (`49197b4`). `RunCostLedger` gained a nullable `triggered_by_user_id` FK (no cascade — a run's cost history outlives a removed member; migration `282b33a17310`), wired at all three run kinds (Screen, Rank, score-current). The Observability last-runs surface shows a subtle "· triggered by \<member\>" stamp, omitted when unknown. Observability stays committee-wide — attribution, not per-member scoping (ADR 0011).

### As-built deviations from the plan

- **Per-requester proposal attribution dropped** (not deferred). Proposals are free text and the discovery model mints the axis key, so there's no deterministic proposal→key link to attribute on — and unioning proposals into one anonymous discovery seed list erases requester identity by the time the model returns. Would need a prompt-echo/heuristic + new stored member→key state; judged not worth it for a small committee. The shared "Requested" badge (every member sees it) stands. Recorded in ADR 0011.
- **Parked for later:** per-screening-check descriptions surfaced as info-icon tooltips (sourced from the prompt/deterministic logic), raised while building the check toggles.

---

## Milestone 14 — Code, Schema & Docs Cleanup

Behavior-preserving cleanup pass taken before multi-member (M15) and hosting (M16), so both land on a clean base rather than the accreted `criteria` blob and 1000-line grab-bag files. Grounded in a five-part audit (backend, frontend, DB schema, docs, best-practice research, 2026-07-20). Governing principles: delete dead code before de-duplicating; rule-of-three-gated extraction (over-abstraction is as bad as sloppiness); no backward-compat when it fights simplicity (DB reset is an acceptable fallback); each phase keeps the tree green (ruff + pytest + `npm run build`).

### Phase 1 — Dead-code removal (pure subtraction)
- Removed the dead in-UI harvest feature end-to-end: `HarvestPanel.tsx`, `harvestEvalCases`, `.eval-harvest*` CSS, the `EvalCaseEditor` judge template, backend `GET /evals/harvest/{family}`, `_HARVESTERS`, `HarvestResponse`, and the two tests pinning it (`fe6e9b6`).
- Removed 9 dead `types.ts` eval-result types and 4 spent one-shot experiment scripts (`fix_decomposer_why`, `coverage_gate`, `marginal_coverage`, `exp_single_call_discovery`) — kept `analyze_convergence` for the still-owed locked-pool experiment (`f3989b7`).
- Swept ~13 comment tombstones and trimmed dead `BLOCK_CONSUMER` entries (`eb51cfb`).
- Deferred to Phase 5: dead columns (`discovery_model_id`, `sync_runs.notes`) and the pre-fan-out "legacy" branches (they die with the schema work).

### Phase 2 — Harvest logic relocated to scripts
- Deleted `capture_scores`/`capture_screening`; replaced by self-describing `scripts/harvest_scoring_cases.py` + `scripts/harvest_screening_cases.py` + a shared `scripts/_harvest_common.py` (synthetic-source guard, opaque applicant index, evidence-source stamping), emitting the current uniform envelope, round-trip-verified against the live loaders (`a3df735`). This is the sanctioned "harvest via scripts, co-author cases" workflow that replaces the in-UI harvest.

### Phase 3 — De-duplication (rule-of-three gated)
- Hoisted the 5×-copied `_emit` into a shared `stability.emit` + `DeltaSink`, dropping 5 `type: ignore` (`e1155fd`).
- Extracted the three categorical passes' shared grading/stability/descriptor plumbing into `app/evals/_categorical.py`, −94 lines (`5be98d8`).
- Added a `useFetchOnce` hook over 5 Insights panels (`954288e`); `DiscoveryPanel` intentionally left out (real `runId` dependency).
- The ~10-endpoint eval registry was deferred into Phase 4a (folded with the `evals.py` split so the file is touched once).

### Phase 4 — File & module organization
Split the two 1000-line grab-bag routers and extracted the monster functions while **keeping** the existing technical-layer structure (`app/{api,ai,evals,services,domain,db,schemas,core}`). A full feature-folder restructure was considered and declined: ~90% of the readability win lives in splitting the two files, and an ~80-file reorg right before M15 was large risk for small gain.
- **4a** — `api/evals.py` (1049 lines) → `api/evals/` package (`_shared`/`catalog`/`cases`/`runs`) with the endpoint registry; the 3 categorical passes' 6 near-identical handlers collapsed into a `CategoricalPass` spec + `register()` factory, −200 lines (`758b472`, `5684163`). Largest file now 356 lines.
- **4b** — `api/ranking.py` (1147 lines) → `api/ranking/` package (`run`/`current`/`insights`/`shortlist`); `rank_run.stream()` (~410-line nested generator) broken into three `_stream_*` per-phase helpers, with `_CriteriaWork`/`_CriteriaResult` dataclasses replacing 11-element tuple hand-offs; `RunTally` renamed `ScoreTally` to reconcile a collision with screening's flag-count `RunTally` (`21f335b`, `158346f`).
- **4c** — Split the cost-estimation trio out of `ai/dimension_scoring.py` (625→458) into `dimension_scoring_cost.py` (185); deleted the dead `estimate_scoring_without_dimensions` alias (`2dcee6d`).
- **4d** — Extracted `App.tsx` (785→654) hooks into `src/hooks/`: `useToasts`, `useApplications`, `useRanking` (`5d22381`). `useAiRuns` deliberately not extracted (would need ~8 injected callbacks — the wrong abstraction).
- **4e** — Naming pass + dedup + `.clinerules` fixes (`39c863c`): `.match-audit-hint` → `.panel-hint` (~30 sites); deduped the `money` formatter; fixed stale `.clinerules` refs (`NumberInput` gotcha, `ScreeningRun`→`RankingRun`).

### Phase 4f — API contract redesign (plan-first)
A drift-and-consistency pass on top of M11's HTTP surface; Jeff approved all 3 changes 2026-07-20.
- **Change 1** (`766b0fc`): estimates uniformly at `<run>/estimate` — `/ranking/estimate`→`/ranking/run/estimate`, `/screening/estimate`→`/screening/run/estimate` — dissolving the estimate-placement and screening/ranking asymmetries.
- **Change 2** (`a29d07c`): collapsed the 12 eval run-routes to 6 — each pass is one `POST /evals/{pass}` with `?mode=stability`; retired the bare `/stability` (now `/judge?mode=stability`).
- **Change 3** (`f9a21f2`): `/ranking/insights/*`→`/insights/*` (top-level `api/insights.py`), since they span Screen + Rank + score-current.
- Kept (right-size guard): action-style run RPC, camelCase, RFC 9457.

### Phase 5 — DB schema rationalization
- Split the `ranking_runs.criteria` grab-bag blob (`0640362`) into `dimension_report` (JSON), `rank_inputs_fingerprint` (indexed String), `run_state` (JSON = tiers + new_dimension_keys + proposed_dimensions), and a new 1:1 `ranking_run_audit` table (narrative + match/fan_out/decompose/consolidate) so the hot path stays lean.
- Dropped derived `weights` (re-derived from tiers), dead `discovery_model_id`, vestigial `ranking_runs.name`/`.status`, and `sync_runs.notes`; made `dimension_aliases` the sole merge-truth.
- Migration `c84f612585ea` backfills in Python (never `CAST(text AS JSON)`, uses `batch_alter_table`), reversible. **Verified on the live DB: 6 runs + 5 sync_runs migrated intact; round-trip preserved everything — no reset needed.** `.db` backed up to `penta_screener.pre-M14-phase5.db` first.

### Phase 6 — Docs & SPEC reduction
- In progress: reduce SPEC to a ~500-line current-state living spec, extract resolved history into this CHANGELOG, adopt `docs/adr/` (MADR-style). Cut the four fully-superseded strata (pre-reframe judge design, deleted reconcile subsystem, removed essay-analysis, the favourite contradiction); re-term M11/M12-stale docs; archive point-in-time design docs.

### Phase 7 — Post-cleanup follow-up passes
Two fresh-eyes reviews after the Phase 1–6 churn settled, both behavior-preserving and tree-green each step (ruff + pytest + `npm run build`), rule-of-three throughout.
- **Second cleanup pass** over the modules the M14 splits churned most (the ranking + evals API packages, the extracted cost module and hooks, the big eval components). Confirmed the refactor was structurally sound — the large abstractions (the `CategoricalPass` factory, the worker-thread reasoning bridge, the extracted hooks, `App.tsx` as orchestrator) were correctly judged and left alone — and landed small fixes: removed a `CRITERIA_STAGES` identity dict; renumbered fossilized phase comments; de-privatized `missing_dimensions_by_application` (a split had turned a same-file helper into a cross-module import); typed the scoring estimate (`ScoringEstimate` TypedDict) and RunnableEval's whole result-render path (`EvalCaseResult`/`EvalRunResult`, replacing pervasive `any` that had silently disabled the sole `tsc` guard — surfacing three unguarded-optional reads); centralized the eval-key unions on `EvalKey`; cleared naming/comment drift.
- **Broad sweep across every layer** (all of `app/ai`, `app/evals` + `app/api/evals`, `app/services` + `app/db`, `app/schemas`/`domain`/`core` + the top-level API, every frontend component, all docs) on their own merits, not only split seams. **Dead code** removed (four unused pass `KIND` constants, `format_agreement`, `JudgeStabilityReport.counts`); **de-duplication** (`_BACKGROUND_PASSES` identity map collapsed, `seed_str` delegating to each pass's own formatter, a shared `_resolve_chains` chain-walk, `_audit_field` for the 7× audit-null guard, `current_dimension_kinds` for a 2-site null-dance); **type tightening** (a shared `CostEstimate` TypedDict; `StatusOverride` on `RequestModel`; a promoted `InsightRunKind`; centralized `EvalRunMode`/`EvalFixtureKey`); **eval-reframe fossils** cleaned; **six docs drift fixes** verified against code; and three approved structural changes — removed the test-only `analyze_one`/`analyze_application` screening path (coverage preserved via the production path), converted `DiscoveryPanel` to `useFetchOnce`, wired the previously-dead judge `label_rationale` into the Judge tab, and dropped the always-NULL `ranking_runs.owner_user_id` column (reversible migration, round-trip verified on a DB copy, live DB backed up first). Left alone as correctly-judged: the `CategoricalPass` factory, the worker-thread bridge, `WorkflowBar`'s prop breadth, and `streamNdjson`'s `any` (a genuinely heterogeneous stream boundary).

---

## Milestone 13 — Observability And Evals

Made the AI pipeline legible: what it cost, what it did, and whether it is any good. Motivated by a re-rank that carried 18/18 dimensions forward by identical key with no way to distinguish genuine re-discovery from match-pass over-matching. Locked plan (2026-07-07), built in order across four pillars plus failure capture.

- **Failure capture (2026-07-07):** `error_type` preserved on `PassResult` + durable logging on the error path; behavior-neutral prerequisite for failure rates.
- **Pillar 1 — Cost surfacing** (built 2026-07-08, unified 2026-07-12): a "Cost" Insights subtab (`CostPanel` / `cost_report.py`) showing cumulative + last-run AI spend broken down per pass with token/model breakdown. Unified all cost accounting onto one shared `PassCost` value object and a single `RunPassCost` table (under a `RunCostLedger` header) that both Screen and Rank write and both surfaces read — collapsing three prior parallel cost structures. Per-run cost is now exact (stamped at write time); every pass is attributed separately. Estimate-vs-actual reconciliation added 2026-07-16 (`RunCostLedger.estimated_usd`, additive migration `server_default='0'`).
- **Pillar 2 — Per-pass AI trace viewer** (reframed; done 2026-07-14): every pass's raw output made legible, match-audit included as one panel.
- **Pillar 3 — Operational metrics** (built 2026-07-12): an Insights "Trends" subtab (`MetricsPanel` / `services/metrics.py`) charting per-run/per-pass cost, tokens, wall-clock latency, cache-hit rate, failure count, and dimension count over time. Two `RunPassCost` columns added (`duration_ms`, `failed_calls`). Honest scope calls: failure counts are real for per-application passes but ~always 0 for fatal pool passes; retry counts deliberately NOT captured (would be a fake or heavy observability lie).
- **Pillar 4 — Property-based evals** (built 2026-07-12): `app/evals/` scores a committed PII-safe fixture against checks split by determinism — **INVARIANTS** (hard-fail pytest CI gate: `poles_present`, `no_protected_attributes`) vs. **SIGNALS** (report-only: `overlap`, `match_rate`). Transferable lesson: split by determinism, not by "is it an eval" — a check you'd soften to keep green is a signal, not an invariant. `one_concept` was cut entirely (semantic, deferred to LLM-judge); `no_protected_attributes` narrowed to whole-word unambiguous terms.
- **Pillar 4 next layer — LLM-judge evals** (first checkpoint 2026-07-14): `python -m app.evals.judge`, a non-gating spend boundary, one Sonnet call per human-labelled case. Coverage extended to **five of six model steps** by 2026-07-16 (consolidation, decomposition, matching, scoring, screening; discovery covered transitively). Established three disciplines: the fidelity rule (judge sees exactly what production saw — no `r` value leaked), the contested category (both verdicts defensible; consistency, not direction, is what matters), and `r` stays out of the confirm step. Score-defensibility judge added with a synthetic-source guard (`app/evals/synthetic_guard.py`, `require_synthetic_pool`).
- Watch-item recorded (not actionable): scorer **confidence** calibration — `medium`-confidence scores cluster in 0.4–0.7 and rarely reach ≥0.9; the broad "under-anchoring" hypothesis was dismissed by a 1363-row distribution analysis (healthy full-range distribution). Do not tune the prompt on n≈1.

---

## Milestone 12 — Database Schema Refactor + Terminology Sweep

Cleaned the persisted data model once the API contract was settled and aligned internal vocabulary with the data/API schema.

- `ScreeningRun` → `RankingRun` (table `ranking_runs`); legacy nullable-for-old-rows columns tightened to non-null (`ApplicationAIResult.prompt_version`, `SyncRun.settings_fingerprint`); the 7-migration chain squashed to one fresh baseline (`18fae53`).
- With "screening" freed by the model rename, the **Screen step** claimed it: route `/quality-flags` → `/screening`, AI-result `kind` `"quality_flags"` → `"screening"`, and the whole `quality_flags`/`QualityFlag*`/`qf*` family → a screening vocabulary (findings are now `flags`; the dashboard flag is `screened`).
- Consistency fixes: `PoolPatternReport` → `PoolDimensionReport`, `current_pattern_report` → `current_dimension_report` (the discovery act stays `discover_patterns`); generic `ScreeningResult` → `PassResult`; frontend types harmonized (`RankEstimate` → `RankEstimateResponse`, `RankingState` → `RankingResponse`, `ScreeningRunState` → `CurrentRunResponse`).
- `/sync` deliberately kept (not renamed to `/import`). Presentational CSS classes (`qf-*`, `quality-flags`) renamed too.
- **Naming principle (gem):** the code's internal vocabulary matches the data model and API schema, so a reader never translates a concept across layers.

---

## Milestone 11 — API Redesign

Redesigned the HTTP surface to best practices while there was no public contract to break (the only client is the first-party frontend, changed in the same commits). Scope: the API layer only — a contract refactor, not a rewrite of screening logic. Step one was an audit of ~21 endpoints, not edits.

Decisions locked (2026-06-26):
- **camelCase everywhere on the wire**, enforced by direction-split Pydantic alias bases in `app/schemas/base.py`: `ResponseModel` (emits camelCase), `RequestModel` (accepts only camelCase), `BridgeModel` (accepts both — the deliberate `AppSettings` exception). Domain dataclasses and storage schemas stay pure; casing lives only in boundary `*Out` models.
- **RFC 9457 problem+json for every error** — one machine-readable shape replacing ad-hoc `{detail: "string"}`. A single `Problem` exception + code→(status, title) registry in `app/core/problems.py`; the frontend branches on `code`.
- **Rename `/screening` → `/ranking`** — the router is the ranking subsystem and the UI calls it "Rank"; "screening" was actively misleading. `/screening/rank/run` → `/ranking/run`. The `/quality-flags` → `/screening` two-way rename was deferred to M12 (renaming the model frees the word with no collision). `/sync` deliberately kept — it is an idempotent upsert-by-email reconcile, and the codebase speaks sync throughout.

Sequenced before observability (M13) so instrumentation and a second actor (M15) build on a clean surface; the DB refactor (M12) lands in between.

---

## Milestone 10 — Committee-Ready Report

Shipped as browser print-to-PDF of the ranked view, replacing the originally-planned Google Docs generation. This removed the need for Docs/Drive write scopes — the app's only Google scopes are login + Sheets read-only.

---

## Milestone 9 — Interactive Weighting (Tier List)

The M8 equal-weight ranking was validated against the real pool and judged not good enough. M9 lets the committee say what matters and re-sorts instantly as deterministic math over cached `DimensionScore`s — no model call.

- **The interface is a tier-list maker, not sequential pairwise questions.** The committee drags dimensions into self-defined importance tiers (from 2 tiers to a strict stack rank) plus an **Ignore** zone (weight 0). This replaced the SPEC's original "what matters more — X or Y?" framing: direct beats indirect for a committee with opinions, and always-editable controls remove the lock-in that pairwise redundancy guarded against (so the anti-lock-in machinery and constraint-solver were unnecessary).
- **Tier layout is source of truth; weights are derived.** `weights_from_tiers` recomputes `criteria.weights` from the layout (non-ignore tiers get descending weight by position; Ignore = 0). Every weight traces to a tier position. The ranking engine (`rank_candidates`, M8) is untouched.
- Default layout: Critical / Important / Minor + Ignore, everything starting in one tier (so the opening ranking equals the M8 equal-weight baseline). Deterministic and trivially reversible; undo/redo is editing the layout. `@dnd-kit` for accessible drag.

### M9 fast-follows (all complete)

**1. Tier carry-forward on re-rank** (Phases 1–5, complete). A blind-discovery + identity-match two-pass that carries the committee's tier placements across a re-rank.
- Phase 1: `weights_from_tiers` falls back to uniform when no dimension has positive weight; `default_tier_layout` starts every dimension in Ignore.
- Phase 2: `app/ai/dimension_matching.py` returns high-bar one-to-one `{new_key → old_key}` matches; `carry_forward_layout` re-places matched dimensions and sends unmatched to Ignore. Ignore is modeled as the **absence of a placement** (`weights_from_tiers`: unplaced → weight 0), not a stored tier with an invariant.
- Phase 3: amber "New" badging for unmatched-new dimensions while in Ignore, with in-place acknowledge (per-badge ✕, "Clear all N new flags", or dragging into a tier); folded into the tiers PUT via `acknowledged_keys`. Post-Phase-3 bug fix: "New" branches on `old_key is None` (no match at all), not on whether a match landed in a working tier.
- Phase 4 (per-dimension score reuse): scores cached per-(candidate, dimension) under `dimension_scoring:<dimension_key>`; matched dimensions **adopt the prior key** (`adopt_matched_keys`), so cache + tier placement carry forward by key alone with no parallel lineage id. Batched scoring (one call per candidate scores all uncached dimensions); the thread-pool core extracted into `run_in_pool`. The whole-set `dims_hash` design was deleted.
- Phase 5 (estimator): the pre-run Rank estimate prices scoring as a whole-pool ceiling (it runs before discovery, so it can't know carry-forward savings); the match-pass cost folds into the combined estimate and single cap check only when a prior run exists.
- **Matching scope: all-history, not last-run (decided 2026-07-08).** `all_known_dimensions(db)` matches fresh discovery against every dimension ever discovered (one entry per key, latest definition), fixing runaway key growth (67 distinct keys for a ~20-25-concept pool) and stale-score cache collisions. "New" now means never-seen-in-any-run. Chosen over scoping the score cache to the match verdict because it also fixes the root cause and improves caching.
- **Post-score consolidation** (built + verified live 2026-07-11): a Pearson-nominate / LLM-confirm cleanup pass after scoring. Pearson correlation (default r ≥ 0.8) nominates near-duplicate score vectors; one cheap LLM call adjudicates by definitions — merge only on confirmed same-concept. Merge = alias the losing (newer) key to the winner; the alias is durable and feeds the match pass so future re-mints are adopted. Verified: 1 real merge, 5 correct keeps (including a 0.94 confound held apart), 0 over-merges. Consolidation stays a definition-based identity merge — it does NOT auto-deactivate on correlation (decided 2026-07-12), separating identity duplication (safe to merge) from mere correlation.

**2. Add-a-dimension mid-tiering** — done, realized by the Committee-Proposed Criteria feature: a proposed axis runs through discovery, gets a fresh key, and is the only uncached dimension, so scoring sends just that one dimension per candidate.
- **Committee-Proposed Criteria (propose):** free text a member writes, persisted on `criteria.proposed_dimensions`, fed to the next Rank's discovery as "strongly consider, but you decide," then cleared. Complementary to (not redundant with) automatic reconcile. Every dimension created from a request is flagged `from_committee_request` (provenance surviving renames/splits).
- **Favourite → "kept" (superseded 2026-07-17):** an earlier ★ "favourite" seed was slated for removal (2026-07-09), reversed and kept (2026-07-10) when reconcile was deleted, then **superseded** — favourite collapses into tier membership. New rule: a dimension in ANY working (non-Ignore) tier is KEPT; Ignore is the only "fair game to drop" bucket. `kept_keys(run)` derives the kept set from working tiers; the ★ UI, `favourited_keys`, and cross-run auto-keep union were all removed. Merge transfers the dropped twin's tier placement to the survivor.

**3. Surface weak spots in the ranked list** — done (pure presentation, no AI). Fixed two defects: a **label bug** (rows showed dimension *confidence* colored high→green, not the *score*) and a **selection bug** (rows chose dimensions by `weight × score`, which structurally only picks strengths). The fix: **`impact = weight × (score − pool_mean)`**, the exact per-dimension decomposition of `fit_i − avg_fit`. Contributions are selected/ordered by `abs(impact)` — sign carries direction, magnitude carries importance, the score band's color says strength-vs-weakness. Computed once in `app/domain/ranking.py`; the candidate detail page shares the same contribution objects via `app/services/ranking/view.py` and drops weight-0 dimensions.

**4. AI Criteria Coach** — deferred until the tier-list has been used against real data. Not a propose-the-tiering tool; its role is to help the committee understand and challenge the weighting they built.

### Fan-Out Redesign (complete — all phases built + committed)
The "first multi-agent workflow" the project parked, justified by evidence rather than proposed on spec. Replaced the sequential match-then-reconcile accumulation that never converged.
- **The decision and evidence:** a locked-pool convergence experiment (n=10) proved re-running the Rank chain to accumulate the "fullest set" does not usefully converge — discovery re-carves the same concepts at different granularities and the sequential machinery hoards every carving, because reconcile's per-axis variance test is near-unfalsifiable. Coverage/redundancy can only be answered with all carvings visible at once — hence fan-out.
- **The shape:** K parallel discovery calls (no scoring) → one decomposition step that sees all K reports and settles the finest non-overlapping set → score once against the settled set.
- **Cost model corrected from the real ledger:** per-(dim × candidate) score = $0.00087, discovery ≈ $0.17, settled-set scoring ≈ $0.52. Discovery is the bigger, uncached half, so K carries real linear cost → K stays small (default started at 4, raised to 5 on 2026-07-10).
- **Phase 1** (2026-07-09): the overlap judge `scripts/dimension_overlap.py` — pairwise Pearson correlation over cached score vectors. Validation caught a hand-diagnosis error: the three participation-commitment slices are behaviorally distinct (r=0.20), so collapsing them would have been an over-merge — the metric's highest value is as an over-merge guardrail. Default threshold r ≥ 0.8.
- **Phase 2** (2026-07-09): `discover_patterns_fanout` runs K calls in parallel via `run_in_pool`; new `AISettings.discovery_fan_out` (default 4). The dead single-call `discover_patterns` was removed (K=1 IS the single call, per D1).
- **Phase 3 — the bake-off** (2026-07-09): both D7 contenders run 3× on the historical fixture and scored by the Phase-1 judge. **Verdict: the single-call baseline wins; the multi-agent loop is NOT built into the product.** The merger↔splitter loop was strictly dominated (23% costlier, no more stable, worse on overlaps) — its Splitter is a one-directional force, a structural thumb on the scale toward under-merging. "Right-size the solution / don't buy multi-agent we didn't earn," decided by measurement.
- **Coverage gate** (`scripts/coverage_gate.py`): measured +36% real-differentiator territory (K-union 25 vs. single-run mean 18.4), padding excluded — confirming K fresh contexts buy real coverage. The completeness-critic fallback was NOT needed.
- **Phase 4** (all done): 4a wired `decompose_dimensions` into the chain (`read_timeout` raised to 600 for the heavy call); discovery timeout + partial-failure tolerance added 2026-07-16 (a failed fan-out worker is collected into `failed_count`; only all-K-failing is fatal; a degraded run surfaces a `WarningEvent`). 4b enforced D9 (committee-request protection) via the deterministic `enforce_committee_requests` backstop + tests. 4c (`0d52b7d`) deleted `dimension_reconcile.py`, its wiring, the reconcile estimate/audit/panel, and the losing bake-off machinery (`decompose_dimensions_loop`, `_split_back`, the Splitter prompts, `OverMergeReport`, `scripts/exp_decompose_bakeoff.py`); net −1190/+69 for the sweep. **Kept:** the overlap judge and the "Revived" badge (presence-derived, NOT part of reconcile).

---

## Milestone 8 — Deterministic Ranked List

Turned the M7 per-candidate scores into a ranked shortlist with **no new model calls** — pure deterministic math over cached `DimensionScore`s, which is what makes the M9 interactions instant, free, and reproducible.

- **Equal-weight baseline:** weights seeded uniform at run creation; fit is the weight-normalized average `Σ(weight·score) / Σ(weight)`. The AI never proposes importance.
- **Confidence is surfaced, not discounted** — shown next to the score but never folded into the fit number (confidence-weighting was considered and rejected: it hides a term).
- **Qualitative labels are relative bands** (Strong fit / Promising / Mixed / Limited) by rank percentile within the pool, not absolute cutoffs.
- **Ranking is a pure domain function** in `app/domain/ranking.py` — no DB or provider access, trivially unit-testable.
- **No fixed shortlist line** — an earlier configurable "shortlist line" with a live above-line count was removed as unhelpful (`criteria.shortlist_size`, the `/screening/shortlist-line` endpoint, and the `above_line` flag all removed). The list is stack-ranked; the committee reads top-down.
- Surfaced as a separate ranked view, not an in-place re-sort of the eligible table.

---

## Milestone 7 — Pattern Discovery And Dimension Scoring

The read-only AI foundation for ranking: discovers how this pool varies and scores each candidate on those axes, but does not yet rank, weight, or ask questions.

- **The defining decision:** the LLM extracts scored features; ranking is deterministic math on top. The model scores each candidate on discovered dimensions and never opines on importance. M8 starts every dimension at equal weight (an honest "no judgment yet" baseline); M9 is the only place weights diverge. Re-ranking the pool with the LLM on every answer was rejected (~300× the cost, slow, nondeterministic).
- **Two passes:** the **Pattern Finder** (pool-level, one synthesis-model call) discovers the differentiating dimensions for this specific pool — name, definition, why-it-differentiates — and proposes no weighting; **Dimension Scoring** (per-candidate fan-out, first-pass model) scores each candidate per dimension with rationale, evidence, and a confidence label. No call-level narrative (decided 2026-07-11) — the per-dimension rationale + evidence IS the observability.
- **Dimensions oriented so MORE is better fit (decided 2026-06-28):** direction is baked in at discovery, not left implicit; there is no per-dimension direction flag (an earlier `more/less/undecided` enum + sign-aware ranking was designed and reverted). "Goldilocks" axes reframe to a monotonic concept or split into two more-is-better dimensions. Empirically, the two-dimension split fires reliably only when the two forces are independently measured; a single-variable soft trait is (correctly) absorbed into a nearby measured axis.
- **Cache key includes dimension identity**, and `prompt_version` is derived by hashing each pass's static prompt text (a prompt edit invalidates that pass's cache automatically).
- **Inputs: essays and structured facts** via a shared `applicant_facts` view so the two passes never drift. Excluded: identifiers and real-estate ownership (a hard filter). Fields that are hard filters but still vary (income within band, household size, pets) are framed for residual variation only.
- **Dimension count is a guided range (5–25), not a fixed number**, biased to split; empirically ~14–16.
- **The whole Rank chain is gated on a pool fingerprint** — a hash of the sorted `raw_row_hash`es of the eligible pool. If unchanged, re-ranking is blocked (`/rank/run` → 409; estimate returns `ranking_current: true`). This supersedes the earlier "re-running always produces a fresh run" behavior — the pool must actually change to re-rank.
- **Surfacing UX:** the workflow is an ordered gated strip — **Import → Screen → Rank** — where Rank is one button running the whole essays → criteria → scores chain under one combined cost estimate (standalone per-pass endpoints removed). Steps go amber-stale by the same signal their no-op gate uses (Import on settings fingerprint, Screen on coverage, Rank on pool fingerprint). Rank streams phase-aware progress; the criteria phase streams the model's live reasoning as a "thinking" panel. A completed Rank lands the user directly in the ranked view. Every AI step opens a confirmation card before running, even when there's nothing to do.

---

## Milestone 6 — Essay Analysis (REMOVED)

**This pass no longer exists.** M6 added a per-candidate essay-analysis pass that extracted and normalized what applicants said (a neutral summary + structured per-signal fields mirroring the four essay questions), without judging. It was deleted after measurement showed its digest inflated tokens ~172% over the raw essays while buying no discovery coverage; discovery and scoring now read the raw essays directly (see `pool_digest.py`). The design record is retained in the SPEC for history.

- Key decisions while it lived: schema fixed (not adhoc), no `other`/catch-all field, first-pass model (Haiku), eligible applications only, status-independent, surfaced as a collapsed accordion below the raw essays, and no reasoning narrative (an A/B run showed the preamble produced no systematic change while costing ~18% more output tokens).
- Commits: added in `83edb35`; narrative dropped in `a860c64`; `evidence` field dropped in `2fa3906`; pass removed in `4e520ab`.

---

## Foundation (Milestones 1–5)

- **M1–4:** project scaffold + Google OAuth + SQLite schema; read-only Google Sheets import/sync + dashboard; deterministic hard filters + configurable rules engine + filtered-out view; application tables, candidate detail pages, and searchable/sortable views.
- **M5 — AI screening flags,** which also delivered the shared AI foundation originally listed under M6: the provider-agnostic interface (Strands + Amazon Bedrock, with a deterministic mock for tests), cached per-application analysis keyed on content hash + model + prompt version, a token pricing table, cost estimate, per-run spending cap, and raw-debug access via the candidate detail page. The **status model** was reworked here: `status` (eligible/ineligible) with a `status_source` (untouched/rules/ai/human), sticky human override, and a staleness signal when machine findings change after review.
