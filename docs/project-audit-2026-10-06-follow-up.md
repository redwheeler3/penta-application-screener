# Two-pass analysis: invalidation and uncertainty — 2026-10-06

**Status: both requested analyses complete; three recommendations remain open.**
Baseline: clean `main` at `b68e6a0`, matching the recorded `origin/main`.
Application code and permanent tests are unchanged. This report replaces the active
audit narrative; the completed U01–U06 campaign and its full evidence remain in
`b68e6a0:docs/project-audit-2026-10-06-follow-up.md`.

## Result

We missed three worthwhile issues. Two are gaps in the recent eval/ranking changes;
the private-note issue predates that consolidation. Four controlled frontend probes
confirmed the behaviors below. None used applicant data, a real model, or production.

| ID | Priority | Finding | Discovered in |
| --- | --- | --- | --- |
| V01 | P2 | Eval output can be promoted to current after its validation context is lost or not refreshed | First pass; related failure case found in second pass |
| V02 | P2 | An older board response can erase newer evidence that the displayed analysis is stale, suppressing its warning | Second pass using the revised method |
| V03 | P2 | Reverting an unconfirmed private-note save can claim success without restoring the server value | Second pass using the revised method |

The shared lesson is specific: **retaining a value does not establish that it is
current or saved.** Earlier tests exercised successful retention, invalidation, and
failure separately. They did not sufficiently combine an adverse starting state,
an unrelated completion, and failed verification, or run independent completions in
both orders. The previous closure conclusion was too strong for that coverage.

The recommendation is to fix these within their existing owners. A new workflow
engine, global status registry, persistent identity, or broader synchronization
scheme is not warranted. Most protections reviewed continue to serve distinct purposes.

## Pass 1 — Challenge the completed changes

Reviewed the new eval result-source contract and its callers/tests, the ranking
dashboard/board observation paths, saved-draft acknowledgements, and existing uncertain
write handling. The first counterexample was V01-A: a result already excluded as
stale became current again after an unrelated case completed and metadata refresh failed.

That is stronger evidence than a green suite or a source smell: the real hook's current
case results changed from absent to passing without any new evidence for that case.
The failure led to the revised method below, which was then used for the second pass.

## Revised best practice

For an asynchronous workflow, write down four things before choosing test cases:

1. **Claim:** what does the UI/API mean by current, saved, permitted, complete, or blocked?
2. **Evidence:** which authoritative fact supports that claim, and when was it captured?
3. **Invalidation:** what event makes the evidence stale, uncertain, or inapplicable?
4. **Recovery:** what positive evidence is required before the claim can become true again?

Then start from stale, blocked, or unconfirmed state and combine it with a second
operation. Exercise both completion orders, plus a delayed/failed dependent refresh.
An unrelated success, an old matching value, or missing metadata must not silently
restore confidence. Conversely, a genuinely new grant, confirmed save, or fresh
authoritative read can restore it; this is not a rule against legitimate recovery.

For this project, the smallest useful set is:

| Starting state | Interleaving to exercise | Required property |
| --- | --- | --- |
| A case's result is known stale | Another case completes; metadata read fails | The stale case does not become current |
| A fixture edit is acknowledged | Its follow-up metadata read fails | Old output is not certified against the changed label |
| A board is known superseded | An older parallel board read completes | It cannot erase the stale observation |
| A write is unconfirmed | The user returns to the previously acknowledged value | Equality alone cannot prove the server has that value |
| A session/lease/intent is revoked or replaced | Old work returns | Only the still-authorized owner may publish/acknowledge |

This complements the previous trigger → authority → consumer review. Tests must
exercise real triggers, but they must also start with inconvenient state and permute
the competing completions. The narrowly scoped rule is now recorded in `.clinerules`
under Engineering Defaults for future async reconciliation work.

Preserve responsiveness: old values may remain visible while verification is delayed.
The requirement concerns the strength of the claim made about them, not a mandatory
network wait before every render or action.

## Pass 2 — Apply the new method

Reviewed each row below from an adverse starting state. The method found V02, V03,
and a second manifestation of V01; it also rejected or narrowed several hypotheses.

| Owner/boundary | Evidence and result |
| --- | --- |
| Eval receipts, saved cases, current metadata | Two reproduced promotions without sufficient evidence; V01 |
| Dashboard observation and board acceptance | Reproduced the reverse completion order missing from the previous tests; V02 |
| Private-note queue and last acknowledged body | Reproduced unconfirmed write → revert → false saved acknowledgement; V03 |
| Browser draft revision/consent | Existing scope/revision checks reject delayed older writes; targeted regressions passed |
| Session change and revalidation | Failed revalidation does not clear the session-changed state; explicit successful continuation does; source review and targeted session tests |
| Settings/eligibility saves | Save success requires an acknowledged response; drafts and their saved indication remain distinct; no equivalent no-write shortcut was found |
| Opening publication/selection uncertainty | Unconfirmed publication prevents changing its facts; uncertain final decisions remain held for reconciliation; reviewed callers and publication regressions |
| Email cancellation and superseded attempts | Completion is conditional on queued state, attempt count and attempt time; targeted regressions passed |
| Replaced/expired run leases | Renewal, commit and release check the acquired lease, not merely the user ID; targeted regressions passed |
| Revoked administrative authority | Shared writes reload authority under the writer guard; targeted regressions passed |

