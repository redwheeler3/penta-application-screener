# API Reference

The authoritative contracts are generated from the running FastAPI application:

- [Interactive docs](http://localhost:8000/docs)
- [OpenAPI](http://localhost:8000/openapi.json)

This map covers the browser API and our own manual tests. Exact field shapes, query parameters,
and validation errors belong to OpenAPI; product policy belongs to [SPEC.md](../SPEC.md).
The Access column describes server dependencies. Public entrypoints still validate the Google,
magic-link, draft, consent, or publication facts required by their workflow.

Committee and applicant sessions use opaque server-side credentials in host-specific cookies.
Applicant responses are not cached. Opening-scoped reads and writes use `opening_id`; mutation
acknowledgements describe the submitted snapshot, not a later draft in another tab.

Screen, full Rank, score-current, and Evals stream NDJSON progress and a terminal summary/error.
Full Rank discovers criteria, scores, and consolidates them under one run lease. Score-current
fills missing scores against captured criteria without discovery. Board reads return criteria,
this member's applicants, and tiers together; without chosen priorities rank/fit/band are null.
Tier changes use cached scores without model calls. Spending reports describe known returned
usage from completed or failed attempts rather than promising an exact provider bill.

Application errors use RFC 9457 `application/problem+json`, with a stable `code`, HTTP `status`,
`title`, `detail`, and optional context fields. Request/response properties use camelCase;
query parameters and stored domain fields use their declared code/OpenAPI names.

Browser protected calls carry `X-Penta-Identity` (`committee:<user ID>` or
`applicant:<application ID>`). The server compares this captured page identity with the
credential before applying the action. A mismatch returns `session_changed` (409), without
changing credentials or another identity's data. Auth-state reads and the initial applicant
application GET are deliberate bootstrap exceptions. Manual non-browser test clients can omit
the header. Signed-out state can be bound explicitly with `applicant:none`.

Sign-out and withdrawal revoke server credentials without cookie-deletion responses; late
responses cannot erase a newer sign-in. Credential exchanges are coordinated separately from
ordinary requests. Return-link requests with no `baseRevision` do not save into a cookie's
current application and do not acknowledge a current-answer save. Ranking discovery and
consolidation audits expose captured configuration where it was recorded.

## Allowlist

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| GET | `/allowlist` | Read Allowlist | Admin |
| PUT | `/allowlist` | Add an allowed email or change its role. Adding an `admin` entry grants admin — the allowlist is the role-management surface. | Admin |
| GET | `/allowlist/denied-attempts` | Read Denied Sign In Attempts | Admin |
| DELETE | `/allowlist/{email}` | Remove committee access and revoke the account's sessions and unused links. | Admin |

## Applicant Intake

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| POST | `/applicant/access-links/inspect` | Inspect Applicant Access Link | Entry/link |
| POST | `/applicant/access-links/open` | Open Applicant Access Link | Entry/link |
| POST | `/applicant/access-links/regenerate` | Regenerate Applicant Access Link | Public |
| POST | `/applicant/access-links/request` | Save a new or authenticated draft, or return to an existing private record. | Entry/link |
| GET | `/applicant/application` | Get Applicant Application | Applicant session |
| PUT | `/applicant/application` | Save Applicant Application | Applicant session |
| DELETE | `/applicant/application/email-change` | Cancel Applicant Email Change | Applicant session |
| POST | `/applicant/application/email-change` | Request Applicant Email Change | Applicant session |
| GET | `/applicant/application/pending-copy` | Get Pending Copy | Applicant session |
| POST | `/applicant/application/pending-copy` | Reconcile Pending Copy | Applicant session |
| POST | `/applicant/application/submit` | Submit Applicant Application | Applicant session |
| POST | `/applicant/application/withdraw` | Withdraw one application and every opening participation from ordinary access. | Applicant session |
| GET | `/applicant/auth/google/callback` | Applicant Google Callback | Public |
| GET | `/applicant/auth/google/login` | Applicant Google Login | Public |
| DELETE | `/applicant/drafts` | Delete Applicant Draft | Public |
| POST | `/applicant/drafts` | Save Applicant Draft | Public |
| GET | `/applicant/openings` | Read Applicant Openings | Public |
| POST | `/applicant/submissions` | Publish a first application without making email access a submission gate. | Public |
| POST | `/applicant/submissions/check` | Stop an existing application at the pre-review boundary and email its owner. | Public |

## Applications

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| GET | `/applications` | Every application, unpaginated. A co-op pool is a few hundred rows at most, so the client holds the whole list and owns filtering, sorting, facet counts, and the favourites view — no server-side paging to keep consistent. | Committee session |
| GET | `/applications/{application_id}` | Get Application | Committee session |
| POST | `/applications/{application_id}/committee-notes` | Add one attributed application-wide note visible to the committee. | Committee session |
| DELETE | `/applications/{application_id}/committee-notes/{note_id}` | Delete Committee Note | Committee session |
| PATCH | `/applications/{application_id}/committee-notes/{note_id}` | Update Committee Note | Committee session |
| PUT | `/applications/{application_id}/note` | Create or replace the current member's private application note. | Committee session |
| GET | `/applications/{application_id}/retained` | Read a selected or direct-fill-eligible application outside ordinary scope. | Admin |
| DELETE | `/applications/{application_id}/shortlist` | Remove an applicant from the committee's shared shortlist, idempotently. | Committee session |
| PUT | `/applications/{application_id}/shortlist` | Add an applicant to the committee's shared shortlist, idempotently. | Committee session |
| DELETE | `/applications/{application_id}/star` | Unstar this applicant for the current member. No-op if not starred. | Committee session |
| PUT | `/applications/{application_id}/star` | Star (favourite) this applicant for the current member. Idempotent: the row's existence is the state, so re-starring is a no-op guarded by the unique constraint. A personal working aid — no effect on ranking, eligibility, or reports. | Committee session |
| DELETE | `/applications/{application_id}/status` | Remove this member's override, reverting their view to the machine verdict. | Committee session |
| PATCH | `/applications/{application_id}/status` | This member's human override of an application's eligibility. | Committee session |

## Auth

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| GET | `/auth/google/callback` | Google Callback | Public |
| GET | `/auth/google/login` | Google Login | Public |
| POST | `/auth/logout` | Logout | Public |
| GET | `/auth/me` | Get Current User | Public |

## Dashboard

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| GET | `/dashboard` | Read Dashboard | Committee session |
| POST | `/cached-results/refresh` | Apply existing matching screening and scoring references in the background without AI calls or spend. | Committee session |
| GET | `/dashboard/email-deliveries` | Read Email Delivery Issues | Admin |
| POST | `/dashboard/email-deliveries/socketlabs/refresh` | Refresh Socketlabs Delivery Status | Admin |

## Development Previews

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| GET | `/dev/previews/emails` | Render every application email without queueing or delivering it. | Public |

## Eligibility Rules

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| DELETE | `/eligibility-rules` | Reset this member to the committee default. Idempotent if they never diverged. Returns the now-effective rules, which are the committee default (`is_default` True). | Committee session |
| GET | `/eligibility-rules` | This member's effective eligibility rules and whether they are the shared committee default (no personal divergence yet) or the member's own. | Committee session |
| PUT | `/eligibility-rules` | Upsert this member's own rules (copy-on-write divergence from the committee default). After saving, the member reads their own rules, so `is_default` is False. | Committee session |
| GET | `/eligibility-rules/catalog` | Read Eligibility Check Catalog | Committee session |
| GET | `/eligibility-rules/committee-default` | The shared committee-default rules. Any member may read it — it's the baseline they follow until they diverge, and the Eligibility Settings page shows it as the "compared to committee default" reference. | Committee session |
| PUT | `/eligibility-rules/committee-default` | Update Committee Default Rules | Admin |

## Email Delivery

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| GET | `/email-delivery/status` | Read Public Email Delivery Status | Public |
| POST | `/email-delivery/status/refresh` | Refresh Public Email Delivery Status | Public |

## Evals

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| POST | `/evals/baseline` | Rebaseline | Committee session |
| GET | `/evals/cases/{eval_key}` | An eval's cases, straight from its committed fixture (free). 404 for an eval with no editable case set (invariants; stability reads the judge set). | Committee session |
| PUT | `/evals/cases/{eval_key}` | Upsert one case (by key) into the eval's fixture FILE (the operator commits it to git deliberately). Validated server-side; a bad payload is refused (422). | Committee session |
| GET | `/evals/catalog` | List the runnable evals + how many model calls each run costs (for the UI's spend-confirm). Free — computed from the committed fixtures, no model calls. | Committee session |
| POST | `/evals/consolidation` | Run Consolidation | Committee session |
| POST | `/evals/decomposition` | Run Decomposition | Committee session |
| GET | `/evals/invariants` | Run the deterministic invariants over the committed fixture. Free (no model calls). (Judgement signals — overlap, carry-forward rate — live on the Observability tab over the live run, which shows them better; they aren't duplicated here.) | Committee session |
| POST | `/evals/judge` | Run Judge | Committee session |
| GET | `/evals/judge-backgrounds` | The per-pass `judge_background` briefs the Judge tab lists + edits, with how many golden cases each pass contributes to the blind audit. Free (reads the committed files). | Committee session |
| PUT | `/evals/judge-backgrounds/{pass_name}` | Put Judge Background | Committee session |
| GET | `/evals/last-run` | Last Run | Committee session |
| POST | `/evals/matching` | Run Matching | Committee session |
| POST | `/evals/scoring` | Run Scoring | Committee session |
| POST | `/evals/screening` | Run Screening | Committee session |

## Feedback

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| GET | `/feedback` | List feedback newest-first. Open items only by default; `includeResolved=true` widens to the full history. | Admin |
| POST | `/feedback` | Record a member's feedback. Identity + app version are stamped here (not trusted from the body); route/tab/analysis are the context the client reported. | Committee session |
| POST | `/feedback/{feedback_id}/reopen` | Move a resolved item back to the open list (idempotent). | Admin |
| POST | `/feedback/{feedback_id}/resolve` | Mark an item handled (idempotent). It leaves the open list but is retained. | Admin |

## Health

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| GET | `/health` | Health Check | Public |

## Observability

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| GET | `/observability/cost` | Cumulative AI spend for the Observability tab, grouped by run. | Committee session |
| GET | `/observability/last-runs` | The most recent Screen and Rank runs, each with fresh spend + cache savings. | Committee session |
| GET | `/observability/metrics` | Operational trends across all completed runs — cost/tokens/latency/cache-hit/ failures per run and per pass, plus dimension count over time. | Committee session |

## Openings

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| GET | `/openings` | Read Openings | Admin |
| POST | `/openings` | Add Opening | Admin |
| POST | `/openings/direct-selection` | Add Direct Selection Opening | Admin |
| GET | `/openings/email-usage` | Read Opening Email Usage | Admin |
| POST | `/openings/preview` | Preview Opening | Admin |
| POST | `/openings/previous-applicants/search` | Find Previous Applicants | Admin |
| PUT | `/openings/{opening_id}` | Edit Opening | Admin |
| GET | `/openings/{opening_id}/selection` | Read Opening Selection | Admin |
| POST | `/openings/{opening_id}/selection` | Select Successful Applicant | Admin |
| POST | `/openings/{opening_id}/selection/no-household` | Select No Household | Admin |

## Passwordless Auth

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| POST | `/applicant/auth/logout` | Logout Applicant | Public |
| GET | `/applicant/auth/me` | Get Current Applicant | Entry/link |
| POST | `/auth/magic-link` | Request Committee Magic Link | Public |
| POST | `/auth/magic-link/consume` | Consume Committee Magic Link | Public |
| POST | `/auth/magic-link/inspect` | Inspect Committee Magic Link | Public |
| POST | `/auth/magic-link/regenerate` | Regenerate Committee Magic Link | Public |

## Ranking

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| GET | `/ranking/board` | Criteria, scores, and tiers from the same captured member view. | Committee session |
| GET | `/ranking/current` | The current analysis's dimensions + this member's view, or null if none discovered yet. | Committee session |
| GET | `/ranking/current/consolidate-audit` | The current analysis's consolidation audit — the post-score duplicate-merge pass: which correlated pairs were nominated and, per pair, whether the confirm call merged them (with its reasoning). Null when no audit exists. | Committee session |
| GET | `/ranking/current/decompose-audit` | Current Decompose Audit | Committee session |
| GET | `/ranking/current/fan-out-audit` | The current analysis's fan-out audit — each of the K parallel discoverers' dimensions + reasoning, so the discovery panel can show every discoverer, not just the one that streamed live. Null when no audit exists. | Committee session |
| GET | `/ranking/current/match-audit` | The current analysis's carry-forward audit — what discovery emitted, how the match pass mapped it onto prior dimensions, and the derived carry-forward rate. Null when no analysis or audit exists. | Committee session |
| POST | `/ranking/run` | Run the full ranking chain — find criteria → score → consolidate — streaming NDJSON. The combined cost is checked against the cap once before any model call, so an over-cap run fails fast with a 402 and spends nothing. | Committee session |
| GET | `/ranking/run/estimate` | Rank Estimate | Committee session |
| POST | `/ranking/score-current` | Fill missing scores without changing the current dimensions or tier layout. | Committee session |
| GET | `/ranking/score-current/estimate` | Score Current Estimate | Committee session |
| PATCH | `/ranking/proposals` | Apply one Add/Remove intent to current pending proposals. Returns the current seed state. 409 before an analysis exists (nowhere to store yet) or if the viewed analysis was superseded (stale_analysis). | Committee session |
| PUT | `/ranking/tiers` | Persist the member's new tier layout, derive weights from it, and return the freshly re-sorted ranking. Unknown dimension keys are rejected (422); a save against a superseded analysis is rejected (409 stale_analysis). | Committee session |

## Screening

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| POST | `/screening/run` | Run the screening pass over the candidate applications, streaming progress. | Committee session |
| GET | `/screening/run/estimate` | Estimate | Committee session |

## Settings

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| GET | `/settings` | Read Settings | Committee session |
| PUT | `/settings` | Update Settings | Admin |

## Vacancy Subscriptions

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| POST | `/vacancy-subscriptions` | Subscribe | Public |
| PUT | `/vacancy-subscriptions/admin` | Save For Support | Admin |
| POST | `/vacancy-subscriptions/admin/delete` | Delete For Support | Admin |
| POST | `/vacancy-subscriptions/admin/lookup` | Lookup | Admin |
| GET | `/vacancy-subscriptions/report` | Report | Admin |
