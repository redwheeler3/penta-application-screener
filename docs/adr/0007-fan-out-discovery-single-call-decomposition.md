# 7. Fan-out discovery + single-call decomposition (multi-agent loop not built)

- Status: **accepted** (still holds; replaced the sequential match/reconcile accumulation)
- Date: 2026-07-09 (decided, measured); committed 2026-07-11 (`0d52b7d`)

## Context

Re-running the Rank chain to accumulate the "fullest set" of dimensions over a locked pool
**did not usefully converge**: discovery re-carves the same concepts at different
granularities each run, and the sequential machinery (a 1:1 match pass + a reconcile pass
that revived dropped priors) *hoarded* every carving. The root cause: reconcile's per-axis
"does this vary?" test is near-unfalsifiable (discovery only coins an axis because it saw
variance), so coverage/redundancy — not variance — is the discriminating question, and that
can only be answered with **all carvings visible at once** (run 10 empirically confirmed the
model can decline on redundancy grounds once overlaps sit in one view).

## Decision

**K parallel blind discovery calls (no scoring) → one decomposition step that sees all K
reports at once and settles the finest non-overlapping set → score ONCE against the settled
set.** Default K=5. The decomposition step is a **single call forced to show evidence both
ways** (assert score-alike to merge; name a distinguishing applicant to keep separate).

The multi-agent alternative was **built and measured, then not adopted**: a
splitter↔merger↔referee loop was run against a single-call baseline on the 10-run fixture
and scored by an independent overlap judge (`scripts/dimension_overlap.py`, Pearson
correlation over cached score vectors — never the same model it judges).

## Consequences

- **The loop was strictly dominated**: 23% costlier, no more stable (0.62 vs 0.60 — noise),
  and *worse* on overlaps (0.7 vs 0.0). Its Splitter is a one-directional force (only splits
  merges apart, never merges more) — an adversarial skeptic on a merge step is a structural
  thumb toward under-merging, the exact creep it was meant to fix. Deleted in the cleanup sweep.
- **Coverage claim measured and held: K-parallel buys +36% distinct real-differentiator
  territory** (K-union 25 vs. single-run mean 18.4, padding excluded — `scripts/coverage_gate.py`).
  A single discovery run misses ~7 real differentiators fresh contexts surface. So the redesign
  is justified end-to-end: K-parallel for coverage, decomposition for cleanliness (0 overlaps).
- **Cost model corrected from the real ledger**: discovery is uncached and the *bigger* cost
  half (K discovery ≈ $0.85 at K=5 vs. scoring ≈ $0.52 on the fixture), so K carries real
  linear cost and stays small and fixed. The dimension-count reduction attacks the term that
  scales with pool size (~$5.75 vs ~$9.15 for the bloated set at n=300).
- **What carries forward, unchanged:** the identity **match pass** (adopts prior keys →
  cached scores + tier placements reuse), the per-(candidate,dimension) score cache, tier
  carry-forward, and the "revived/new" badge (presence-derived — an axis discovery drops then
  re-surfaces still badges "Revived," now that reconcile is gone).
- **Reconcile is fully deleted** (`dimension_reconcile.py`): its revive role was the creep
  engine, and K-fold discovery organically covers its one legitimate purpose (if an axis
  genuinely varies, at least one of K blind discoveries names it, and decomposition keeps it).
- **D9 (committee-request protection):** a `from_committee_request` axis gets a higher bar to
  merge away, enforced by a deterministic backstop (`enforce_committee_requests`) after
  decomposition — over-merge landing on an explicit human ask is surfaced ("your proposal X was
  folded into Y"), never silent.
- Embodies "measure before committing to the fancy architecture" — the fancy loop lost the
  bake-off on real data. Blow-by-blow in `docs/case-studies/dimension-convergence.md`.