An apparent authenticated draft-clear cleanup issue was not promoted to a finding:
the ordinary Clear this draft UI is signed-out-only, so a search hit in an authenticated
branch did not establish a normal reachable failure. Any cleanup there should first
prove its real caller. Do not add defensive machinery merely because a branch exists.

Production snapshot rollback remains an explicitly accepted policy. This pass does
not reclassify that decision as a new bug or propose a general recovery ledger.

## V01 — Preserve validation knowledge independently of retained eval output

**Anchors:** `frontend/src/components/evals/evalResultState.ts:33,82`;
`frontend/src/components/evals/useEvalRunner.ts:41`; the case-save acknowledgement in
`components/evals/RunnableEval.tsx`.

### A. A different case's completion revives known-stale output

Controlled sequence through the real `useEvalRunner` hook:

1. History contains passing results A and B. B was produced from fingerprint `b1`;
   current metadata says B is now `b2`.
2. The hook correctly omits B from current case results.
3. Run A only. Its valid summary arrives; make the ensuing metadata/history request fail.
4. B reappears as a passing current result using `b1`.

`acceptEvalReceipt` deletes the mode's current metadata so a newly delivered receipt
can be visible. `matchesCurrent` then treats missing metadata as acceptance for every
source, including reconstructed historical cases. The comment describes a fresh-receipt
exception, but the predicate also grants that exception to unrelated stored output.
This can last beyond a transient render when refresh fails.

This manifestation was introduced by the recent reconciliation change. The new
retention design is useful, but deleting validation context lost previously established
negative knowledge. The tests combined a failed refresh with good output; the stale
other-case sentinel was missing.

### B. A confirmed label edit can leave its old pass current

A second controlled hook sequence began with A=0.8 passing a minimum of 0.5. The real
case setter accepted a saved fixture whose minimum was now 0.9. Its follow-up metadata
read failed. The displayed fixture contained the new minimum, but A remained a current
passing result with the previous fingerprint.

The setter updates fixture data and asks for new metadata without invalidating the
affected current-result claim. The missing-history fix therefore does not cover failure
of the metadata read after a known successful edit. This is a residual failure-path gap,
not evidence that the fixture save itself failed.

**Recommendation:** keep last-confirmed validation metadata; do not erase it to make
received output visible. Distinguish retention/presentation of the receipt from whether
that output qualifies as current coverage. A fresh receipt must not make unrelated
historical cases eligible. An acknowledged case/brief change must invalidate affected
coverage using metadata from that acknowledgement, or leave it explicitly unverified
until refreshed. Prefer returning the existing semantic fingerprints/version information
with the successful edit response over duplicating the hashing rules in JavaScript.

Continue preserving paid output, editorial-note reuse, per-case source run IDs and
separate mode coverage. Do not add another durable results store, automatically rerun
models, or turn every metadata refresh into a blocking UI operation.

**Acceptance:** retain a stale B sentinel while A completes; delay, reject and then
recover the metadata read. Test both recorded and unrecorded A. Repeat with a label
edit, input edit, and judge-brief change, while confirming editorial-only changes keep
valid output. Assert current dots/summaries and retained details separately.

**Latency/complexity:** use the existing pure reconciliation owner and mutation response.
No model work is needed. Metadata acknowledgement may add a small projection to a
response, but should not add a serial network dependency for ordinary operation.

## V02 — A stale observation must fence older board reads

**Anchors:** `frontend/src/hooks/useRanking.ts:130,151,164` and the parallel intake
refresh / stale-toast effect in `frontend/src/CommitteeWorkspace.tsx`.

Controlled sequence through the real `useRanking` hook:

1. Display board 1 and begin a passive board refresh whose captured response is board 1.
2. A parallel dashboard read establishes that analysis 2 is current.
3. `observeCurrentAnalysis(2)` marks the displayed board stale.
4. The older board-1 response arrives and `adoptBoard` clears `staleAnalysis` again.

The probe batched steps 2–4 as neighboring async completions. The effect that would
show the stale warning never observed `true`: the old board remained displayed and
no warning was raised. This is not merely an internal flag mismatch. Server-side
stale-analysis checks still reject writes to the superseded board; no wrong-board
database write was demonstrated.

