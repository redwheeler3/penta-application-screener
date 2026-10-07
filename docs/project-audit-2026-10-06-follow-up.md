# Whole-project audit — 2026-10-06, post-implementation review

**Status: complete; X01–X06 recommended, not implemented.** Baseline `83bfd9e`, clean
working tree, ten local commits ahead of the recorded `origin/main`. The completed W01–W07
report remains at `83bfd9e:docs/project-audit-2026-10-06-follow-up.md`.

## Recommendation

Fix the dashboard loading race, the two fixture-contract gaps, and the disruptive trace refresh.
Repair the two command-line experiment wrappers before relying on their next model comparison.
These are bounded changes to existing owners. I do not recommend another architecture rewrite,
a general mutation framework, or additional production caching.

| ID | Priority | Finding | Evidence |
| --- | --- | --- | --- |
| X05 | P2 | A failed background dashboard refresh can strand initial loading | Both requests settle, but the real hook remains `loading`; reversing their completion order settles correctly |
| X01 | P2 | Fixture family metadata can disagree with its owning file/endpoint | Save returns 200; Judge lists the wrong family; its Run request returns 404 and current fingerprints use a different identity |
| X02 | P2, eval validity | Unknown screening flag names can silently weaken an assertion | A misspelled forbidden flag saves successfully and the real grader passes output that the correct spelling rejects |
| X06 | P3 | Passive trace refresh discards expanded operator content | An open discovery trace disappears during refresh and returns collapsed, even with identical data |
| X03 | P2, operator tooling | Golden model bake-off retains invalid success/completeness rules | Missing contested verdict counts as passed; all-error repeats report stable; a later grader error erases already-returned usage |
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

## X02 — Validate screening assertion vocabulary after normalization

**Anchors:** `backend/app/evals/case_schema.py:_ScreeningExpected`,
`backend/app/evals/screening.py:_normalize_fires`, `_case_from_expected`, `_check`.

A synthetic screening case with `expected.absent = ["fake_contcat"]` saved through the API
with status 200. A mock report containing `fake_contact` passed the real live grader. Correcting
the expectation to `fake_contact` made the identical output fail. The unknown name is never
produced by `FlagCategory`; it is an ineffective guard, yet it also prevents the case from being
treated as a clean-applicant check. Unknown required flags create impossible assertions instead.

The current committed corpus contains no unknown flag names; this is a hole in accepted edits,
not a claim that existing fixture results all need to be discarded.

**Recommendation:** normalize the supported string/list/pipe any-of forms with one shared rule,
then validate every leaf category against the existing `FlagCategory` vocabulary. Reject empty
names/groups and unknown forbidden/required flags before writing or running a case. Keep the
existing raw fixture/editor contract where possible; do not invent a second category list or
silently drop misspelled assertions.

**Acceptance:** all supported any-of representations, whitespace, empty values/groups,
unknown required and forbidden names, correct pet-only/clean cases, and identical live/Judge
meaning. An invalid save must leave the file unchanged. **Latency:** local validation only.

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

**Acceptance:** actual runner → wrapper → summary tests for valid contested divergence, invalid
output, missing score, one/some/all failed repeats, and returned usage followed by failure.
A complete consistently wrong answer can still be stable; operational failure cannot establish
measurement completeness. **Latency:** report bookkeeping only. Repair before the next CLI
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
