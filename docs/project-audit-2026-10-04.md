# Project audit — 2026-10-04

## Recommendation and baseline

There are additional changes worth tackling. I recommend the five findings below in four
cohesive work packages: preserve unsent committee notes, restore truthful navigation context,
repair and bound the public signup limiter, and remove the configuration dependency from
unrelated admin tools. I do not recommend another broad restructuring or adding more generic
concurrency infrastructure.

Reviewed baseline: `main` at `75e0032`, initially clean and synchronized with the locally
tracked `origin/main`. The audit below describes that pre-implementation baseline; temporary
reproduction tests were removed. The user approved all four work packages. All five findings
are now implemented and committed, including the related navigation and responsiveness fixes.

## Implementation complete

| Finding | Result | Commit |
| --- | --- | --- |
| F01 — private notes | Account-owned in-memory drafts and per-applicant ordered writes survive editor disposal; failures retain text and offer Retry save; page exit/sign-out warn about unconfirmed work; queued writes are fenced before credentials change | `9dda574`, with the responsiveness follow-up in the completion commit |
| F02 — navigation | History includes opening and review mode; guarded list selection and detail reads run in parallel; stale work cannot change the opening or reopen detail; unavailable openings cannot silently substitute another pool | `35844ba` |
| F03/F04 — public limiter | Canonical validated Fly client addresses only in the Fly runtime, transport peers locally; ignored caller-controlled forwarding headers; bounded expiry work and 10,000 live-key ceiling without evicting active quotas | `fab52b4` |
| F05 — independent admin resources | Configuration owns its load/failure/retry surface; the admin chooser and all five unrelated sections remain available | `e5fef1c` |

Related fixes stay within those owners: narrow save acknowledgements no longer cancel another
applicant's navigation; the workspace opening effect no longer erases restored detail; late
ranking reads inspect the live view before redirecting; redundant cross-opening/setup helpers
were removed. Shared-settings retry and captured-draft acknowledgements remain intact.

The final responsiveness review replaced workspace-wide keystroke updates with a small
per-applicant subscription using React's `useSyncExternalStore`. A regression first reproduced
two extra workspace renders for two edits, then verified zero extra owner renders with immediate
textarea updates. Confirmed notes are released once unobserved rather than cached for the account's
whole session; unsaved drafts remain available. This is a draft/editor boundary, not a general
application cache or state framework.

No note acknowledgement blocks internal navigation. Cross-opening history now waits for both
the correct list context and its detail, concurrently; perceived load time can therefore follow
the slower response. Admin resource navigation no longer waits for unrelated settings retries.
Limiter cleanup is capped at 128 expired buckets per request, under its existing in-process lock.
These are code-path and regression observations, not production latency measurements.

Final checks: **897 backend tests passed, one POSIX-only test skipped**; Ruff passed.
**258 frontend tests**, ESLint, TypeScript, and production build passed. Build/test cache directories
retain inherited Windows permissions. The owning-change review found no unresolved approved
finding; it does not claim that every possible defect has been eliminated. No schema migration,
database reset, provider/email call, production change, or push was performed.

Drafts are deliberately memory-only; the browser's normal exit warning and explicit discard
confirmation protect ordinary departures, but do not provide crash recovery. Production ingress
must remain Fly HTTP Proxy with Cloudflare DNS-only, as documented in `docs/deploy.md`.

## Coverage

