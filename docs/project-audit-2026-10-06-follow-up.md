# Whole-project audit — 2026-10-06, post-implementation review

**Status: complete through four independent domain reviews and a reconciliation/challenge pass;
X01–X16 recommended, not implemented.** Original baseline `83bfd9e`; the independent reviews
started from clean `bc8e3ff`, twelve local commits ahead of the recorded `origin/main`.
Application code is unchanged between these audit revisions. The completed W01–W07
report remains at `83bfd9e:docs/project-audit-2026-10-06-follow-up.md`.

## Recommendation

Prioritize the access-link identity defect (X07), cross-opening priority loss (X08), and
retention/submission failures (X09–X12). The independent reviews below add ten findings to
the original six; they are one combined implementation backlog, not separate implementation rounds.
Then fix the dashboard loading race, the two fixture-contract gaps, and the disruptive trace refresh.
Repair the two command-line experiment wrappers before relying on their next model comparison.
These are bounded changes to existing owners. I do not recommend another architecture rewrite,
a general mutation framework, or additional production caching.

| ID | Priority | Finding | Evidence |
| --- | --- | --- | --- |
| X07 | P1, access control | Regeneration revives superseded access and cancelled email-change links | Actual anonymous regeneration/redemption restores access to a synthetic current profile |
| X08 | P1, ranking integrity | Global criterion aliases erase another opening's effective priorities | Another opening's report retains `newer`, but reconciliation changes its positive tier to `older`; weight becomes zero |
| X09 | P2, retention | Withdrawn participation misses the final-decision retention update | Four withdrawal/decision combinations remain without deadlines and survive an overdue purge |
| X10 | P2, draft loss/retention | Private draft deadlines are stale or absent after saves/claims | Switching to a later opening leaves early expiry; empty-selection claim creates a nonexpiring Application |
| X11 | P2, intake | Hidden archived openings demand address history the form removes | Form accepts August 2024 move-in; actual submit rejects it against hidden April 2024 cutoff |
| X12 | P2, submission | Duplicate submit can replace success with a stale-copy error | Real review permits repeated clicks; real hook moves `submitted` → `stale_copy` on late 409 |
| X13 | P2, ranking coverage | Consolidation revives criteria without complete current scores | Run reports 4 scored/0 failed; final board and dashboard have only 3/4 coverage |
| X14 | P2, operator writes | Subscription controls permit overlapping writes and obsolete acknowledgements | Same-normalized-address edit allows delete; earlier save then restores deleted subscription in UI |
| X15 | P2, navigation | Feedback applicant links use the currently selected opening | Feedback for A invokes detail read for B, failing or displaying B's eligibility context |
| X16 | P3, report clarity | Cost tables compare provider replies with cached result counts | Three fresh dimensions plus one cached displays uncached 1/cached 1, while cache-hit metric correctly says 25% |
| X05 | P2 | A failed background dashboard refresh can strand initial loading | Both requests settle, but the real hook remains `loading`; reversing their completion order settles correctly |
| X01 | P2 | Fixture family metadata can disagree with its owning file/endpoint | Save returns 200; Judge lists the wrong family; its Run request returns 404 and current fingerprints use a different identity |
| X02 | P2, eval validity | Screening expectations admit unknown categories and inconsistent raw types | Misspelled forbidden flags weaken assertions; a string pet count validates but fails against the identical numeric count |
| X06 | P3 | Passive trace refresh discards expanded operator content | An open discovery trace disappears during refresh and returns collapsed, even with identical data |
| X03 | P2, operator tooling | Golden model bake-off retains invalid outcome rules and reloads inputs per model | Invalid contested output passes; all-error repeats report stable; later errors erase known usage; control/challenger can see different inputs |
| X04 | P2, operator tooling | Full-rank copy experiment does not reliably capture its advertised inputs | Copied DB omits a committed WAL row; two visible openings fail before running; requested high reasoning leaves copied pass settings low |

Preserve submission-time age, automatic cache reuse, committee judgment and unranked behavior,
coverage-based workflow readiness, retained imported records, admin-only operator views,
local fixture editing, and uncapped evals. The deferred export/source-guard policy remains
deferred; X04 does not reopen it. This audit authorizes no application changes or push.

## Coverage and method

The table began with pending entries. Evidence is now recorded by subsystem and perspective.
**S** means source/caller review, **T** means existing tests executed in this audit, **P** means
a new controlled probe. These labels describe the evidence, not a claim of exhaustive proof.

