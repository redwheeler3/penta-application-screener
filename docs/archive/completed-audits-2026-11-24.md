# Completed codebase audits, November 24, 2026

Historical findings, decisions and verification for the two completed audit rounds. Current product behavior is documented in [SPEC.md](../../SPEC.md).

## Ponytail audit — November 24, 2026

**Status: implementation authorized November 24, 2026.** Jeff approved all 13 recommendations
and local commits. He also approved conservative deletion of affected pool-level narratives and
applicant-specific justifications at the first contributing applicant purge, retaining numeric
costs and demonstrably non-identifying criteria. All 13 findings are implemented and locally verified; the completion record below distinguishes
automated checks from real-provider observations and bounded Chrome verification.
The findings below preserve the pre-fix audit evidence. Application baseline:
`220a3b60c72f8438b48d3c18f8e60ec986963dc5`. All passes used unchanged application code.

**What this repo does:** Penta collects and retains housing applications, manages opening outcomes
and mail, and helps committee members screen and rank candidates using shared AI evidence and
personal priorities. Expected load is one Fly process, approximately five committee members,
300 applications, and 1,500 vacancy subscriptions. Overlapping applicant requests, committee work,
and background email/maintenance are normal; the public intake boundary must also withstand abuse.

### Passes and stopping evidence

| Pass | Perspective and result |
| --- | --- |
| 1 — user journeys | Traced guest/email/Google access, saved vs submitted answers, opening publication/decisions, notices and applicant recovery. Found unthrottled public intake, broken frontend verification, and the native income widget (4, 8, 11). |
| 2 — data transformations | Compared eligibility consumers and traced criterion identity, cache reuse, export provenance and aggregate deletion. Confirmed the three larger privacy/identity findings (1–3); the 24 list/detail comparisons and union/Screen/Rank scope checks agreed. |
| 3 — adverse sequences | Challenged partial discovery failure, a later ordinary applicant entering a synthetic analysis's opening, corrupted browser storage, leases/disconnects, selection/purge overlap and email consent generations. Added proposal loss, recovery failure and missing failure counts (5, 6, 9); strengthened finding 1 with a second reproduction. |
| 4 — simplification and contracts | Reviewed actual call sites, schema/prompt meanings, nested editor shapes, deployment/build/scripts and the watchdog. Added only smaller prompt/editor/dead-helper recommendations (10, 12, 13); no new high-impact defect. |
| 5 — request-lifetime challenge | Repeated a guest collision using a separate session for each HTTP request. Found a real rollback hidden by the existing test's shared session (7). Followed the shared mail helper through both collision consumers. |
| 6 — closing challenge | Checked every magic-link sender caller and the alternate sent/failed/coalesced branches; ordinary draft/access saves explicitly commit their suppressed-mail paths. Rechecked all findings against consumers, existing success tests and documented limits; revisited every coverage row. No further material issue remained unexamined within this bounded coverage. |

Returns diminished after the broad passes: pass 4 added only small contract/tooling cleanup,
pass 5 found one substantive transaction defect, and the focused follow-through/final challenge
added none. That late defect was followed to closure in the audit rather than ignored to meet a
stopping target. Stopping also depends on the coverage map and explicit gaps, not a finding count. This is a bounded audit, not a claim that every line or defect was found.

### Coverage and evidence

For each row, review covered correctness, failure/concurrency, supported value shapes, consumer
agreement, unnecessary work and readability. `Read` means source tracing; `Test` means existing
checks actually executed; `Probe` means a separate synthetic reproduction. Tests are not treated
as proof of model judgment, browser gestures, production state, or the absence of other bugs.
Backend paths in this table are relative to `backend/app/`.

| Area | Source and scenario coverage | Executed evidence and limits |
| --- | --- | --- |
| Applicant intake | Read `api/applicant/{guest,application,google}.py`, `services/applications/{intake,drafts,access}.py`, answer/submission schemas and frontend save/review/lifecycle/storage owners. Followed collisions, incomplete drafts, stale revisions, closed/archived choices and primary-email authority. | Test: applicant, submission, identity and copy-concurrency suites. Probe: 12 same-source unique submissions plus 12 same-address draft saves; corrupted stored record; corrected-selector copy of guest-review tests; repeated collision with separate request sessions. Found 4, 6, 7, 8, 11. No live mailbox, Google round trip or browser date-entry test. |
| Identity and authority | Read dependencies, cookie identity binding, passwordless/applicant/committee resolvers, admin writer guard, browser API factories and session refresh. Checked host-only cookie policy, active allowlist, revocation and queued-work identity capture; kept one session model. | Test: auth/passwordless, identity concurrency, admin-write authority, operator access, frontend identity/client/session tests. No live OAuth configuration or dependency-advisory check; no claim about external provider availability. |
| Openings and mail | Read catalog, participation, selection, protection, notice/audience/subscription ownership, delivery reservation/outbox/sender and admin opening workflows. Traced preparing → publication → decision, whole-consent consumption, failure/retry, current recipient and ambiguous acknowledgement. | Test: opening edit/write/selection concurrency, decision outbox, notice eligibility, email and vacancy-consent suites; frontend opening/decision tests. Reviewed acceptance-before-consumption and absence of provider I/O under the send writer. No actual messages or 1,500-recipient load run. |
| Retention and recovery | Read retention clauses, purge, result ownership, maintenance, backup service and root backup/restore wrappers. Checked Pacific expiry, legal hold/selection, WAL-safe restore, deletion bounds, allocation high-water marks and restored authority. | Test: retention transitions/purge/protection/schema, result retention, migrations, backup and maintenance suites. Probe: a purged participant's marker remains in its opening's analysis/audit prose (2). No local real DB reset/restore and no production snapshot rehearsal. |
| Eligibility and pool consistency | Read pure filters/status, per-member rules/union, list/detail presentation, opening scope, submitted facts and ranking assembly. Examined income/age/child/pet/employment/property boundaries, muted flags, an override, selection and missing-score semantics. | Probe: identical 12 synthetic households under two policies; all 24 list/detail comparisons matched, individual eligibility matched list output, union matched scoring, and pre-screen scope matched its rule union. Existing ranking/age/cache tests also passed. No claim of statistical fairness or model accuracy. |
| AI and ranking | Read cached/fresh publication, provider adapter, discovery/decomposition/matching/scoring/consolidation, selected-result references, cost meters, rank persistence/member history and run lease/stream lifetime. Checked no-priority and partial-score behavior, timeout/storage failure, aliases and tier ownership. | Test: AI/scoring/identity/tier/pool/cost/metrics, lease-renewal, cancellation and HTTP-disconnect suites; frontend ranking/run tests. Probe: same label/different definition with a model returning no match (3); seeded-worker failure/proposal clearing and zero persisted failure count (5, 8). No paid calls; prompt judgment and latency remain unmeasured. |
| Evals and observability | Read fixture export/synthetic guard, both applicant harvesters, categorical/stability/Judge collectors, history/result presentation and nested editor. Traced errors vs contested cases, attempted repetitions, local-write/admin gates, nullable values and provenance. | Test: eval completion/experiments/history/cases, stability/Judge and editor suites. Probe: non-synthetic baseline would publish nested marker prose; later non-synthetic applicant passes historical analysis guard (1); nested scalar/object/list controls and null-to-string editing (11). File write was intercepted; committed eval data was not changed. |
| Browser and operations | Read API deadlines/stream parser, request scopes, navigation, note queues, settings/board refresh, applicant persistence, print/report ownership, Docker/Fly config, backup wrappers and all three watchdog source modules. Checked acknowledgement ordering, scope changes, cancellation, watchdog restart/host/lookup recovery and pause. | Test: frontend suite/build/lint; watchdog tests/type check; backend deployment/stream/backup tests. The current workflow already uses short writes, shared helpers and bounded worker pools. No full visual/accessibility/print walkthrough, gesture test, deployed watchdog check or production load profile. |