| Area | Review | Result |
| --- | --- | --- |
| Backend | Inventory/reference checks over 189 app modules and 10 diagnostic scripts; dependency graph including deferred imports; focused reads of auth, applicant access/saves, committee mutations, openings, retention, email claims, maintenance, ranking, and spending | No import cycles or further proven dead helper paths; signup-limiter findings |
| Frontend | Runtime import graph across 129 non-test TypeScript files; focused review of auth/form lifetimes, note editing, navigation, opening selection, ranking writes/reads, shared settings, and admin composition | Note preservation, navigation, and admin dependency findings |
| Data/AI | Current selected-result readers, captured scoring work, complete chosen-score ranking, provider metering, lease cleanup, recovery boundaries, and retained-data support | Keep the recent guarantees; no new confirmed defect in these reviewed contracts |
| Styles/readability | Export/declaration references, nontrivial duplicate Python bodies, CSS references including dynamic class construction, and responsibility boundaries | No worthwhile additional removal or cosmetic splitting substantiated |
| Tooling/ops | Recovery/setup/dev wrappers, manual analysis readers, watchdog request/retry/alert lifetime, deployment topology, and config owners | Existing repair boundaries remain appropriate; proxy topology matters to limiter identity |
| Docs/API | Current owners and comments, generated OpenAPI compared with the endpoint map | All 111 method/path entries match; a few minor comments belong with their next owning edit |
| Verification | Full backend/frontend/watchdog baselines plus isolated current-behavior reproductions | Baseline suites pass; reproduced gaps are outside their current coverage |

The entire tracked source tree received inventory/reference checks; manual review concentrated
on complete workflows and their boundaries. This is not a claim that every line received equal
manual scrutiny or that no undiscovered bugs exist. No production service, applicant content,
provider call, database migration/reset/restore, deployment, or dev server was used for this audit.

## Findings

| ID | Priority | Finding | Owner |
| --- | --- | --- | --- |
| F01 | First | A private-note draft can disappear before its debounce sends it | Committee note/editor lifetime |
| F02 | Next | Browser navigation loses opening context and can retain the wrong read-only mode | Navigation/history identity |
| F03 | First | A supplied Cloudflare header can choose a fresh public-limiter bucket | Public request identity |
| F04 | With F03 | Expired public-limiter buckets remain in memory indefinitely | Limiter retention/capacity |
| F05 | Next | AI settings availability blocks independent admin tools | Admin/configuration ownership |

### F01 — Preserve an unsent private note when its editor is disposed

Evidence: [CandidateNotes.tsx](../frontend/src/components/applications/CandidateNotes.tsx),
lines 40–45 and 77–84. Edits schedule a save after 600 ms. Unmount cleanup clears that timer
without preserving or sending its latest value. The draft lives only in component state.

Reproduction: render an existing private note, type a new value, dispose the editor without
a blur event, and advance the timers by one second. The actual component sends **zero saves**.
Browser-history/programmatic navigation can dispose the detail without a pointer-triggered
blur, so ordinary click/blur coverage does not protect this case.

The separate write queues correctly protect ordering once a write is queued. They do not
protect an edit that never reaches the queue. A naive unmount flush is insufficient for every
transition: candidate-action requests are opening-scoped, while switching an opening can
invalidate that scope before the old editor's cleanup submits its note.

Recommendation: retain the latest unsent draft at the account/applicant ownership boundary
before disposing the editor, and drain it through the existing ordered writer. Internal
navigation should remain responsive. Preserve account-generation and server actionability
checks, so sign-out/account switching cannot send a note under another identity. For leaving
the application entirely, warn about unconfirmed work rather than claiming a last-moment
network send guarantees persistence. Do not introduce silent local storage of committee notes.

Regression matrix: browser Back, programmatic tab/opening change before debounce, change while
an earlier save is pending, latest draft superseding an intermediate one, failure/retry, and
sign-out/account switch. Preserve current serial/revert tests. Latency tradeoff: parent-owned
draft/write lifetime can avoid blocking internal navigation; waiting for an acknowledgement on
every navigation would be a separate tradeoff and is not my default recommendation.

### F02 — Navigation identity must include context and mode

Evidence: [useNavigation.ts](../frontend/src/hooks/useNavigation.ts), `BrowserLocation` at
line 7, `onPopState` at line 70, and the same-applicant return at line 110.

Two independent current-behavior reproductions passed:

1. Open applicant 42 under opening 1 and capture the history entry. Its state has no opening
   ID. Render opening 2, then dispatch a history return to that old entry. The hook calls
   `fetchApplication(42, 2)`, using the current opening instead of the entry's context. An
   applicant shared by both openings can appear with a different eligibility/ranking context;
   an applicant absent from opening 2 instead fails to reopen.