| Subsystem | Correctness / consumers | Failure / concurrency | Shapes / lifecycle | Simplicity / cost |
| --- | --- | --- | --- | --- |
| Applicant form/persistence | S/T: canonical vs working answers, acknowledgements | S/T: browser revisions, changed session, pending copy, email/withdrawal flows | S/T: native/imported answers, residences, optional household members | S: retain cohesive save/email/withdrawal owners |
| Identity/admin authority | S/T: cookie/displayed identity and role boundaries | S/T: demotion, revocation, first identity claims | S/T: applicant/committee credentials, public limiter boundaries | S: admission and writer checks protect different moments |
| Committee actions/navigation | S/T: narrow receipts, author-only notes, saved views | S/T: creation replay, uncertain saves, overlapping detail/navigation | S/T: retained review, blocked drafts, opening changes | S: keep existing field queues and navigation ownership |
| Opening publication/decisions | S/T: phase, audience and finality | S/T: stale opening edits, selection/withdrawal, uncertain outcomes | S/T: direct/ordinary, withdrawn/expired/unsubmitted households | S: W06 projections retained; no new query cache justified |
| Screen/Rank/cache | S/T: frozen inputs, member/shared pools, provenance and weights | S/T: lease replacement, HTTP cancellation, partial calls | S/T: missing score vectors, reused identities, no priorities | S: existing bounded lookup/projection helpers serve real consumers |
| Eval grading/history/editor | S/T/P: X01/X02; W01–W04 boundaries retained | S/T: receipt ordering and failed refreshes | S/P: malformed-but-accepted family/category values | S: share validation rules; do not duplicate family or category registries |
| Settings/operator views | S/T/P: X05/X06, settings save receipts | P: both initial/background completion orders; same-analysis refresh | S/T: empty/failed loads, changed analysis, typed editors | S: preserve mounted trace content without changing all resource semantics |
| Email/maintenance | S/T: audience, recipient intent, queue summaries | S/T: attempts, cancellation, consent lifetime, daily lease | S/T: obsolete notices, targetless recipients, expiry | S: W07 narrow reads retained; no new optimization justified |
| Retention/recovery/tooling | S/T/P: aggregate entitlement, snapshots, X03/X04 reports | S/T/P: renewed retention, failed restore, live WAL source | S/T/P: old/new IDs, model settings, multiple openings | S: audit CLI entrypoints under `app/` as well as `scripts/`; keep SQLite copy and pipeline rules in existing owners |

Passes: inventory and entrypoints; user journeys; producer/consumer data meaning; failure and
completion-order probes; simplification and final challenge. The CLI inventory used actual
`main`/`__main__` entrypoints across both application modules and scripts, not directory names
alone. The prior general audit had not exercised the two model experiment wrappers end to end.

## X01 — Make fixture family identity authoritative

**Anchors:** `backend/app/evals/case_store.py:34,54`,
`backend/app/evals/case_schema.py:131`, `frontend/src/components/evals/EvalCaseEditor.tsx:85`,
`backend/app/api/evals/cases.py:_case_response`, `backend/app/evals/judge.py:load_cases`.

A temporary copy of a valid matching case was given a unique key and
`metadata.pass = "consolidation"`, then saved through `PUT /evals/cases/matching`.
The response was 200. Judge's case list preserved the conflicting metadata because its reader
uses `setdefault`; its UI therefore identifies the case as consolidation. The actual Judge
loader and history derive family from the matching file. Running the case using the displayed
family returned 404 without a model call; current fingerprints used `["matching", key]`.

This is reachable through the new-case editor: unlike existing cases, new cases allow editing
`metadata.pass`. It also affects hand-edited fixtures. The endpoint already knows the owning
family, so this is two representations of one fact that can disagree.

**Recommendation:** the endpoint/file family is authoritative. Reject conflicting family
metadata on writes, derive Judge response identities from the owning family, and keep the
family field fixed while adding a case. Reuse the existing family/key identity; do not add
another ID or routing registry. Avoid a broad corpus rewrite merely to fix this boundary.

**Acceptance:** valid ordinary and Judge edits, conflicting/unknown family, new-case editor,
same key in different families, non-ASCII keys, list/run/history identity agreement, and rejection
before fixture mutation or provider invocation. Existing valid fingerprints need not change.
**Latency:** validation/response projection only; no additional request or model work.

## X02 — Validate screening expectation meaning and raw types consistently

**Anchors:** `backend/app/evals/case_schema.py:_ScreeningExpected`,
`backend/app/evals/screening.py:_normalize_fires`, `_case_from_expected`, `_check`.

A synthetic screening case with `expected.absent = ["fake_contcat"]` saved through the API
with status 200. A mock report containing `fake_contact` passed the real live grader. Correcting
the expectation to `fake_contact` made the identical output fail. The unknown name is never
produced by `FlagCategory`; it is an ineffective guard, yet it also prevents the case from being
treated as a clean-applicant check. Unknown required flags create impossible assertions instead.

The current committed corpus contains no unknown flag names; this is a hole in accepted edits,
not a claim that existing fixture results all need to be discarded.

**Additional pre-implementation probe:** `expected.pets.dogs = "2"` passes `validate_case`
because the nested AI `PetFacts` model coerces the string for validation. The stored raw
expectation is not rewritten, however, and the live grader compares that string with the
model's integer `2`. It reports `expected 2 dogs, extracted 2` as a failure. Integer `2`
passes against the same output. Boolean pet counts are also accepted by that nested model.
The parent fixture model's strict setting does not make this separate nested model strict.

**Recommendation:** normalize the supported string/list/pipe any-of forms with one shared rule,
then validate every leaf category against the existing `FlagCategory` vocabulary. Reject empty
names/groups and unknown forbidden/required flags before writing or running a case. Keep the
existing raw fixture/editor contract where possible; do not invent a second category list or
silently drop misspelled assertions.

For pet expectations, validate the raw types the grader actually consumes. Prefer a small,
strict expectation shape with nonnegative integer counts and string-list other pets over
reusing the more permissive AI-output shape. Do not validate a coerced copy and then grade
uncoerced input. Keep supported valid numeric fixtures intact; no new field-editor framework
or broad corpus migration is warranted.

**Acceptance:** all supported any-of representations, whitespace, empty values/groups,
unknown required and forbidden names, correct pet-only/clean cases, and identical live/Judge
meaning. Include string/boolean/null/negative pet counts and valid integer controls through
both validation and grading. An invalid save must leave the file unchanged.
**Latency:** local validation only.

## X03 — Bring the golden model-comparison CLI under the corrected outcome contract

**Anchors:** `backend/app/evals/model_bakeoff.py:192–295`, shared live eval results,
`backend/tests/test_model_bakeoff.py`.