Verification results against the unchanged baseline:

- Backend: **1,330 passed, 1 skipped**; complete Ruff check passed. The first sandboxed pytest run
  hit the established temporary-directory permissions issue; the successful run used the same
  configured directory outside the sandbox. No application failure was attributed to that run.
- Frontend: **474 passed, 2 failed** across 54 files; build passed. Lint failed on the unused
  `preview` in `OpeningsPanel.test.tsx:58`. Both failed tests stop at the obsolete date-field query
  in `ApplicantReviewAdmission.test.tsx:157`, before reaching their intended adverse sequence.
- Temporary probes: **13 frontend checks passed** in the copied guest-review/shape probes, plus
  **1 storage reproduction passed**. The copied review suite passes with label-based field lookup;
  its original file remains unchanged. Python boundary/privacy/failure and separate-request-session probes reproduced the
  documented outcomes using isolated in-memory SQLite and captured providers/mail only.
- Watchdog: **43 tests passed** and TypeScript check passed. All temporary probe files were removed.

### Must fix

1. **Exports can label ordinary applicant evidence as safe synthetic data.**
   - **What this is:** `evals/fixture.py:168` writes the baseline; `_harvest_common.py:33` trusts an
     analysis stamp before the scoring/screening harvesters read today's candidates.
   - **Problem:** Baseline recording accepts a non-synthetic analysis and retains nested prose.
     A later non-synthetic applicant can also enter an originally synthetic opening and be harvested
     under its old stamp. Both synthetic-marker probes reproduced the unsafe boundary; no real leak
     was inspected or claimed. `docs/ai-evals.md` already warns about these limits.
   - **Fix:** Enforce the synthetic boundary at every export over the actual exported inputs and
     source analysis/history; preserve provenance from the pool captured before calls, rather than
     recomputing it later. Refuse unknown/mixed evidence before publishing a file or printing cases.
   - **If we skip it:** An operator can follow the advertised harvesting/re-baseline workflow and
     put real applicant text into a Git-tracked fixture.
   - **Owner/check/cost:** `services/ranking/{pipeline,analysis}.py`, `evals/{fixture,synthetic_guard}.py`
     and both harvesters. Check non-synthetic baseline refusal, late arrival, withdrawal during
     discovery, inherited non-synthetic criterion prose and unchanged destination on refusal. Reuse
     existing provenance/guards; remove duplicate weaker assumptions. Only bounded local reads;
     no extra provider call or waiting on the applicant path.

2. **Applicant purge leaves pool-level AI text behind.**
   - **What this is:** `services/applications/purge.py:155` erases application aggregates; an opening's
     `Analysis`/`AnalysisAudit` owns separate narratives and pool justifications.
   - **Problem:** Purging a participant leaves its synthetic identifying marker in discovery
     narrative, fan-out prose and `why_it_differentiates`. These free-text fields can quote applicants;
     their lifetime is not tied to the source applicant. Hiding an opening does not erase its rows.
   - **Fix:** Include applicant-bearing pool text in the retention boundary. Prefer conservative
     cleanup by the existing opening/participation scope over a paragraph-level tracking system;
     retain only demonstrably non-identifying criterion identity and numeric expense facts.
   - **If we skip it:** The stated aggregate-deletion guarantee is incomplete even when direct
     applicant rows, credentials and per-applicant cache results disappear correctly.
   - **Owner/check/cost:** Purge/result-retention owners plus ranking audit/report persistence.
     Before implementation, agree what historical prose must be removed when source lifetimes differ.
     Seed markers in every copied/nested prose destination, purge through normal and restore paths,
     and check that unrelated retained applicants and numeric costs survive. Consolidate cleanup in
     aggregate erasure; no new live-read polling or provider cost. Historical trace detail may shrink.

3. **A fresh criterion can silently become an unrelated old criterion.**
   - **What this is:** `ai/dimension_matching.py:158` forces every shared key to self-match;
     `services/ranking/identity.py:8` then restores the prior criterion wholesale.
   - **Problem:** Fresh discovery also invents snake-case keys. Two different definitions called
     `community_skills` are therefore forced together even when the matching model explicitly
     returns no match. The probe replaced conflict-resolution skill with the older gardening skill.
   - **Fix:** Distinguish proven carried-forward keys from fresh model labels. Rename a colliding
     fresh key before matching, and reserve forced self-matches for established input identity.
     Preserve frozen wording/scores once a genuine identity match has been established.
   - **If we skip it:** New concepts disappear, and the committee sees old tiers and scores instead
     of the distinct criterion discovery found.
   - **Owner/check/cost:** Discovery/criteria/matching and key adoption; trace cache/tier/audit consumers
     together. Check same label/different meaning/no match, proven kept-key survival, equivalent
     renamed match and cached-score reuse. Replace the overbroad self-match assumption; no schema
     rewrite or automatic history rewrite. Correctly distinct criteria may require fresh scoring.