2. Open retained applicant 42, then call the normal `viewApplication(42)` method under a live
   opening. The applicant-ID shortcut returns before clearing the retained read-only flag or
   replacing the retained history identity. The resulting normal detail remains read-only.

Recommendation: use existing opening ID, applicant ID, tab, and retained/normal mode as the
navigation identity. Do not add a new synthetic identifier. I recommend recording/restoring
the opening with Back/Forward, using the existing opening-selection workflow and stale-request
guards before loading its applicant. If the intended product rule is instead that the current
opening persists across Back, incompatible history entries should be skipped/invalidated;
they should not be silently fetched under another opening.

The retained-to-normal transition should update mode and history even when the applicant ID
is unchanged. Preserve deliberate cross-opening reads, account-keyed workspace disposal, and
late-response fencing. Regression matrix: same applicant in two openings, applicant present
in only one, Back/Forward while an opening/detail request is pending, and retained/normal
transitions for the same ID. Opening-context restoration is the product choice to settle;
the sticky read-only mode is a confirmed implementation defect.

### F03 — Derive public limiter identity from a trusted ingress

Evidence: [vacancy_subscriptions.py](../backend/app/api/vacancy_subscriptions.py), lines 44–48
and 68. `_client_key` prefers `cf-connecting-ip` whenever supplied, with no trusted-proxy check.

Isolated reproduction: construct 11 requests with the same transport client address but a
different supplied header. The production key builder selects 11 different buckets, and the
production limiter admits all 11 even though its configured limit is 10. This runs only the
key/limiter functions; no signup or production request was sent. Valid IP strings can also
be varied, so validating only the header's syntax does not establish trust.