Three controlled observations through the actual wrapper:

- The consolidation runner returns a missing verdict with an explicit error. For a contested
  case, `_run_one` still reports `passed=True` and outcome `?` because it uses
  `result.passed or contested`, ignoring validity.
- Three provider timeouts produce error rows, but `_summarize_cases` reports
  `grade_stable=True`, `outcome_stable=True`, and `majority_agreement=1.0`.
- A mock provider returns 100 input/20 output tokens, followed by a synthetic grader exception.
  The wrapper records one call but zero tokens and zero known cost, discarding its own meter.

**Additional pre-implementation probe:** the actual `run_bakeoff` job builder calls
`spec.load()` inside its per-model loop. A controlled changing loader supplied input version
1 to the control and version 2 to the challenger, under the same case key in one report.
The probe models a local fixture edit between the two reads; it made no real model call or
fixture edit. The advertised frozen comparison should capture each family's cases once and
reuse that snapshot for all models and repetitions.

This is a remaining consumer gap in W01: the shared API stability collector is corrected,
but this CLI has a separate repetition/summary path. Existing bake-off tests build report rows
directly or check configuration dictionaries; they did not run these failure cases through
the wrapper. The problem does not affect normal committee Screen/Rank reporting.

**Recommendation:** apply the existing validity distinction before contested handling, mark
incomplete repeated measurements explicitly, and retain known returned usage even when later
grading fails. Reuse the shared result/completeness rules where they actually match; keep the
CLI's model-comparison grouping. Remove duplicated success/error accounting rather than build
a second evaluator. Missing scoring output should have the same explicit validity meaning as
missing categorical output; do not infer validity from display strings such as `?` or `None`.
Do not estimate unknown provider charges or retry paid calls automatically.
Load each family's cases once before constructing its control/challenger jobs; all repetitions
must reuse those captured inputs. This removes duplicate reads rather than adding a cache.

**Acceptance:** actual runner → wrapper → summary tests for valid contested divergence, invalid
output, missing score, one/some/all failed repeats, and returned usage followed by failure.
Include a changing-source loader and assert a single family read with identical captured
inputs for both models and all repetitions.
A complete consistently wrong answer can still be stable; operational failure cannot establish
measurement completeness. **Latency:** report bookkeeping and fewer fixture reads. Repair before the next CLI
model-selection experiment.

## X04 — Make the full-rank copy experiment capture a coherent, scoped configuration

**Anchors:** `backend/app/evals/model_rank_bakeoff.py:97–156`,
`backend/app/ai/strands_provider.py:_model_for` (explicit effort precedence),
`backend/app/api/ranking/run.py:rank_run`, documented invocation in ADR 0013.

The wrapper's advertised isolated experiment has three reproduced gaps:

1. **Snapshot:** with a temporary source connection held open in WAL mode, a committed marker
   row remained in the WAL. The wrapper's `shutil.copy2` destination contained zero marker
   rows while the source contained one. Only the main file was copied. An uncheckpointed
   schema/data change can likewise leave the experiment with stale or unusable inputs.
2. **Opening:** a synthetic source with two visible openings reaches the real Rank endpoint
   with no opening ID and fails with `opening_required`. The CLI has no opening argument.
3. **Reasoning:** requesting `high` builds a provider fallback map containing `high`, but the
   copied settings still contain `low` for scoring. Production calls pass their settings'
   effort explicitly, which takes precedence over that fallback. The requested report
   configuration can therefore differ from what the pass exercises.

The WAL/reasoning probe stopped at a stubbed Rank entrypoint before any model work. The
multi-opening probe used the real endpoint's preflight with an inert provider. No real DB,
credentials, model, or production service was exercised.

**Recommendation:** take a SQLite-consistent snapshot into a fresh, isolated destination;
thread an explicit opening through the command, Rank invocation, analysis and report reads;
apply chosen models and effective reasoning to the copied pass settings and derive reported
configuration from those accepted settings. Keep using the production Rank pipeline. Dispose
copy-engine resources in `finally`. Do not add an independent ranking implementation.

During that change, stop using an unqualified latest analysis as evidence of this attempt:
when a stream fails before producing an analysis, an older/global analysis must not masquerade
as fresh experiment output. That is a source-reviewed follow-through requirement, not an
additional reproduced production incident.

**Acceptance:** committed WAL data/schema while source remains open; source hash/content
unchanged; distinct/fresh destination; two openings; reasoning override reaching the actual
provider call; report configuration matching persisted pass settings; success/failure cleanup;
failed run not attaching another opening's old fixture. Keep the deferred export/source-guard
policy out of this repair. **Latency:** snapshot work is confined to the explicitly requested
CLI experiment; no committee UI latency change.

## X05 — The request that replaces initial loading must settle it

**Anchors:** `frontend/src/hooks/useDashboard.ts:41–62`,
`frontend/src/CommitteeWorkspace.tsx` focus/visibility/60-second intake refresh,
`frontend/src/components/workflow/WorkflowBar.tsx` loading/error rendering.

A real-hook probe starts `loadInitial`, then starts a newer `refresh`. The refresh fails;
the older initial read subsequently returns a valid payload. Because the refresh superseded
its request scope, the valid initial response is ignored. But the refresh failure is swallowed,
so after both promises settle `loadState` is still `loading`. Reversing the order leaves the
state correctly `ready`.

The workflow bar consequently keeps showing “Loading workflow…” without its error Retry control
until a later refresh succeeds. Focus/visibility refresh and cache-adoption refresh are real
independent callers, so this does not require manually calling an unreachable function.