4. **Public intake can create records and send mail without a source-level limit.**
   - **What this is:** `api/applicant/guest.py:155,201,273` accepts anonymous draft, submission and
     access requests. Existing mail throttling largely follows the recipient address.
   - **Problem:** One synthetic client submitted 12 different addresses and received 12 successes
     and 12 captured confirmations; it also created 12 drafts for one address despite email coalescing.
     There is no equivalent of the public vacancy-signup source limiter on these paths.
   - **Fix:** Reuse `PublicRateLimiter` and the existing trusted ingress-key rule before anonymous
     record creation/mail staging, covering submission checks, drafts, submissions and access requests.
     Keep mailbox coalescing as well; authenticated revision saves must retain their normal behavior.
   - **If we skip it:** A single source can fill the live pool/draft store and consume the shared
     email allowance. Changing recipient addresses bypasses the present mailbox limits.
   - **Owner/check/cost:** Applicant public boundary, `services/auth/rate_limit.py` and the existing
     vacancy ingress-key owner. Check rotating addresses, repeated drafts, forged forwarding headers,
     ordinary retries and authenticated saves. Share the ingress policy rather than copy it. Constant
     in-memory work, no extra network call; use a threshold that accommodates shared household access.

5. **A failed proposal-seeded discovery worker consumes unevaluated proposals.**
   - **What this is:** Only worker 0 receives proposals (`ai/dimension_discovery.py:223`);
     `services/ranking/analysis.py:98` starts the next member view with no pending proposals.
   - **Problem:** If worker 0 fails and a blind worker succeeds, the run can publish successfully.
     The proposal guard sees no proposed axes in the surviving reports and the new view clears the
     original request. The synthetic “Conflict mediation” request vanished in this exact sequence.
   - **Fix:** Do not publish new criteria when the sole proposal-bearing worker fails. Use the
     existing failed-run path to keep the prior board/proposals; retain tolerance for blind-worker
     failures. A deliberate model decision to skip a non-varying proposal remains valid.
   - **If we skip it:** Human input looks consumed even though the model never assessed it.
   - **Owner/check/cost:** Discovery/criteria pipeline, new-analysis creation and proposal UI refresh.
     Check seeded failure with blind success, the reverse order, no proposals and valid deliberate
     omission. Remove the claim that downstream guards recover failed seed input. No automatic paid
     retry; a failed attempt retains known spend and a user may choose another run.

6. **Malformed browser recovery data can block valid server answers.**
   - **What this is:** `frontend/src/applicant/draftStorage.ts:67,217` casts parsed storage to the
     draft type; `useApplicantPersistence.ts:315` loads it before applying server answers.
   - **Problem:** Valid JSON with a current timestamp and `draft: null` throws `TypeError` in
     `loadApplicationDraft`. Nested malformed fields can also escape into rendering; parsing JSON
     successfully is not proof of a usable draft.
   - **Fix:** Treat an invalid individual remembered record as unavailable and continue restoring
     the server copy. Validate the used record's structure and clear only that captured bad record
     under the existing storage lock, preserving another tab's newer copy.
   - **If we skip it:** A returning applicant can be stuck during restoration until site data is
     cleared, despite a healthy saved application on the server.
   - **Owner/check/cost:** Browser draft storage and restore flow. Check null/missing/nested malformed
     data, invalid opening IDs/revision, valid sibling drafts and concurrent replacement, through
     actual restore. Reuse existing storage fencing; no compatibility framework or dependency.
     Local validation only; never delay server recovery on provider work.

7. **Email coalescing rolls back the latest guest collision answers.**
   - **What this is:** `api/applicant/guest.py:123` saves a comparison copy and delegates delivery
     to `services/email/transactional.py:67`. Both pre-review checks and submission collisions use it.
   - **Problem:** `send_magic_link` returns `RECENT` before committing when a prior email is still
     recent or its request quota is reached. The caller also returns/raises without committing the
     new copy, so request-session close rolls it back. With realistic per-request sessions, the
     first response was `sent`, the second `recent`, and stored answers remained the first copy.
   - **Fix:** Make the collision owner explicitly commit the preserved copy independently of whether
     another email is sent. Keep the existing mailbox coalescing and authenticate before any change
     to the applicant's saved working/submitted application.
   - **If we skip it:** Returning through the already-sent link can present older guest answers while
     the applicant believes the latest answers were preserved for comparison.
   - **Owner/check/cost:** Shared collision helper, both HTTP consumers and
     `tests/applicant/test_guest.py:171`. That existing regression shares one Session across requests
     via `tests/applicant/support.py:41`, allowing a later link-open to commit the previous request's
     pending update. Give the regression real request-session lifetimes; test sent, coalesced,
     quota-limited and failed delivery and the 409 submission path. Reuse the existing transaction;
     no extra provider call, duplicated draft store or network wait is needed.

### Should fix

8. **Frontend verification is already red.**
   - **What this is:** Guest-review admission tests and the opening-panel test fixture.
   - **Problem:** Two tests query native date controls as textboxes; lint also rejects a never-used
     `preview` fixture. The concurrency assertions are not reached by the failing tests.
   - **Fix:** Use accessible label queries for the date fields and delete the unused preview/import.
     The temporary copied review suite already passes with label lookup.
   - **If we skip it:** Routine frontend checks remain noisy and those review races lack a working test.
   - **Owner/check/cost:** `ApplicantReviewAdmission.test.tsx:157`, `OpeningsPanel.test.tsx:58`.
     Full frontend suite/lint/build must pass after repair. Delete the obsolete fixture; no runtime
     code, dependency or latency change is needed.