The documented deployment uses Cloudflare **DNS-only**, not a Cloudflare HTTP proxy
([deploy.md](deploy.md), line 205). Treating a Cloudflare-named header as proof of origin does
not follow that topology. Fly documents its HTTP-handler-added `Fly-Client-IP` and warns that
forwarded identity must be handled with spoofing in mind. A reverse proxy ahead of Fly changes
what that address represents. [Fly request-header documentation](https://docs.fly.io/networking/request-headers)

Recommendation: explicitly establish the trusted client identity for the documented Fly ingress,
with transport-client fallback for direct local tests. Ignore Cloudflare client headers unless
a trusted Cloudflare-proxy path is deliberately configured. Canonicalize/bound the selected
address after establishing its trust. Preserve legitimate clients' separate buckets; using a
shared proxy peer for everyone would create false throttling. No proxy/deployment changes are
authorized by this audit; any such change needs its own review.

Regressions: repeated requests from one transport client with forged Cloudflare headers,
the accepted Fly ingress identity, local fallback, malformed/oversized identity, and distinct
legitimate clients. This should require no database, provider, or blocking network operation.
The application-boundary weakness is confirmed; current production edge filtering was not
tested, and no claim of a demonstrated production exploit is made.

### F04 — Expire and bound the limiter's client map

Evidence: [rate_limit.py](../backend/app/services/auth/rate_limit.py), lines 12–23.
The deque is pruned only when that exact key returns. Its dictionary entry is never removed;
timestamps for clients that never return also remain. `clear` is a test/reset operation rather
than a production expiry path.

Reproduction: admit one attempt for each of 1,000 synthetic clients; advance by one day
with a 15-minute window, then admit a fresh client. The map still holds **1,001 buckets**.
This retains obsolete client identifiers and grows for the process lifetime. F03 makes
arbitrary new keys particularly easy to create.

Recommendation: expire idle buckets and bound live cardinality under the existing lock. Keep
cleanup amortized/bounded rather than scanning a large map on every request. At capacity,
do not erase active quotas in a way that resets a caller's allowance. Keep this small and
in-process for the documented deployment; a distributed limiter or new database service is
not justified by the current application scale.

Regressions: old inactive keys disappear, active-window quotas survive cleanup, capacity
handling cannot reset active quotas, and concurrent callers still share one allowance.
Implement F03/F04 together. Expected effect is lower retained memory; measure request-time
cleanup cost before choosing a pruning cadence.

### F05 — Keep independent admin tools available without AI settings

Evidence: [CommitteeWorkspace.tsx](../frontend/src/CommitteeWorkspace.tsx), lines 429–449,
and [AdminSettingsPanel.tsx](../frontend/src/components/admin/AdminSettingsPanel.tsx),
lines 64–90. The entire admin panel mounts only when the shared AI-settings draft exists.
Only its Configuration branch consumes that draft. Openings, Access, Notifications,
Email Delivery, and Feedback have their own resource readers and actions.

Consequently a slow/failed `/settings` GET replaces every admin subtab with the settings
loading/error view, even when its own endpoints work. The alert's Openings/Email Delivery
links cannot reach their tools in this state. This is confirmed control flow, not a measured
production outage. Shared settings uses five read attempts; with the 15-second GET deadline
and existing backoff, one timeout cycle can take about 84 seconds before it settles.

Recommendation: mount admin navigation independently of the AI configuration resource. Keep
configuration loading/error/retry state within its owning Configuration view, preserving draft
acknowledgements and save ordering. Allow the other subtabs to load their own resources and
show their own failures. Do not add a second settings cache or change retry policy just to
unblock unrelated tools.

Regressions: delayed/rejected settings alongside successful Openings/Access/Feedback loads,
configuration retry and unsaved draft preservation, and admin-role gating. This is both an
ownership simplification and a responsiveness improvement; it adds no required wait.

## What I would leave alone

- No further proven unused production declarations or substantial exact duplicate Python
  bodies emerged. `ensure_lock_row` supports schema-only tests; `FlyWatchdog` is a deployment
  entrypoint. Initial CSS misses are dynamic role/phase/status/column/badge/view classes.
- Retained imported-answer readers support stored records. The retired intake integration
  does not justify removing their data support. Do not add a data migration to this cleanup.
- Keep captured save acknowledgements, account/consent/request generations, ordered writes,
  stream cancellation/lease fencing, selected-result provenance, complete score transactions,
  and returned-usage receipts. Their distinct contracts still warrant the additional code.
- Keep the zero-weight/unranked behavior and complete chosen-score ranking. I did not find
  another confirmed flaw in their reviewed transitions. Relative band semantics are an existing
  product policy, not a reason to quietly change the ranking formula.
- Keep the cohesive ORM registry and domain service packages. No file split, general state
  machine, cache framework, blanket strict-typing migration, or formatting rewrite is justified.
- Minor stale comments (for example the admin tab's removed data-source description and the
  rule file's old JSON-column example) should accompany an owning edit, not become independent
  projects. The diagnostic overlap tool's global scope is stated; changing it is optional,
  not a newly confirmed defect.

## Verification and implementation scope

Fresh checks on the unchanged baseline: **890 backend tests passed, one POSIX-only test skipped**;
Ruff passed. **229 frontend tests**, ESLint, TypeScript, and production build passed. Watchdog
TypeScript and **9 tests** passed. Python import cycles: zero. Runtime frontend imports resolve;
only test setup/support and compiler declarations are outside the runtime graph. The current
API index matches all 111 generated method/path pairs.

Three temporary frontend tests verified the current note/navigation failures and were then
deleted. They deliberately asserted existing faulty behavior to demonstrate the triggers;
they are not regressions proving a fix. Two isolated Python probes verified limiter bypass
at the request boundary and expired-bucket retention. Implementation must invert those
expectations into meaningful regressions through the owning component/request boundary.

Recommended sequence: (1) trusted, bounded limiter identity; (2) note preservation with an
account-safe writer lifetime; (3) navigation context/mode after settling Back behavior;
(4) independent admin resources. Keep all approved items and confirmed related follow-ups
in one implementation task with cohesive commits and a final workflow review. Nothing needs
a schema migration or provider call. No significant new waiting is needed for the recommended
approach; any decision to block navigation on a note acknowledgement should be discussed first.