**Recommendation:** give every winning dashboard request responsibility for settling initial
loading, while retaining already-loaded data on ordinary background failures. Alternatively,
avoid superseding an unfinished initial load with redundant background work. Prefer the narrow
state-ownership correction using the existing scope and load state; no global loader or new
request identity is needed. Keep unrelated list/board reads parallel.

**Acceptance:** both completion orders; initial success/failure versus background success/failure;
opening change; existing loaded data retained on background failure; truthful Loading/Retry/ready
UI; successful retry. The applications hook already suppresses background replacement during
initial selection, and `useFetchResource` settles its own winning failures. A ranking refresh
with an existing board does not show the initial-loading placeholder, so that superficially
similar code is not evidence of the same user-facing failure. **Latency:** no extra requests
or normal-case blocking dependency.

## X06 — Refresh a trace without unmounting the content being read

**Anchors:** `frontend/src/components/ai/AIWorkspaceView.tsx:65–67,149–156`,
`components/observability/DiscoveryPanel.tsx:19`, sibling trace panels and `useFetchResource`.

The accepted dashboard observation changes the mounted trace's refresh key. Every trace panel
returns a Loading placeholder during that read. A real-component probe opened a discovery
`details` section, changed only the observation for the same opening/analysis, and delayed the
read. The entire details subtree disappeared. When the identical payload returned, it was
collapsed. The normal focus/periodic refresh therefore interrupts reading even when nothing
changed; transient errors also replace the content with an error screen.

**Recommendation:** distinguish initial/changed-analysis loading from background refresh of
an already displayed trace. Keep same-analysis content mounted during refresh and expose a
retryable background error without throwing away the reading state. Use the existing opening
and analysis identity to remount/reset on a real scope change; do not add another persistent
version or cache. Keep the four trace panels consistent, but do not change every resource hook's
loading semantics to fix this one surface.

**Acceptance:** expanded content survives same-analysis delayed, successful-identical, and failed
refreshes; changed data appears; switching opening/analysis never displays the prior scope as
new; initial loading/error/retry still work; refreshed trace correctness from the earlier audit
is retained. **Latency:** no additional reads; less visible interruption and DOM reconstruction.

## Evidence, rejected changes, and remaining limits

Fresh verification at `83bfd9e`:

- **1,111 backend tests passed; one existing POSIX-only test skipped on Windows.**
- **368 frontend tests passed across 50 files.**
- Six temporary backend probe cases reproduced X01–X04 using copied synthetic fixtures,
  in-memory/temporary SQLite databases, and mocked providers. Two dashboard completion-order
  probes and one real trace-component probe reproduced X05/X06. All temporary test files were
  removed; their defective-behavior assertions are evidence, not regression tests for fixes.
- Corpus inspection found no unknown current screening flag names. X02 protects future edits.
- Application source, fixtures, migrations, and permanent tests are unchanged. No production,
  real-provider/email call, local database mutation/reset, dev-server start or browser reload
  occurred. The running local app was not used for destructive/action probes.

Coverage anchors beyond the findings include `applicantSaveFlow`, `applicantEmailFlow`,
`applicantWithdrawalFlow`, `draftStorage`, canonical answer models, application access and
participation, session-cookie identity checks, authority and limiter owners, candidate actions
and navigation, opening publication/finality, ranking provenance/cache/lease/cost code, email
retry and consent ownership, retention/backup code, and documented CLI entrypoints. Their
corresponding existing suites ran in the full baseline. New probes were concentrated where
source review established a concrete unsupported sequence or inconsistent contract.

I would **not**:

- Replace the persistence hooks with a state-machine library or general mutation framework.
- Merge lifecycle/write guards merely because their code looks similar, or alter production
  fan-out survivor policy to resemble eval stability.
- Add broad caches, background synchronization, more IDs, or a second settings registry.
- Split model/schema files purely for line count or perform a general comment/style rewrite.
- Remove retained imported-answer support or reopen the explicitly deferred export policy.
- Treat current green tests as evidence that untested CLI paths or malformed-but-accepted inputs
  are correct. Likewise, do not delete meaningful race tests just to reduce test counts.

No additional worthwhile read optimization was confirmed beyond the recently implemented ones.
Existing feedback/name projections, cached-result lookups, opening and email summaries already
have bounded ownership or read paths. Potential large-history tuning should follow measurement,
not a speculative cache layer.

This is repository-grounded source and synthetic-behavior coverage, not a claim of line-by-line
formal verification, production load testing, real-model judgment validation, or a new mobile/
accessibility certification. Recovery was covered by isolated tests, not a production restore.

## Final challenge and implementation sequence

The closing challenge followed each finding into its sibling consumers and considered the
smallest durable remedy. X01/X02 must align save, load, editor, and Judge identities/expectations;
X03/X04 must exercise the real operator wrapper rather than only its dictionaries; X05/X06 must
preserve both failure recovery and existing read-scope protections. No proposed remedy requires
new production infrastructure. After those expansions, no further material candidate remains
unexamined in the planned scope.

Suggested packages: X05 dashboard recovery; X01/X02 fixture contracts; X06 trace refresh;
X03 golden-comparison reporting; X04 scoped SQLite experiment copy. Implement the first three
packages for routine use. Complete the CLI repairs before using those tools for model choices;
they are not prerequisites for ordinary applicant or committee use.

The process improvement from this pass is concrete: inventory **actual entrypoints wherever
they live**, including `app/evals/*_bakeoff.py`, and run a shared-rule probe through every
entrypoint that presents that rule. The prior tooling tests covered three analysis scripts but
only configuration/helper behavior for these model wrappers. The existing audit rule already
requires consumer coverage; this report supplies the missing consumer list rather than adding
another general framework or promising zero future misses.