The previous tests covered old dashboard observation **after** newer board acceptance.
They did not cover the reverse: newer dashboard knowledge **before** older board
acceptance. Reusing the dashboard read introduced an independent producer of this
fact, without making its stale transition invalidate the older board request.

**Recommendation:** when a trustworthy observation marks the board stale, invalidate
older board reads using the existing request scope, and keep the displayed view settled.
Clear that knowledge only when a suitable fresh/explicit board read is accepted. Check
the loading-state consequence of cancelling a request too; do not leave a spinner waiting
for an acknowledgement that was intentionally discarded. No extra ID or observer registry
is needed, and fresh reads should remain parallel.

**Acceptance:** both dashboard/board completion orders, including one React batch;
stale observation → failed reload → successful fresh reload; pending member edits and
an opening change. Verify the warning effect and displayed analysis together, not only
one final boolean in isolation.

**Latency/complexity:** request invalidation and state ownership only. No additional
normal-case request or lock is required.

## V03 — Equality with an old acknowledgement cannot settle an uncertain note save

**Anchors:** `frontend/src/hooks/usePrivateNotes.ts:66,87,197`;
`frontend/src/api/client.ts` ordinary-response failure handling;
`backend/app/api/applications/routes.py:save_private_note`.

Controlled sequence through the real private-note hook and a simulated committed server:

1. The last acknowledged note is `Original`.
2. Save `Committed but unconfirmed`. The server model accepts it, but the client receives
   the transport's 503 outcome instead of the acknowledgement.
3. The hook correctly reports an error and keeps the draft.
4. The user changes the text back to `Original` and flushes the queue.
5. `body === savedBody` skips the request. The hook reports `saved`, and
   `hasUnconfirmed()` becomes false, although the server still has the changed text.

The scenario is reachable: the actual endpoint commits before returning, and the browser
transport maps a lost/timed-out response body to 503. The mock explicitly models the
server commit; no real applicant note was changed during the probe.

The equality optimization assumes the last acknowledged value still describes the
server after an uncertain write. It does not. This issue predates the consolidation.
Existing tests covered reverting during a successful pending save and retrying rejected
writes, but not a committed write with a lost acknowledgement followed by a revert.

**Recommendation:** remove the equality-based no-write shortcut for dirty/retry drafts.
Keep the existing early return for a confirmed saved draft, debounce, per-applicant queue,
and superseded-draft skipping. Once a dirty or retry draft reaches the writer, send its
desired value and mark it saved only after acknowledgement. This is simpler than adding
another confidence flag alongside `savedBody` and `status`.

**Acceptance:** commit → lost acknowledgement → revert → retry; test the retry succeeding
and failing. Confirm the actual server model, displayed text, saved status and leaving
warning agree. Also retain newer typing, independent-applicant, account-exit and blocked
draft tests. An explicit discard is not a promise to undo an already-sent server write.

**Latency/complexity:** typing remains debounced and nonblocking. A local edit reverted
to the prior value can now make one otherwise-skipped small save; there is no preceding
read or extra round trip per ordinary save. The correctness benefit warrants that bounded
write, and the implementation should remove branching rather than add a new subsystem.

## Verification and limits

- **Four temporary counterexample probes passed assertions for the defective behavior.**
  They exercise real React hooks with controlled API completions and synthetic values.
  They are evidence of bugs, not successful regression tests for proposed fixes.
- Existing targeted frontend suites: **81 passed across six files** (eval runner, ranking,
  private notes, sessions, remembered drafts, opening editor).
- Existing targeted backend suites: **41 passed** (run locks/streams, email outbox and
  administrative write authority).
- Those green suites alongside the probes demonstrate a coverage gap. A larger count of
  similar tests would not address the missing state/order combinations.
- Probes were removed after recording the sequences. No permanent test or application
  code changed. No dev server, real email/model call, production read/write, database reset,
  or applicant-data export was involved.
- This was a targeted follow-up analysis of asynchronous truth/acknowledgement boundaries,
  not another line-by-line whole-repository certification or a production latency benchmark.

## Recommended next work and stopping rule

Implement V03, V02 and V01 as cohesive changes in their existing owners, adding the
counterexamples as expected-behavior regressions. Retain the useful test cases; replace
overlapping branch assertions rather than stack them indefinitely. Review each fix with
the adverse-state table and both completion orders before calling it closed.

Then perform a cross-owner pass specifically asking: **what evidence could this transition
forget, and what claim would then become too strong?** Report covered boundaries and
remaining product decisions explicitly. Do not respond to a newly found combination by
adding a global framework or by claiming that another broad reread can guarantee no misses.

The method improved the second pass: it found two additional owners with the same class
of mistaken confidence and one related eval edit case. It does not establish that every
remaining defect has been found. At this point these three recommendations are the
confirmed, worthwhile follow-up work; the other reviewed guards do not need a rewrite.
