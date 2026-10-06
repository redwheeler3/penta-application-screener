# General project audit — 2026-10-05, follow-up review

**Status: complete.** Clean `main` baseline at `2ce157b`, ten commits ahead of the
locally recorded `origin/main`. This report replaces the implemented audit; that report
and its decisions remain in Git. This phase investigates and recommends, without runtime fixes.

## Scope and established decisions

Review the whole project in multiple passes for correctness, reliability/concurrency,
readability, redundant/dead code, simplicity and responsiveness. Follow findings into their
producers, consumers, sibling flows and tests; do not stop at an arbitrary finding count.

- Submission-time ages and automatic matching-cache adoption remain the policy.
- Complete current coverage determines Screen/Rank readiness; pending criterion proposals
  also make Rank amber. Retain consumed findings without per-applicant stale labels.
- Preserve the two distinct paid Rank actions and unranked behavior without positive priorities.
- Evals/Observability are admin-only; hosted eval runs remain uncapped; corpus editing is local.
- Local committed fixtures reach the hosted app through a manual deployment; push alone does not deploy.
- Previous **A04 export privacy/source-guard work remains deferred** and is not being proposed again.
- No production operations, real model calls, email delivery, dev-server start, page reload,
  database reset or applicant-data export is planned for this audit.

## Review passes

1. Inventory/recent changes: dependency reachability, shared contracts, long owners, redundant
   interfaces and instruction/documentation accuracy.
2. Backend: transactions, authority, application/opening lifecycle, cache ownership, model/run
   boundaries, eval fidelity, email/retention/recovery and operational paths.
3. Frontend: complete applicant/committee/operator journeys, response ordering, drafts and
   acknowledgements, view refresh ownership, action affordances and unnecessary waits/requests.
4. Adversarial consolidation: synthetic probes, concurrent/partial failure sequences, sibling
   checks, rejected hypotheses, baseline checks and cohesive implementation recommendations.

## Findings

The following findings have been reproduced with fabricated data and mock providers.
Four review passes and a second consolidation round are complete. IDs below identify distinct
fixes; some share an implementation package. All priorities describe the consequence of the
reproduced sequence, not an observed production incident.

| ID | Recommendation | Priority | Confidence |
| --- | --- | --- | --- |
| B01 | Make AI-run start/completion own passive-read fencing and affected view refresh | P2 | Combined real-hook reproduction |
| B02 | Keep live/restored eval results tied to the full experiment | P2 | API, real grader and hook reproductions |
| B03 | Capture/version the Judge prompt snapshot actually consumed | P2 | API/provider-argument and static-guard reproductions |
| B04 | Use the existing family plus key for aggregate Judge identity | P2 | API calls and history-loss reproduction |
| B05 | Fix backup creation/pruning order under timestamp collisions | P2 | Real temporary SQLite snapshots |
| B06 | Close accepted-but-unconsumable fixture shapes and invalid run modes | P2 / P3 mode typo | Valid-save/real-runner and API reproductions |
| B07 | Make committee note creation replay-safe after acknowledgement loss | P2 | Commit/lost-response/retry reproduction |
| B08 | Complete uncertain-outcome recovery for ordinary opening decisions | P3 | Real component reproduction; backend replay already safe |
| B09 | Restore current per-case coverage without the 30-row cutoff or unused reasoning | P2 / P3 projection | 35-case restore and SQL instrumentation |
| B10 | Share request-local eval dataset snapshots for repeated reads/counts | P3 | Ten reads counted for five files |

### B01 — Finish AI-run ownership of passive reads and completed views (P2)

`useRanking.setDisplayedProposals` invalidates passive reads, but `useAiRuns.runRank` calls
it only when discovery consumes nonempty pending proposals. A previously started board
refresh can therefore identify the member's own new analysis as another member's work while
a normal discovery run with no proposals is still active. The workspace suppresses new
passive reads during a run but does not cancel that already pending one in this sequence.

**Evidence:** a combined real-hook probe started a passive board read, started discovery
with zero proposals, and delivered the new analysis before completing the run response.
`rankRunning` and `staleAnalysis` were both true: the global another-member Reload notice
would be false. Existing coverage directly calls the proposal setter and does not exercise
this actual start path.

Screen completion also refreshes dashboard/applications without the loaded board. Since a
completed Screen has already selected its results, subsequent free adoption can report no
change and leave ranking eligibility stale until the next intake interval.
**Evidence:** a completed Screen hook probe kept the one-scored board despite a supplied
updated board and never made a second board request. This delay is bounded by the interval,
unlike the false live-run notice above.