## Pre-implementation challenge pass

Requested after `f1e125b`; application code is unchanged from the audit baseline. This pass
challenged the proposed changes and nearby consumers rather than repeating the entire inventory.
It confirmed two additional manifestations within X02/X03 and added them above. No new
independent work package or broad refactor is recommended.

| Plan item | Challenge and outcome |
| --- | --- |
| X01 | Confirmed that new-case identity protection, write validation, and file-derived Judge identity must agree; fixing only the editor would leave manual fixture edits/API callers inconsistent. |
| X02 | Checked raw versus validated expectation shapes. Nested pet-count coercion reproduces a contradictory failure; the plan now requires strict raw expectation types as well as valid flag names. |
| X03 | Followed job construction before the existing outcome/summary checks. The actual job builder reloads the family per model; capture once for a fair frozen-input comparison. |
| X04 | Reviewed the proposed SQLite snapshot, explicit opening, effective settings, and attempt/report ownership together. Keep this a wrapper over the production pipeline; avoid a second pipeline or a new experiment store. |
| X05 | Reviewed both loader entrypoints and existing scope protections. The fix must settle the winning initial load while still allowing later background recovery; do not suppress every refresh whenever the state is not ready. |
| X06 | Reviewed resource state and all four trace callers. Keep content only for the same opening/analysis; reset on a genuine identity change. Changing the generic resource hook globally would affect unrelated editors and is unnecessary. |

**New evidence:** 55 existing backend tests plus two temporary counterexample tests passed
(57 total), and 44 existing frontend loader/ranking/operator tests passed. The new backend
tests exercised validation → real screening grading and the actual bake-off job builder with
a controlled changing source. They made no real model/provider call. The temporary file was
removed. The previous full-suite results remain the baseline; they were not rerun or presented
as new results during this focused pass.

The last challenge was whether either addition needs another abstraction: neither does.
X02 can use a strict expectation boundary; X03 can move an existing read outside its model
loop. The six-item implementation plan now includes these cases. Application code, fixtures,
and permanent tests remain unchanged; no further material candidate was identified in this pass.

## Independent discovery passes — 2026-10-06

This extension deliberately did not begin from X01–X06. Three subagents independently
reviewed lifecycle/security, ranking/accounting, and committee/admin UI; the coordinating
review examined applicant journeys. Each started from source and user-visible invariants.
The findings were compared with the existing audit only during consolidation. No application
implementation was performed. The earlier closing statements describe their respective passes,
not a claim that later independent review could not uncover more issues.

### Coverage and challenge results

| Independent pass | Journey / invariant | Adverse sequence or transformation | Evidence / closure |
| --- | --- | --- | --- |
| Lifecycle and authority | A credential proves the currently authorized identity | Change email or cancel a proposal, then regenerate the old token anonymously | X07, actual ASGI routes with captured mail; independently repeated by coordinating reviewer |
| Lifecycle and retention | Every retained record has the correct lifecycle deadline | Withdraw before final decision; choose a later opening; claim a draft with no selection | X09/X10, isolated DB/API probes plus existing retention suites |
| Applicant form | Form validation and submitted-answer validation agree | Retained archived participation plus a new opening and intervening address move | X11, real submit route and frontend canonical-answer helper |
| Applicant persistence | A confirmed submit remains confirmed | Two submissions at revision 1; first succeeds, second returns 409 later | X12, actual review component and persistence hook |
| Ranking identity | A committee member's priorities remain attached to the report being viewed | Opening A creates a global alias while B still uses the old report keys | X08, existing/new member paths source-reviewed; existing-member counterexample reproduced |
| Ranking completion | Successful scoring retains complete coverage after all transformations | Consolidation selects an older survivor missing one current applicant's score | X13, actual ranking endpoint, board, dashboard, cache refresh and estimate |
| Accounting | Adjacent cached/uncached counts use comparable units | One reused criterion plus three freshly scored criteria in one provider reply | X16, actual scoring and report functions; metrics used as independent comparator |
| Committee/admin UI | Pending writes retain ownership and navigation retains context | Normalized email edit during write; feedback opened from another opening | X14/X15, actual components/hooks with deferred mocked API responses |
| Notes, settings, publication, access | Acknowledgements preserve newer drafts and scope | Source challenge of queues, uncertain writes, session remount, preview and decision replay | No additional finding; existing owners protect different guarantees |
| Performance / simplicity | Avoid redundant work and policy copies | Batched ranking reads, cost reporting, retained results, report consumers, all proposed remedies | No measured latency regression or broad rewrite justified; consolidate only the specific duplicated policies below |
| Recovery and external behavior | Preserve explicit evidence limits | Disk-fixture initialization failed in seven targeted cases; no production/provider probe | Recovery/concurrency source-reviewed where tests could not start; no new runtime conclusion from those failures |

### X07 — Historical links can restore superseded or cancelled email access

**Priority: P1.** `backend/app/api/applicant/links.py:163` regenerates using the old
`link.email` and `link.purpose`, even after its authority has been superseded or cancelled.
`backend/app/services/applications/access.py:77` accepts an application-bound access link
without comparing its email proof with the application's current primary address.

Two independent runs through the actual routes, using only synthetic identities and captured
email, reproduced both sequences:

1. Sign in as `old@example.com`, confirm a change to `new@example.com`, then anonymously
   regenerate the consumed original access token. The replacement goes to `old@example.com`;
   redeeming it permits GET `/applicant/application` and returns the current profile.