9. **Degraded discovery records zero failed calls.**
   - **What this is:** `ai/dimension_discovery.py:280` tracks `failed_count` separately from `PassCost`;
     criteria persistence, the run ledger and `services/metrics.py` consume the latter.
   - **Problem:** One failed worker plus one successful worker produces a visible degradation
     warning but `discovery_cost.failed_calls == 0`. The normal ledger loses that failure fact.
   - **Fix:** Carry failed worker counts into the existing pass accounting, without guessing token
     usage or billing for responses never returned. Keep successful replies and failed attempts distinct.
   - **If we skip it:** Failure trends and the warning describe different versions of the same run.
   - **Owner/check/cost:** Fan-out result accounting → criteria → ledger → metrics/UI. Test partial
     success, all-fail and all-success and inspect the persisted pass row, not only the warning.
     Consolidate counts in the existing result/cost objects; no provider call or extra hot-path query.

10. **Discovery defines a different score scale from the scorer.**
   - **What this is:** `ai/schemas.py:107,357` defines the low pole as near zero; discovery instructions
     (`ai/dimension_discovery.py:72`) still describe a 0..1 score.
   - **Problem:** Scoring and ranking use −1..+1, with zero reserved for neutral/no evidence. The
     producer of the pole definition and its consumer assign different meanings to the same zero.
     This is a confirmed contract contradiction, not a measured claim of model error frequency.
   - **Fix:** Align both dimension schemas and discovery instructions with the signed scale and
     neutral-zero rule. Keep one clear meaning for the low pole in production and eval inputs.
   - **If we skip it:** The model receives conflicting instructions at the point where criteria
     definitions become scores and committee explanations.
   - **Owner/check/cost:** Shared AI schemas, discovery/decomposition, prompt versions and eval corpus.
     Remove unsigned-scale wording; test prompt/schema consistency, then run bounded real-model
     scoring/stability checks before shipping. Prompt changes rederive versions; no new pass or
     workflow wait, though explicit rediscovery may produce different criteria.

11. **Applicant income bypasses the shared safe number control.**
    - **What this is:** `frontend/src/applicant/ApplicantFormFields.tsx:222` has a separate native
      number input; the established `NumberInput` avoids accidental wheel changes.
    - **Problem:** Income is an eligibility input on a long scrolling form, but this is the one
      production numeric entry still using the widget the project explicitly excludes. Source and
      rendering confirm it is native; its wheel gesture was not tested in a real browser here.
    - **Fix:** Use the existing shared control, preserving blank vs zero and whole-dollar validation.
    - **If we skip it:** The form retains the known risk of silently changing an income while scrolling.
    - **Owner/check/cost:** MoneyField, draft conversion, validation and guest-review tests. Check blank,
      zero, negative/fractional refusal and wheel behavior in Chrome. Delete the parallel widget;
      no dependency or request/latency change.

### Nice to have

12. **The generic case editor cannot create or restore JSON null.**
    - **What this is:** `frontend/src/components/evals/StructuredFields.tsx:9,49` supports nullable
      fixture values but renders null as empty text and offers no null field type.
    - **Problem:** Editing a null value to `2` produces the string `"2"`; clearing it produces `""`.
      The scalar/list/object probe confirmed that ordinary shapes work, but null cannot be restored
      through those controls. Missing, empty text and null can mean different things to a prompt.
    - **Fix:** If editing such a case, provide an explicit null choice through the existing scalar
      controls rather than adding a schema-driven editor. Preserve null on blank display alone.
    - **If we skip it:** Operators must edit the JSON file directly for a null-valued case.
    - **Owner/check/cost:** StructuredFields and case-save contract tests. Exercise null → text/number
      → null, including inside lists, and verify the saved JSON type. No new dependency, provider
      cost or network wait; optional ergonomics, not a production screening blocker.

13. **A published-opening helper has no production caller.**
    - **What this is:** `services/openings/catalog.py:60` duplicates a small published-opening query;
      its only function reference outside its definition is one assertion/import in
      `tests/test_preparing_openings.py`. The loader's same-named local variable is unrelated.
    - **Problem:** It preserves and tests a query contract no route or service uses.
    - **Fix:** Delete the helper and replace that one assertion with the real applicant-visible
      opening projection; preserve the rest of the protection/publication test.
    - **If we skip it:** A small amount of dead production surface remains to maintain.
    - **Owner/check/cost:** Catalog and preparing-opening tests; whole-tree reference search already
      checked imports, tests, scripts and docs. Recheck consumers, then run focused opening tests.
      About 15 production lines can go, with zero runtime/dependency cost.

### Proportionality, rejected rewrites and remaining gaps

Recommended discussion order: **export safety and retention (1–2), criterion identity (3), public
intake abuse (4), then proposal/recovery correctness (5–7)**. Restore green frontend checks (8)
before implementing frontend fixes. Accounting and scale wording (9–10) are bounded follow-ups;
11–13 are small shared-component/tooling cleanup. Implementation is complete; the findings above describe the audited baseline.

Keep the current FastAPI/SQLite/React architecture, the explicit pipeline, shared cached evidence,
short write transactions and human priorities. The audit found no justification at this load for
Postgres, a distributed job system, a new agent orchestrator, a generic provenance framework,
another numeric component, or replacing the nested editor. The 1,151-line ORM model catalog stays
cohesive as the schema map; splitting it merely to meet a line threshold would not fix these bugs.
Do not add a committee-wide budget, automatic paid retries, cross-member ranking comparison or a
new account model. Preserve the run lease, selected-result references, writer guards and synthetic
boundary rather than deleting them as apparent abstraction overhead.

Rejected suspected issues: editor typing does not invalidate captured write ownership
(`useRequestScope.invalidate` affects ordered reads, and the existing acknowledgement test passes);
unknown scores are not treated as neutral by the ranker; failed/contested eval outcomes are retained
and use distinct summary rules; per-applicant shared-result deletion already waits for the last
retained producer/consumer. None is an additional recommendation.

**Audit verdict at discovery:** the core consumer/transaction design was well defended by tests,
but privacy/export and identity gaps required correction before broad cleanup. **Lean:** about 15 production lines and
the unused preview fixture can be deleted; **0 dependencies** need adding or replacing.