**Recommendation:** explicitly fence passive reads at AI-run start, independently of proposal
changes, and reconcile affected displayed views after Screen completion. Use existing request
scopes/identities and one refresh owner. Keep saves and run acknowledgement responsive.
**Latency:** invalidate old reads and perform a free background read when needed; no model calls.

### B02 — Keep eval results tied to the complete experiment (P2)

Live/restored eval results are associated with case keys, prompt/model and reasoning, but
not the actual case input/expectation or stability repeat count. They can report a pass for
a changed case or combine different experiments as one current run.

**Evidence:** changing a scoring case's expected band from around zero to 0.7–1.0 kept the
stored zero score marked passed, with all staleness flags false. The actual grader rejects
that score against the new band. A K=2 partial stability run also restored an older K=5 case
under the K=2 header. A frontend probe ran one case with a new model: another case's old-model
green result remained in the live view while restored history correctly contained only the
new-model case.

**Recommendation:** capture a coherent experiment identity from existing case content and
relevant configuration; compare it for live accumulation and restored history. Inputs/labels,
effective model/reasoning and K matter; editorial notes should not force reruns. Keep historical
results inspectable and clearly separate from current coverage, without a second corpus store
or invented record IDs. **Latency:** local hashing/comparison, no automatic paid reruns.

### B03 — Stamp Judge with the prompt snapshot it actually uses (P2)

`run_judge` loads cases/briefs and then separately calls `judge.prompt_version`, which reads
the files again. A concurrent local brief edit can stamp a run with the new version while
the model receives the old brief. Per-file atomic I/O does not make these two read sets one
snapshot. The version also omits the static user-prompt/guard text in the reproduce adapters.

**Evidence:** an API probe edited a temporary brief between those reads. The mock received
the old system brief while both the streamed and persisted version matched the new brief.
A second probe changed the shared injection guard: the actual judge prompt changed while
its version stayed the same.

**Recommendation:** derive the version from the loaded prompt inputs and relevant static
template/schema, and pass that captured snapshot into the run. Share the reader rather than
locking files across model work. **Latency:** removes redundant file reads; no new model calls.

### B04 — Scope Judge case identity by its existing family and key (P2)

Each family allows its own keys, but the aggregate Judge selector, frontend selection/results
and saved-history merge use the key alone. Two valid family cases named the same can cause a
single-case action to run both, show/select the wrong case and lose one result on restoration.

**Evidence:** two temporary families with the same key caused one `?case=` Judge request to
make two mock calls and emit two cases. `/last-run` collapsed them into one. Both files were
valid under their family contracts.

**Recommendation:** carry the existing `(family, key)` identity through selectors, UI state
and history merging; no new UUID or global renaming rule is needed. Verify same-name cases
in live/stability, editing and restoration. **Latency:** avoids unintended model calls.

### B05 — Backup pruning can discard the newest recovery point (P2)

`backup.create_backup` handles timestamp collisions with `-1`, `-2`, … suffixes, but
`list_backups` reverses a lexical filename sort. Within one timestamp/tag, the unsuffixed
older file sorts ahead of a later suffixed file. `create_and_prune(keep=1)` can delete the
backup it just created and return a path that no longer exists.

**Evidence:** a temporary SQLite database was backed up, changed, and backed up again at the
same injected second. The newer file was deleted; the older file survived. No real backup
or application database was touched.

**Recommendation:** use trustworthy creation ordering consistent with collision handling,
and ensure the create/prune operation retains its new recovery point. Cover collision suffixes
and different tags. Review zero/negative retention parameters against the helper's recovery-point
contract. **Latency:** no normal application cost; confined to explicit backup tooling.

### B06 — Some accepted eval shapes still cannot be consumed (P2)

The shared schema accepts empty matching lists and optional descriptor names, but the live
matching runner indexes the first prior/new entry and direct-reads each name. Consolidation
also direct-reads names which its descriptor schema permits omitting. Because validation
does not rewrite the raw fixture, model defaults do not fill those fields in the saved data.

**Evidence:** three valid-save probes (empty prior, empty new, omitted prior name) loaded
successfully and then failed in the real matching runner with IndexError/KeyError before a
provider call. A valid two-descriptor consolidation case without names failed the same way.
The editor allows removing these fields/items.

**Recommendation:** align the required collection/descriptor shapes and actual consumers;
make required fields explicit or consistently use deliberate display fallbacks. Keep the
single validation boundary and preserve captured input; do not normalize silently through
unused temporary model defaults. **Latency:** cheap validation on operator paths only.