2. Request an email change, cancel it successfully (204), then anonymously regenerate the
   cancelled confirmation token. Redeeming the replacement applies the cancelled change.

Possession of the historical token and access to its recipient mailbox are required. This is
an access-control failure, not evidence of an incident or a claim about deployed production.
`SPEC.md:222–232` describes cancellation; stale-link renewal remains an intentional feature.

**Remedy / owner:** centralize purpose-aware renewal and identity checks in application access
services. Current-address access recovery can continue after ordinary expiry/consumption;
superseded addresses must not regain authority. Revoked/consumed email-change proposals must
not restart. Preserve renewal of expired, unused, nonrevoked proposals. Enforce the binding at
redemption as well as renewal, under the existing identity/write protections, including a link
issued before an intervening email change. Do not blanket-ban all stale links or duplicate policy
in the route. Handle draft-bound and application-bound links consistently without weakening
selected/withdrawn/expired application restrictions.

**Acceptance:** both reproduced sequences; ordinary expired/current-address recovery;
expired valid proposal; replaced/cancelled/completed proposals; intervening identity change;
draft claim; existing single-use and session-revocation behavior. **Latency:** existing target
lookup plus comparisons; no new provider work. This is first in the implementation order.

### X08 — Global aliases silently remove priorities from another opening

**Priority: P1.** `backend/app/services/ranking/member_state.py:83` transfers tier keys using
global aliases, while `dimension_weights` at line 104 still uses the target report's original
keys. `tier_history` at line 216 has the equivalent carry-forward mismatch.

Reproduced: A mints `older`; B has criterion `newer` in a positive tier. A consolidates
`newer → older`. Reading B rewrites the stored tier to `older`, but B's unchanged report
still contains `newer`. Its effective weight becomes zero; with one criterion, B becomes
unranked. A read has silently changed committee intent in an unrelated opening.

**Remedy / owner:** reconcile member placements against the captured target report. Preserve
keys still owned by that report; transfer an alias when that report has adopted the survivor.
Share this report-aware mapping between reconciliation and carry-forward. Do not rewrite
unrelated reports or rescore them to compensate. Review flagged/acknowledged key sets with
the same mapping, rather than fixing only the displayed weights.

**Acceptance:** two openings with different current reports; existing and newly materialized
member views; independent members; same-opening consolidation; alias chains; both source and
survivor present. **Latency:** local mapping over existing data; no provider call or new waiting.

### X09 — Final decisions omit withdrawn households from retention refresh

**Priority: P2.** `backend/app/services/openings/selection.py:163` and `:209` refresh deadlines
only for active participants. `backend/app/services/applications/retention.py:38` correctly
uses durable participation, including withdrawal, but is never called for these omitted rows.

Four isolated combinations reproduced this: selected-household/no-household decisions, each
with full profile withdrawal or withdrawal only from A while still active in B. When B finishes
before A, the final A decision leaves the withdrawn profile's deadline `None`; an overdue sweep
purges nothing. Explicit recomputation produces the expected one-year deadline. This conflicts
with `SPEC.md:685–690`: withdrawal changes access/scope, not the retention clock.

**Remedy / owner:** share a final-decision retention refresh across both decision functions,
covering every application with participation in that opening. Keep outcome assignment and
email audiences restricted to active participants. Do not reuse one participant filter for
these different responsibilities. In implementation, account for already-stale deadlines in
existing records through a reviewed data-repair plan; do not silently run a production purge.

**Acceptance:** both decision types and withdrawal forms, both completion orders across
openings, selected seven-year policy, eventual purge, no outcome email for fully withdrawn
profiles. **Latency:** one bounded participant-identity lookup and existing deadline calculations;
measure query count to avoid an unnecessary per-participant reload.

### X10 — Private draft expiry is stale or absent after creation and saves

**Priority: P2.** `backend/app/services/applications/intake.py:59` assigns initial expiry only
when selected IDs are truthy. Ordinary save at `backend/app/api/applicant/application.py:207`
and reconciliation at `:92` update selections without maintaining the private deadline.

Actual save-route reproduction: a draft chooses A closing October 7, then saves B closing
October 26. Its working selection is B, but expiry remains October 8; the sweep deletes it
while B is still open. Opposite reproduction: an empty-selection guest draft receives the
supported fallback deadline, but claiming it creates an Application with deadline `None`.
The sweep deletes the temporary draft and leaves the claimed private profile indefinitely.
`SPEC.md:669–673` establishes the draft lifetime.

**Remedy / owner:** make private-draft expiry one lifecycle rule applied on creation and
working-selection changes, including empty-selection fallback. Reuse it for ordinary save,
reconciliation, email claim and Google creation; remove the truthiness special case and
separate equivalent assignments. `refresh_draft_retention_for_opening` also needs to cover
empty-selection drafts whose fallback depends on that edited opening. Preserve submitted
participation-based deadlines. Existing private records need a scoped repair strategy that
does not turn this code fix into an unapproved production deletion.

**Acceptance:** A→B and B→A; empty selection; email/Google claim; reconciliation; opening
extension; submitted-copy deadline unchanged. **Latency:** existing close-date query on relevant
private saves; no extra browser round trip. Keep expiry policy out of generic answer-copy code
unless that owner is explicitly given the lifecycle context.

### X11 — Hidden archived openings make valid-looking resubmissions impossible

**Priority: P2.** `frontend/src/applicant/applicationDraft.ts:88` computes the residence cutoff
from form-visible open/closed offerings; `canonicalAnswers` drops unnecessary earlier addresses.
`backend/app/services/openings/participation.py:181` preserves required archived participation,
and `backend/app/services/applications/intake.py:149` includes it in the residence cutoff.