**Not checked:** live provider quality/prices/terms, dependency vulnerability advisories, public
website code in the sibling repository, production mail/OAuth/Fly state, real-data load/latency,
full browser accessibility/visual/print/drag behavior, and every migration/script/stylesheet line.
Existing migration/script checks passed; that does not substitute for a production rehearsal.
These are explicit limits, not silent green checks. Only synthetic inputs were used; real local
or production applicant records were not inspected, changed, restored, emailed or exported.


### Implementation and verification closeout

Jeff authorized all findings and local commits, including conservative pool-text deletion, on
November 24, 2026. Existing application/result/cost data was preserved; the additive migration
`b69f7e31d425` adds captured source IDs and the text-purge marker. Local SQLite is verified at that
revision, with 104 applications, 21 analyses, 18,611 AI results and 79 cost runs unchanged by the
schema check/upgrade, and valid foreign keys. Production deployment remains an operator action.

| Finding | Implemented behavior and verification |
| --- | --- |
| 1 | Baseline and both actual harvest paths require captured and current synthetic inputs. Unknown/mixed history is refused; a withdrawal cannot rewrite captured assurance. Regression tests cover stale stamps, inherited unknown history, late arrivals, expired sources and unchanged destination files. |
| 2 | Source-aware purge removes whole affected audits and copied pool explanations, preserves generic criteria/retained applicants/costs, and fences late consolidation text. Normal purge, legacy scope, cross-opening inheritance and SQLite restore are covered, including a restore without the source row. |
| 3 | A fresh colliding key with different frozen meaning receives a distinct key before matching. Proven kept keys and identical frozen definitions retain identity; semantic matching may still adopt an established concept. Production criteria-path regressions cover refusal and kept identity. |
| 4 | One 30-per-15-minute anonymous quota runs before records/mail for all four public intake paths. The shared ingress helper rejects forged forwarding identities. Endpoint tests use rotating mailboxes, shared quota and saturated-quota authenticated saves. |
| 5 | Failure of a worker carrying proposals aborts criteria publication and leaves prior proposals/board intact. Blind-worker degradation remains tolerated. HTTP run tests inspect terminal events, unchanged member state and persisted known spend. |
| 6 | Remembered records are shape-checked before use; malformed copies fall back to server answers. Clearing uses the captured record and existing browser lock. Tests cover nested malformed data, invalid revision/opening IDs, valid siblings and a newer concurrent replacement. |
| 7 | The collision owner commits the latest comparison copy independently of mail delivery. Its existing repeated-collision regression now uses real per-request sessions; submission-collision and delivery-failure paths remain covered. |
| 8 | Date controls use accessible label queries and the unused preview fixture/import is deleted. Frontend suite, lint and build are green. |
| 9 | Degraded discovery carries failed workers into the pass ledger/metrics without invented usage. HTTP regressions verify failed/successful call counts for degraded completion and proposal failure. |
| 10 | Both dimension schemas and discovery instructions define −1..+1 with neutral zero. Discovery/decomposition versions include their static output schemas. Retained scores remain valid; rediscovery stays explicit. Real-provider checks exercise the revised producers and signed-score boundaries. |
| 11 | Applicant income uses the shared NumberInput. Tests preserve blank/zero and reject negative/fractional amounts at review; no native number widget remains in production entry code. |
| 12 | Existing scalar controls offer explicit null/text/number/Boolean choices; new fields and copied null list entries preserve JSON null. A nested case round-trip verifies the saved JSON, not only the displayed control. |
| 13 | The unused published_openings helper is deleted. The preparing-opening test now checks the real applicant projection and preserves its retention/publication checks. |

Automated verification: **1,356 backend tests passed, 1 skipped**, complete Ruff check passed;
**486 frontend tests passed**, frontend lint and production build passed. The watchdog code was
unchanged; its audit baseline had 43 passing tests plus a passing TypeScript check.

Real-provider evidence is preserved in
[the synthetic validation snapshot](ponytail-audit-validation-2026-11-24.json).
The successful direct Terra-low/Haiku run screened three fictional households, completed discovery,
decomposition, scoring and consolidation with **19 criteria, 3 scored applicants and 0 failures**,
and passed deterministic invariant checks. Rank's ledger recorded **$0.2633**; the retained full
probe including Screen recorded **$0.291312** known usage at application prices. No production
model setting was changed.

The direct Sonnet attempt timed out during decomposition at the normal 90-second idle policy;
the earlier shorter probe also timed out. The initial restricted process did not discover AWS
credentials. In the normal Windows user context the default shared-credentials-file profile resolved
and **Bedrock Haiku/Sonnet completed the full run: 24 criteria, 3 scored applicants, 0 failures**,
with **$0.4577** recorded Rank cost and **$0.577205** known probe usage including Screen and scoring
stability checks. Invariants passed. The existing bounded missing-dimension re-asks recovered one
omitted dimension for each applicant without losing returned usage or complete-vector publication.
No credential or production model configuration was changed.

Both Haiku routes measured the same two sensitive goldens over five repetitions per case: absence
confidence passed 4/5 and the modest-evidence band passed 3/5. The other four goldens were stable.
Absence scored zero every time; the high and demonstrated-negative boundaries held 5/5. The scoring
prompt and golden labels were unchanged. These observed sensitivities remain visible; neither labels
nor unrelated instructions were weakened to make a clean sweep. Provider billing without returned
usage is unknown; the evidence notes the first in-memory probe's missing durable usage receipt.

After Jeff restarted the Chrome integration, signed-in local Evals and the applicant form were
reachable. Actual applicant income controls rendered as text inputs with decimal input mode. In a
separate preview tab, the real shared components were exercised using isolated fictional state:
blank/zero/negative/fractional income validity, ArrowUp without changing 80000, number → text → null,
and copying null list entries. At desktop width the editor was 980 px wide; at a 390 px mobile
viewport it was 366 px wide, with controls contained and an 8 px label-row gap. The mobile screenshot
was visually inspected. No applicant answer or fixture was saved by those checks, and the scratch
tab was closed. Physical mouse-wheel, drag, complete application and print journeys remain outside
this verification. No dev server was started and no production deployment performed.

## Follow-up full-codebase audit — November 24, 2026