The HTTP run-mode boundary is also permissive: `mode=stabilty` silently ran normal paid
scoring instead of being rejected. **Evidence:** a temporary-corpus API probe emitted a
normal scoring summary and made one mock call for that typo. Use a literal/enum for the
supported modes; keep the existing documented K clamping and uncapped eval policy.

### B07 — Committee note creation is not safe to replay after a lost acknowledgement (P2)

The note composer preserves its draft and tells the member to try again on failure.
`POST /applications/{id}/committee-notes` always inserts a new attributed note; it has no
way to recognize a retry of the same creation attempt. A body timeout/transport failure
after commit therefore leads to duplicate notes when the member follows that instruction.

**Evidence:** an isolated ASGI transport allowed the first POST to commit, then replaced
its acknowledgement with the client-style 503. Retrying the same body created two notes
by the same author. The real composer retains the body and says “Try again” on false;
its action owner treats a non-OK response as failure without reconciliation.

**Recommendation:** give creation an explicit replay contract, retaining the exact submitted
attempt through uncertainty. First consider existing note identity/reconciliation; if a
creation-request key is needed because the server ID is not available before acknowledgement,
keep it local to that note attempt. Do not deduplicate arbitrary note text—intentional repeats
are possible. Private-note PUT and edits/deletes of known note IDs already have identities
and do not need a generic retry framework. Test commit-then-lost-body, retry, new drafts typed
while pending, account/applicant switches and deliberate repeated notes.
**Latency:** preserve immediate typing and use background reconciliation; no model cost.

### B08 — Permanent opening decision recovery still assumes transport errors throw (P3)

`OpeningDecisionPanel` has accurate uncertain-outcome copy in its catch block. The common
client turns transport/body timeouts into a non-OK 503 response, so that branch instead
forwards generic “Network request failed. Please try again” text and keeps the old selection
panel, without refreshing recorded state. Direct selection and opening publication now
handle this response path explicitly, so this is an inconsistent sibling journey.

**Evidence:** a real component probe supplied the client's 503 shape; it showed the generic
retry failure, kept Back enabled and did not acknowledge/reconcile the saved opening.
The existing backend supports exact decision replay, so this is confusing recovery, not a
claim of duplicate permanent selections or duplicate outcome emails.

**Recommendation:** classify uncertain responses consistently and reconcile the opening in
the background before inviting a different decision. Reuse the opening ID and existing
idempotent backend behavior. **Latency:** one exceptional-path read, no successful-save wait.

### B09 — History restoration drops current per-case coverage at 30 rows (P2)

`/evals/last-run` takes the newest 30 rows before accumulating cases. More than 30 one-case
runs in an unchanged experiment therefore lose earlier current results from the restored UI,
although those rows remain stored. The existing Judge corpus has 40 cases, so this is not
only a hypothetical scale problem. Live accumulation and restored coverage can disagree and
encourage unnecessary paid reruns.

**Evidence:** 35 synthetic current case results restored only 30. SQL instrumentation also
showed the history read selecting each row's unused `thinking` text, even though the response
intentionally excludes it.

**Recommendation:** restore the latest relevant result per existing scoped case and experiment
efficiently, instead of treating a fixed row window as coverage. Project only needed columns.
Avoid an unbounded history scan or a duplicate current-results table; verify the query plan,
including long repeated runs of one case, current/removed cases and experiment changes.
**Latency:** avoid loading unused reasoning and measure the coverage query; no automatic reruns.

### B10 — Reuse eval dataset reads instead of reading each family twice (P3)

The catalog loads each live family's cases and then loads them again for the aggregate Judge
count. This repeats I/O, parsing and validation, and can expose mismatched counts during a
concurrent local edit. Similar independent reads construct Judge cases versus its version
(B03). The datasets are small, so the catalog duplication alone is not a latency emergency.

**Evidence:** a real catalog request read all five golden files twice (ten reads). Static
ownership review confirms both counts describe the same family datasets.

**Recommendation:** share a request-local, typed dataset snapshot for counts and prompt
capture, while keeping each family's grader/adapter distinct. This belongs with B02–B04/B06,
not in a new global cache or generic eval engine. **Latency:** fewer redundant reads/validations.

## Coverage and verification

### Source evidence map

Pointers refer to the audit baseline `2ce157b`; they may move during implementation.