Actual API reproduction: archived close April 9, 2026, new visible opening close October 16,
2026, current residence began August 17, 2024. The form cutoff is October 16, 2024; its real
canonical helper removes previous addresses, even if they were retained in the draft. Submit
returns 422 demanding history back to April 9, 2024. The UI hides those previous-address inputs,
so an honest applicant cannot complete this request through the form.

**Remedy / owner:** compute submission residence validation from the same form-visible scope
required by `SPEC.md:48–50`, separately from immutable participation selection. Do not simply
remove archived openings from `publish_working_copy`'s selected list: that would change historical
participation. Visibility includes all shown open/closed offerings, not only checked choices,
and excludes inactive closed cards. Reuse the existing applicant-opening presentation rule;
keep one named cutoff policy per language, tested with identical scenarios. Earlier versions
remain historical; `SPEC.md:559–560` already allows later submissions while retaining archived
participation. No new grandfathering policy or selected-household edit permission is needed.

**Acceptance:** archived plus new opening; current address on either side of cutoff; prior
address pruning; inactive closed/unselected visible offerings; leap day; archived participation
and historical versions unchanged. **Latency:** derive scope from existing opening data where
available, with no extra browser request.

### X12 — A repeated submit can replace success with a stale-copy error

**Priority: P2.** `frontend/src/applicant/ApplicantReview.tsx` disables submit only for an
unchecked declaration. `applicantSaveFlow.ts:51` admits repeated starts while working; the
session guard does not order writes within the same session.

The real review component accepts two clicks while `persistencePhase="working"`. A real
`useApplicantPersistence` probe submits revision 1 twice: success at revision 2 sets `submitted`,
then the other request's late 409 sets `stale_copy`. The backend's revision protection is correct;
the UI misreports a successfully submitted application.

**Remedy / owner:** retain a synchronous pending-mutation guard in the existing applicant
persistence/save ownership and disable review submission while pending. The save-flow factory
is recreated each render, so a closure-local busy variable is insufficient; use stable ownership
from the hook. Cover sibling revision-bearing writes (`saveForReview`, `emailReturnLink`) and
release on failure. Old-session completion must not release a new session's operation. Do not
replace the hook with a general queue/state-machine library or discard the existing submitted
snapshot rules. Review navigation during submission must preserve any permitted newer edits.

**Acceptance:** rapid double click, both completion orders, rejection/network failure followed
by retry, review/edit interaction, session change, newer draft preservation. **Latency:** block
only a second conflicting mutation until the existing request settles; no additional work or
serial refresh on the ordinary successful submit.

### X13 — Consolidation loses coverage after reporting a successful rank

**Priority: P2.** `backend/app/services/ranking/analysis.py:179` drops the freshly scored key
and may revive a historical survivor without current scores for every applicant. The pipeline
at `pipeline.py:466` proceeds to completion; the summary at `:521` retains pre-consolidation
counts.

Reproduced through POST `/ranking/run`: `older` has current scores for applicants 1–3, `newer`
is scored for 1–4, then mock confirmation merges `newer → older`. The final summary says one
dimension, four scored, zero failed. The board omits applicant 4; dashboard coverage is 3/4
and correctly amber. Automatic cache adoption cannot repair it because the missing survivor
score does not exist; Score current would require another paid call.

**Remedy / owner:** gate cross-run replacements on complete current survivor coverage before
publishing the merge/alias. Defer an unsafe merge and retain the criterion just scored. Reuse
batched cache-planning checks. Do not copy scores under different frozen wording, insert zero
scores, or make an unestimated follow-up provider call. X08's report-aware tier mapping remains
necessary even for coverage-safe merges.

**Acceptance:** missing/stale/complete survivor scores, multiple replacements and alias chains,
board/detail/dashboard agreement, truthful final summary, no hidden provider calls. **Latency:**
bounded batched database lookup; no additional model latency. Consolidate the coverage predicate
with existing cache ownership instead of adding another readiness definition.

### X14 — Subscription writes lose ownership after a normalized email edit

**Priority: P2.** `frontend/src/components/admin/VacancyNotificationsPanel.tsx:148` clears busy
on every email edit, while write acknowledgements use a request scope keyed by normalized email.
Changing capitalization or surrounding whitespace therefore unlocks controls without invalidating
the pending write's scope. Read invalidation does not cancel captured write ownership.

Real component probe: start Replace preferences for `a@example.com`, edit to `A@example.com`,
look up again and successfully delete, then resolve the first save. The UI restores the deleted
subscription and says saved. Overlapping requests also leave actual server arrival order able
to conflict with the later intent. A sibling probe found deletion clears preference edits made
while that deletion is pending.

**Remedy / owner:** retain write ownership until settlement in this component; disable the email
control during save/delete while keeping lookup reads replaceable. During deletion, either lock
preference editing or preserve a permitted newer draft. Keep this local; no global mutation queue.

**Acceptance:** same-normalized address edits, both save/delete completion orders, replaceable
different-address lookups, failure/retry, delete versus newer preferences. **Latency:** only the
existing write duration restricts conflicting controls; no added requests or waits.

### X15 — Feedback links lose opening and retained-review context

**Priority: P2.** `frontend/src/components/admin/FeedbackPanel.tsx:119` passes only applicant ID
through `CommitteeWorkspace` to `useNavigation.viewApplication`, which uses the current opening.
The producer (`FeedbackButton.tsx:50`), feedback schema/model and response omit opening/retained
context; `route` stores only pathname and cannot recover it.