**Status: all seven findings implemented and verified. Jeff authorized commits and push.**
Baseline: `c19d4b6edd3f65e2c398fe68e920dc45e3184ea5`. Review current behavior across the full
system, including areas unaffected by the previous fixes. Expected load remains one Fly process,
about five committee members, 300 applicants and 1,500 vacancy subscribers. Only isolated synthetic
data may be used in probes; do not mutate the real local database or send mail.

Jeff additionally requested three more passes after the initial set because he switched from Sol
to Astra. Record those separately, without restarting discovery or changing the application baseline.

### Coverage plan

Every row is challenged for correctness, adverse completion order/failure, supported input shapes,
agreement between consumers, unnecessary work and readability. Source review, executed checks,
synthetic probes and explicit gaps must be distinguished at closeout.

| Area | Scenarios and source owners |
| --- | --- |
| Intake and applicant state | Guest/collision/Google/email, incomplete drafts, publication, cross-tab/browser copies, date/number validation; `api/applicant/`, application services/schemas and frontend applicant owners |
| Identity and authority | Session expiry/switches, allowlist/admin boundaries, credential issuance/revocation and captured API identities; auth services/API dependencies and frontend session/client owners |
| Openings and email | Preparation/publication/edit/selection/cancellation, audience and consent generations, delivery retries and uncertain acknowledgements; opening/email services and admin workflows |
| Retention and recovery | Availability before sweep, source inheritance/erasure, selected/legal-hold records, physical purge, SQLite backup/restore and migrations |
| Eligibility and ranking consumers | Same facts through list/detail/dashboard/union/Screen/Rank, override ownership, incomplete scores, criteria/tier/alias history and printed output |
| AI execution and cost | Estimate/confirmation/execution consistency, captured inputs, failure and retry accounting, lease/cancellation and provider boundary; AI and rank/run services |
| Evals and observability | Editor value shapes, case/history identity, attempted vs completed work, stability/Judge summaries, provenance and local/admin fixture boundaries |
| Browser and operations | Navigation, draft/save/read completion order, visible refresh, API retry/deadline/stream handling, deployment/static serving, watchdog and operator scripts |

Initial set: user journeys; data/consumer transformations; adverse sequences; simplification and
closure. Additional requested set: independent trust-boundary challenge; workflow/completion-order
challenge; cold-reader/operational challenge. Continue following any new material issue within scope.

### Audit outcome and evidence

What this repo does: Penta collects housing applications, applies deterministic eligibility rules,
and gives committee members AI evidence and personal rankings. Human administrators own opening
decisions. The review assumes the small production load above, including slow providers and
ordinary requests arriving during background work.

The initial four perspectives jointly produced six verified findings. The three additional passes
requested after the Sol-to-Astra switch produced one more finding (confirmation against changed
criteria), then zero and zero. The final challenge traced each issue through its producer, stored
state and consumers, added negative controls, and found no further unexamined material issue.
This is bounded coverage, not a claim that every line or possible execution was checked.

| Area | Source review and exercised evidence | Remaining limit |
| --- | --- | --- |
| Intake and applicant state | Publication, working copies, browser restoration, lifecycle reads, canonical answer schemas and shared form controls. Synthetic resubmission and actual date-control/validator probes found findings 1 and 7. Applicant suites and frontend persistence/editor tests ran. | No new complete human application or physical input-device journey. |
| Identity and authority | Cookie identity headers, committee allowlist/session revalidation, writer-time admin checks, local fixture gates and account-owned frontend requests/drafts. Auth/authority/session and adverse-order suites ran. Explicit identity mismatch remains refused. | No external Google sign-in or credential attack exercise. |
| Openings and email | Publication audience, consent-generation reservation, direct selection, final decisions, retry preparation/acknowledgement and daily lease. Slow/short virtual-clock batches and withdrawn/active/decided controls found 3 and 6. | No actual email was sent; timeout timing is simulated. |
| Retention and recovery | Retention predicates, history/protection, aggregate/result/pool erasure and local restore ledger/authority reset. Linked-feedback marker survives purge (2); restore/purge/migration suites ran. | No real local DB restore/reset or production snapshot rehearsal. |
| Eligibility and ranking consumers | Shared machine/member/union rules, selected-applicant scope, chosen score rows, ranking arithmetic and list/detail/dashboard projections. Existing parity, partial-vector, query-count, scoring and concurrency tests ran. | No fresh production-sized timing benchmark or print interaction. |
| AI execution and cost | Source capture, criteria worker/publication, estimate/run owners, scoring, measured costs, heartbeat and fenced commit/cleanup. Mock HTTP probes found 4 and 5; known failed spend remains accounted for. | No new paid provider run or prompt-quality claim in this audit. |
| Evals and observability | Local/admin gates, captured dataset/fingerprint identity, attempted-run completeness, contested grading and browser summary/history. Completion-order, grading-parity, fixture-boundary and editor suites ran. | Previous real-model quality sensitivities above remain; no prompt retuning. |
| Browser and operations | Scoped reloads, private-note acknowledgement, API deadlines/body/stream cancellation, static image/config, SQLite pragmas, backup/restore wrappers and watchdog decision/retry owners. Frontend build/lint and watchdog tests/typecheck passed. | No deployment, provider outage injection or third-party advisory scan. |

Automated baseline: Ruff clean; **1,356 backend tests passed, 1 skipped**; frontend production build
and lint passed; **43 watchdog tests passed** and TypeScript passed. The first frontend run had one
failure in the pending-email visibility/permission refresh test; its focused rerun passed all 74
tests and the complete rerun passed all **486**. This intermittent result is recorded, not promoted
to a proven application defect or hidden behind the clean rerun.

Synthetic probes used isolated in-memory databases, mock AI and captured/failing mail senders.
No real applicant answers, credentials, mail or production services were used or changed. A temporary
Vitest check exercised the actual date field and validator under `TZ=Asia/Tokyo`; it was removed
after execution. Scratch scripts are ignored; the reproducible setups and measured outcomes are
recorded below. The application baseline stayed unchanged throughout all seven passes.

### Must fix