| Findings | Primary owners / consumers |
| --- | --- |
| B01 | `frontend/src/hooks/useAiRuns.ts:133`, `:227`; `hooks/useRanking.ts` passive reads and proposal setter; `CommitteeWorkspace.tsx` intake/run suppression |
| B02, B09 | `backend/app/api/evals/catalog.py:194`; `frontend/src/components/evals/useEvalRunner.ts:60`, live summary accumulation; `EvalResults.tsx` history marker |
| B03, B10 | `backend/app/api/evals/runs.py:343`; `app/evals/judge.py:56`, `:91`; `app/evals/reproduce.py`; the catalog's live/aggregate case loading |
| B04 | Judge route's key-only selector; `catalog.last_run` key-only merge; `components/evals/RunnableEval.tsx:106`, `EvalCaseList.tsx`, `useEvalRunner.ts` |
| B05 | `backend/app/services/backup.py:83`, `:105`, `:118`; root backup/restore wrappers |
| B06 | `backend/app/evals/case_schema.py:29`, `:68`; `matching.py:131`, `consolidate.py:124`; eval run query parameters |
| B07 | `backend/app/api/applications/routes.py:348`; `frontend/src/components/applications/CandidateNotes.tsx:62`; `hooks/useCandidateActions.ts` |
| B08 | `frontend/src/components/admin/OpeningDecisionPanel.tsx:31`; `api/client.ts` synthetic 503 responses; sibling direct-selection/publication handling |

### Review passes completed

1. **Inventory/ownership/redundancy:** inventoried 206 Python app/script modules and 130
   non-test frontend source/type modules. Python app graph: 196 modules, no static import
   cycle including deferred imports. Frontend graph including lazy imports: all runtime
   modules reachable, nine type-only modules intentionally excluded, no runtime import cycle.
   No exact long Python body duplicate was found after docstring exclusion. Runtime value
   export/reference checks found no further orphan requiring removal; namespace factories,
   lazy entry points and the intentionally test-used `ensure_lock_row` were cross-checked.
   Reviewed the recent implementation and owner map against current paths and contracts.
2. **Backend/operations:** traced applicant save/submission/revision and access lifetimes,
   deadline/participation/selection/retention boundaries, borrowed cache results and deletion,
   member/union eligibility, ranking/scoring/fingerprints/estimates, model retry and stream
   cancellation/leases, admin/identity checks, auth activity/rate limits, email claim/retry/
   consent fencing, daily maintenance, backup/restore, eval producers/readers/history, static
   serving and Fly/watchdog/recovery scripts. Rejected hypothetical findings where explicit
   authority, idempotency or existing scopes already carry the guarantee.
3. **Frontend/journeys:** traced guest/returning applicant save/review/submit, authentication,
   stale/pending-copy reconciliation, email identity and withdrawal, committee navigation and
   detail receipts, notes, eligibility/settings, cache adoption, Screen/Rank readiness and
   confirmations, board/tier/proposal refresh, opening creation/decision/direct selection,
   operator editing/live/restored evals, visibility/focus/session transitions and print views.
   Compared complete sibling journeys rather than proposing another generic state layer.
4. **Adversarial consolidation, two rounds:** followed plausible gaps into real callers,
   constructed 14 isolated backend and four frontend hook/component characterizations,
   all passing as demonstrations of the defects/measurement above. Used temporary corpus
   files, fabricated markers, isolated databases, mock providers and a lost-response transport.
   Removed throwaway probes before baseline checks. Cross-checked consumers, existing tests,
   runtime versus manual entry points, unchanged policy and implementation dependencies.

This is a broad repository review with targeted executions, not a line-by-line certification
or a production load/security test. No real applicant data was printed or exported, and no
real backup/database was altered. No server or model/email work was started.

### Baseline checks

Current verification passed after the throwaway probes were removed:

- Backend: **1,034 passed, one existing platform-dependent skip**; Ruff green.
- Frontend: **304 tests passed**; lint and TypeScript/Vite build green.
- Watchdog: **nine tests passed**; TypeScript check green.
- `git diff --check` green; generated build/cache directories inspected with inherited ACLs.
- Only this audit document changed. No runtime fixes, corpus changes, production operations,
  real model calls, outbound emails, database reset or backup/data export took place.

Passing baseline tests do not disprove the reproduced edge cases; their permanent regressions
belong with implementation. The characterization scripts were not retained as tests asserting
that bugs should continue to exist.

## Recommended implementation sequence

Gather these into one approved implementation effort with cohesive commits:

1. **Recovery correctness:** B05 backup ordering/retention contract, independently testable
   without affecting application paths. Preserve existing restore integrity, deletion-ledger
   and identifier-high-water protections.
2. **Committee actions:** B07 note creation replay contract, and B08's small opening recovery
   completion. Keep distinct resource owners and reuse existing identities where possible.
3. **AI view lifecycle:** B01 explicit run-start fence and post-Screen reconciliation. Verify
   zero/nonzero proposals, own runs, other-member changes, pending edits, focus/intake, account
   and opening switches, failures and completion; avoid blanket awaited refreshes.
4. **Eval consumer contracts:** B06 matching/consolidation shape requirements and valid modes.
   Keep preserved raw input and the shared validator/reader boundary.
5. **Eval snapshots and identity:** B03/B10 coherent dataset/prompt capture first; B04 family/key
   identity through UI/API/history; B02 experiment-aware accumulation and B09 efficient complete
   coverage/projections. These need coordinated regressions for live, partial and restored runs,
   local edits, deployed corpus changes, duplicate names, model/prompt/reasoning/K changes and
   changed/removed cases. Split by those ownership boundaries rather than creating a generic
   eval engine or a parallel dataset store.

No production change is needed to review/implement these fixes. Deployment and push remain
separate authorized actions. Previous A04 remains deferred, and eval budgets are not proposed.

## Complexity and latency assessment

The recent ownership, cache, writer and acknowledgement protections remain justified. The
confirmed weaknesses are incomplete lifecycle wiring and experimental identity/consumer
contracts, not a reason to discard the architecture. In particular, run ownership should not
depend on a proposal setter being called incidentally (B01), and validation cannot assume its
discarded model defaults rewrote the actual data (B06). Make those boundaries explicit once.

B02–B04/B06/B09/B10 should form one coherent eval data contract with captured inputs and
request-local snapshots. That can remove repeated reads and mismatched freshness logic; it
does not require another database, generic transaction framework or universal revision ID.
A replay key for a newly created note, if required, is different: the existing server-assigned
note ID is unavailable when its first acknowledgement is lost. Explain that narrow identity
tradeoff rather than silently inventing a second ID for every operation.

Normal applicant saves, committee edits and AI run acknowledgement should gain no extra
awaited derived-view refresh. B01 and B08 reconcile in the background, B05 is offline tooling,
and experiment/shape checks stay on operator paths. B04 avoids unintended paid calls. B09's
query must be measured so correct coverage does not become an unbounded slow history scan;
excluding unused reasoning is an immediate request-cost reduction. No recommendation adds
automatic AI reruns or invalidates applicant caches because a birthday occurred.

Request/file/SQL counts above are measured in synthetic probes. Production response-time
percentiles were not measured, so this report does not claim a measured user-facing speedup.

## What I would leave alone

- Keep submission-time ages, semantic cache identities and selected-result provenance. Keep
  automatic cache adoption, retained findings and complete-coverage readiness; do not restore
  cache-reuse prompts, per-applicant stale labels or discovery-fingerprint readiness.
- Keep the unranked message and hidden applicant/view/print controls without positive weights,
  the distinct paid Rank actions and hidden inactive closed opening cards.
- Keep admin-only Evals/Observability, local-only corpus editing and uncapped engineering runs.
  Do not build hosted editing, automatic deployment or an eval budget subsystem in this work.
- Keep current short writer/lease fences, snapshot acknowledgements, scoped reads, per-file
  mutation/I/O locking, targeted scoring re-asks, credential-before-send and consent-aware
  email consumption. Do not add blanket locks around network/model calls.
- Opening publication already freezes facts after uncertain responses and preserves its
  request identity; ordinary decision replay is safe on the backend. Do not recreate those
  mechanisms or claim that B08 causes duplicate permanent selections.
- Keep supported imported answers and historical migrations/ADRs. Retiring a form does not
  retire its stored data. Keep the cohesive ORM registry (1,124 lines); other largest frontend
  owners remain below the review threshold. No broad file splitting, rename/format sweep or
  dependency upgrade was justified by this pass.
- Keep bounded cache reads, union eligibility grouped by distinct rulesets, client-side
  list/filter/sort/facets and lazy feature entry points. Do not add new global caches or event
  buses for small request-local duplication. Derived activity timestamps and deliberately
  approximate cost estimates do not justify tightening ordinary request synchronization.
- `ensure_lock_row` is referenced by schema-only test constructors and lease tests, with an
  explicit purpose. It is not unreferenced runtime tombstone code worth deleting.