Real component/navigation reproduction: feedback for applicant 7 in A, admin currently on B;
click invokes `fetchApplication(7, B)` and fails when the applicant belongs only to A. If the
applicant belongs to both, it opens B's eligibility context instead of the reported context.

**Remedy / owner:** carry existing opening ID and retained-review mode through feedback's
context and use existing explicit-opening/retained navigation. Replace the insufficient ID-only
callback. Contextless older feedback can open the admin retained detail; do not guess its opening
or build a second navigation system. Scope non-applicant feedback links using the same available
context. Nullable context reflects feedback legitimately sent outside an opening, not a legacy
shape adapter. Preserve existing access checks and safe missing/purged-target behavior.

**Acceptance:** A feedback while B selected; applicant only in A or in both with different
eligibility; retained review; contextless feedback; unavailable target; back navigation.
**Latency:** existing detail/list loading can remain parallel; no added serial lookup needed.

### X16 — Cached and uncached cost counts use different units

**Priority: P3.** `backend/app/services/cost_report.py:174`/`:239` expose provider reply counts;
`frontend/src/components/observability/CostPanel.tsx:118`/`:151` labels them "uncached" next to
cached dimension-result counts. `backend/app/schemas/observability.py:19`/`:64` incorrectly
claims these are comparable per-result units.

Actual scoring/report probe: score `a`, then `a,b,c,d`. The second run reuses one criterion and
produces three fresh dimensions in one provider reply. Both cost tables display uncached 1 /
cached 1, while the metrics correctly show 25% cache hits using ledger `fresh_units: 3`.
This finding concerns count semantics; the probe did not establish incorrect dollar totals.

**Remedy / owner:** use the existing `fresh_units` for comparable result counts, retaining
unknown/null where interrupted attempts cannot establish them. Label provider reply counts
explicitly if they are retained. Update the response names/comments and shared table presentation
together. No new accounting store, estimates, or historic fabricated counts.

**Acceptance:** mixed reuse, successful re-asks, incomplete retries, interrupted attempts,
noncacheable passes, cumulative and last-run tables agree with metrics. **Latency:** existing
ledger data; no additional query/provider call needed.

### Verification, limits, and one combined implementation sequence

Fresh evidence from these independent passes (separate from earlier full-suite results):

- Lifecycle reviewer: **34 existing backend tests passed**; synthetic ASGI/in-memory probes
  confirmed X07/X09/X10. Four restore cases could not initialize their disk fixtures, before
  application behavior executed; restore remains source-reviewed in this extension.
- Ranking reviewer: **138 targeted backend tests passed**; mock-provider/in-memory probes
  confirmed X08/X13/X16. Three additional disk-based concurrency cases stopped at fixture setup.
- UI reviewer: **7 temporary component/hook tests passed**, three adverse-sequence probes plus
  four copied sibling regressions. All calls were mocked.
- Coordinating reviewer: independently repeated both X07 actual-route sequences; reproduced
  X11 through the real submit endpoint; **3 temporary frontend tests passed** for X11/X12.
- Temporary frontend probe files were removed. Backend probes ran from stdin. No production,
  live applicant database, real email/provider, dev server, or browser mutation was used.
  No full-suite rerun is claimed for this documentation-only extension.

The final challenge checked sibling producers and downstream consequences: cancelled versus
expired credentials; active-email audiences versus durable retention membership; private versus
submitted expiry; archived participation versus visible form validation; stable mutation ownership
across renders/sessions; global aliases versus local reports; coverage after consolidation; and
accounting units at the final UI. It refined X11/X12's remedies rather than opening another
unexamined candidate. For example, filtering archived selections wholesale would introduce a
withdrawal defect, and a factory-local submit guard would reset on every render.

Implement in cohesive commits within one authorized implementation phase:

1. **X07:** access-link authority and purpose-aware renewal, with route-level adverse tests.
2. **X09/X10:** separate durable retention membership from active outcomes; centralize private
   expiry maintenance. Prepare any needed existing-data reconciliation for explicit review.
3. **X11/X12:** align residence scope and preserve single-owner applicant writes.
4. **X08/X13:** report-aware tier reconciliation and coverage-safe consolidation, tested together
   across openings and the full run/board/readiness path.
5. **X05/X06/X14:** bounded UI loading/refresh/write corrections, retaining existing hook ownership.
6. **X15/X16:** feedback context and honest cost-count presentation through producers and consumers.
7. **X01/X02:** fixture family/expectation boundaries, including the previous challenge cases.
8. **X03/X04:** experiment wrappers before further model-comparison use.

The intended net change is fewer competing policies: one link-authority policy, one private-draft
expiry rule, one form-visible residence rule per language, one report-aware tier mapping, and
reuse of existing score-coverage and accounting data. Added guards should protect actual writes;
no general synchronization framework, speculative caching, module split by length, or blanket
serialization is recommended. Tests should target these real boundary sequences, replacing
superseded assertions rather than preserving duplicate helper tests.

To reduce misses, retain independent coverage assignments through discovery, then require each
finding to be challenged by another perspective **before implementation**. In particular, follow
transformations that occur *after* a successful operation (consolidation, acknowledgement,
regeneration, retention refresh), and compare membership sets across consumers (visible, active,
historical, retained). A broad passing suite is supporting evidence, not a substitute for those
counterexamples. Close when the coverage map is evidenced or explicitly limited and the final
challenge leaves no material candidate unexplored. This extension meets that bounded stop rule;
it does not promise that future review will find no defects.