1. **Replacement answers inherit a fictional-data stamp.**
   - **What this is:** [`publish_working_copy`](../../backend/app/services/applications/intake.py)
     replaces committee-visible answers; [`capture_rank_sources`](../../backend/app/services/ranking/provenance.py)
     and the [export guard](../../backend/app/evals/synthetic_guard.py) trust `Application.synthetic_data`.
   - **Problem:** Start with a fixture-stamped application, publish replacement answers while runtime
     `application_data_is_synthetic=False`, then capture/export. The application and new Rank remain
     stamped true, and the guard accepts the replacement text. A genuinely false input is refused
     by the same guard, so publication is the missing boundary.
   - **Fix:** Make publication refresh the submitted projection's assurance from trusted runtime
     provenance. Keep private edits separate. Cover both stamp directions, ordinary creation,
     publication and actual evidence exporters in intake/synthetic-guard tests.
   - **If we skip it:** Ordinary personal answers can be exported as supposedly safe fictional evidence.
   - **Owner/cost/deletion:** Shared intake owns the stamp; exporters remain defense in depth. No extra
     request/model call, no new identity or dependency; remove the stale-stamp assumption.

2. **Applicant quotes survive purge inside feedback.**
   - **What this is:** [Feedback](../../backend/app/api/feedback.py) explicitly permits sensitive applicant
     specifics and retains resolved items; [aggregate erasure](../../backend/app/services/applications/purge.py)
     only nulls their applicant reference.
   - **Problem:** Create feedback linked to a reviewable applicant with a fictional quote marker,
     purge the applicant, then list admin feedback: the link is null but the complete marker survives.
     Removing the link also loses the identity needed for a later cleanup.
   - **Fix:** Delete the entire linked feedback item at applicant purge, including local restore
     replay. Jeff explicitly accepted this tradeoff on November 24: preserve general product feedback,
     sacrifice linked debugging history to honor applicant retention. Test resolved/unresolved linked
     items, unrelated feedback and restore replay. Unlinked free text cannot be attributed reliably;
     tell members to avoid applicant details in general feedback rather than inventing text detection.
   - **If we skip it:** The live database retains identifying text after its source's retention ends.
   - **Owner/cost/deletion:** Existing purge owner; replace reference-nulling with deletion. One bounded
     SQL delete, no provider latency, no new retention subsystem.

3. **Slow daily email work can acquire a second owner.**
   - **What this is:** [Maintenance](../../backend/app/services/maintenance.py) leases ten minutes, then drains
     [the outbox](../../backend/app/services/email/outbox.py) sequentially without renewal or ownership checks.
   - **Problem:** A virtual-clock probe queues 100 fictional notices; each retryable send takes ten
     seconds. Another ordinary request after minute ten reclaims maintenance while its predecessor
     continues: 200 attempts, two maintenance acquisitions, all 100 intents retried on the same day.
     At one second per send, the identical control makes 100 attempts and the second acquisition loses.
     Existing completion fencing protects the final status, not the ongoing work.
   - **Fix:** Renew the existing acquisition during work and stop dispatching when that acquisition
     is replaced. Keep per-delivery claim/acknowledgement fencing. Test long batches, ownership loss,
     failure and both old/replacement completion orders with virtual time.
   - **If we skip it:** A provider slowdown can amplify retries and defeat the promised daily cadence.
     The probe proves duplicate attempts, not that recipients necessarily receive duplicate mail.
   - **Owner/cost/deletion:** Maintenance owns daily acquisition; the existing outbox loop supplies
     progress checks. Short DB renewal writes; no lock across provider waits, new queue or scheduler.

4. **Rank spends before rejecting already-expired inherited sources.**
   - **What this is:** [Provenance](../../backend/app/services/ranking/provenance.py) unions historical source
     IDs, and [analysis creation](../../backend/app/services/ranking/analysis.py) validates retention only
     after discovery, decomposition and matching.
   - **Problem:** Use a valid current pool and one older analysis whose captured source is already
     expired but not swept. HTTP Rank makes seven mocked provider calls, then fails at criteria
     persistence and creates no analysis. The ledger correctly records $0.03675 of simulated usage
     at application prices. Such rows are possible between expiry/protection release and maintenance.
   - **Fix:** Validate captured historical sources before paid work; fail with actionable recovery or
     run the existing safe cleanup before proceeding. Preserve the late writer-time check for expiry
     during work. Test pre-existing expiry (cleanup before provider inputs, or zero calls on refusal)
     and mid-run expiry (no prose publish).
   - **If we skip it:** Retrying the known-invalid inputs repeats paid work that cannot be published.
   - **Owner/cost/deletion:** Rank/provenance owns preflight, analysis owns final fencing. One bounded
     retention query before calls; consolidate the predicate, do not add another source registry.

5. **Score-current confirmation can execute different criteria.**
   - **What this is:** [The estimate and action](../../backend/app/api/ranking/score_current.py) independently
     choose the newest analysis. [The browser action](../../frontend/src/hooks/useAiRuns.ts) sends only an
     opening; its confirmation does not carry the displayed analysis identity.
   - **Problem:** Estimate an analysis with two criteria, publish a newer one with one criterion as
     another member, then confirm the original action. The endpoint makes a model call and reports
     one executed criterion. The estimate has no `analysisId`; the stale-board toast is not a gate.
   - **Fix:** Carry the existing analysis identity through the estimate, confirmation and action;
     refuse a changed identity before model work and refresh the confirmation. Include UI stale-state
     behavior and both analysis-change/confirmation orders. Ordinary token-cost variability remains
     an estimate, not a new exact-cost approval protocol.
   - **If we skip it:** A member approves one set of criteria and pays to apply another.
   - **Owner/cost/deletion:** Score-current API/types/client and `useAiRuns`/confirmation own this.
     Reuse `analysisId`; no new identifier, polling or additional successful-path round trip.

6. **All withdrawals hide an overdue decision while retention stays unbounded.**
   - **What this is:** [The overdue selector](../../backend/app/services/openings/selection.py) requires an
     active participant; [retention](../../backend/app/services/applications/retention.py) waits for decisions
     on all durable participations, including withdrawals.
   - **Problem:** A published, undecided opening is past move-in and its last submitted participant
     withdraws. The probe shows no retention deadline and zero overdue actions. Restoring the active
     participation produces one action; recording a decision produces a deadline and no overdue action.
   - **Fix:** Base the reminder on the outstanding published opening decision, including withdrawn
     participation history. Keep an explicit human no-household decision and the existing retention
     anchor. Test all-withdrawn, active, empty, decided and future openings through dashboard/admin consumers.
   - **If we skip it:** Forgotten decisions can leave withdrawn applicants' retained records without
     a deadline or the promised reminder. Manual admin opening management remains available.
   - **Owner/cost/deletion:** Existing opening selection/dashboard projection; remove the active-only
     reminder gate. No new table, background task or date change.

### Should fix

7. **Client and server disagree about today's allowed dates.**
   - **What this is:** [`localDateToday`](../../frontend/src/components/shared/DateInput.tsx) supplies the
     field maximum and [review validation](../../frontend/src/applicant/ApplicantFormFields.tsx); canonical
     [answer validation](../../backend/app/schemas/applicant/answers.py) uses Penta's Pacific date.
   - **Problem:** At `2026-11-25T02:00:00Z`, a Tokyo browser accepts an employment start of November 25
     through the actual field and validator. Pacific is still November 24; the actual server schema
     rejects the same value as future. Review passes, then saving/submission fails.
   - **Fix:** Use the existing Pacific calendar policy consistently in shared date limits and form
     validation. Cover both sides of Pacific midnight, another browser zone and unrestricted dates;
     keep date-only values unchanged.
   - **If we skip it:** Applicants outside Penta's time zone receive contradictory form instructions.
   - **Owner/cost/deletion:** Shared frontend date helper and consumers; reuse the existing timezone
     formatting pattern. Delete browser-local validation arithmetic; no network request or dependency.

**Verdict:** Address the two evidence-retention gaps first, then acquisition ownership and paid-work
preflight/confirmation. The existing layers can own all seven remedies.

Rejected expansions: no new job system, source-ID registry, generalized approval fingerprint,
database replacement, dependency, speculative cache or wholesale module split. The source review
and existing query-count tests do not establish a new performance bottleneck at the expected load.
Do not reopen the approved generic-criterion retention policy or retune unrelated goldens to hide
the previously measured model variability. No additional smaller style findings were withheld.

**Not checked:** Production deployment/snapshots, live Google/email flows, fresh paid-model judgment,
physical drag/wheel/print journeys, third-party vulnerability advisories and a production-scale load
test. One intermittent frontend test remains an explicit verification limit.

### Implementation and closeout

Jeff approved all seven remedies and explicitly accepted deletion of the entire applicant-linked
feedback item. Implementation began only after the seven discovery passes finished on `c19d4b6`.
No new dependency, migration, identifier, scheduler or database replacement was required.

| Finding | Final behavior and regression evidence |
| --- | --- |
| 1 | Publication stamps the replacement submitted answers from the explicit runtime assurance; private saves preserve the submitted stamp. All four old/new assurance combinations exercise creation, private save, publication and the actual fixture exporter. Ordinary replacement answers are refused. |
| 2 | Aggregate erasure deletes linked feedback rather than orphaning its body. Resolved/unresolved linked items, general feedback and another applicant's items are distinguished. A real isolated SQLite backup/restore replay removes the expired quoted feedback and preserves general feedback. Submission serializes with purge and rejects unavailable applicant targets, covering both save/purge orders and expired/withdrawn/missing inputs; the actual composer retains its unsent draft after rejection. The composer reminds members to omit applicant details from general feedback. |
| 3 | The same daily acquisition renews before each email attempt and between stages, and a lost acquisition stops dispatch. Both 100-item virtual batches (one- and ten-second sends) make exactly 100 attempts with one daily owner. Replacement during an accepted or failed send stops the old worker before its second dispatch; existing obsolete-completion tests stay green. |
| 4 | Rank preflight shares the retention predicate with final publication. Expired known sources go through normal purge before discovery; the expired marker never reaches a prompt. An unresolved missing source returns 409 without calls and releases the lease. Expiry during paid work still prevents analysis publication. |
| 5 | Estimate/types/client/confirmation/action carry the existing `analysisId`. Both client-known drift and drift while claiming the server lease are refused; the board refreshes and no success is announced. Estimates take a short writer snapshot and refuse a live full Rank, covering in-place consolidation without another version token. The required ID is enforced; successful score-current, cache, failure-cost and lease-loss consumers remain covered. |
| 6 | Every overdue published undecided opening remains an admin action, including empty/all-withdrawn histories. Future, Preparing and decided openings do not. Dashboard and one-query summary tests cover the projection; human decisions and retention anchors are unchanged. |
| 7 | Shared form date maxima and validation use the existing Vancouver/Pacific timezone policy. Actual fields are checked on both sides of winter and summer Pacific midnight, including a separate Tokyo-process run; unrestricted dates retain their behavior. Date-only answers are not shifted. |

Final checks: **1,377 backend tests passed, 1 skipped**, Ruff clean; **494 frontend tests passed**,
frontend lint and production build passed. The six date-field checks also passed with
`TZ=Asia/Tokyo`. Watchdog code is unchanged; its 43-test/typecheck audit baseline remains applicable.
The previously intermittent visibility-refresh test passed in the final full suite; its initial
failure is retained in the audit evidence above.

A fresh [live Bedrock smoke receipt](followup-audit-live-score-2026-11-24.json) records
one fictional applicant from the committed intake fixture scored against one committed golden
criterion through the estimate and score-current HTTP endpoints: **1 scored, 0 failed**. The
Haiku result scored explicit lack of licensed-trade experience at −1 with high confidence and quoted
the fictional applicant's statement that neither adult is a tradesperson; the stated low pole
supports this result. A superseded confirmation then returned 409 without another model call.
Known provider usage was **$0.003557** (display/ledger rounding: $0.0036). This verifies the revised
path and one inspected output, not a new model-quality benchmark or a change to golden labels.

Operational cost: maintenance adds short renewal writes between sends; score-current estimation
holds a short SQLite writer transaction while reading its plan, never across network/model work.
Rank adds a retained-source query and invokes existing cleanup only when necessary. No additional
successful-path browser round trip was added. Linked feedback takes a short application writer
lock before checking context and storing the body. The real local DB, credentials and provider settings
were untouched. Production deployment, live mail/Google flows and full browser/print journeys
remain outside this implementation verification.
