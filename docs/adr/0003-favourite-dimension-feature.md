# 3. Favourite-dimension feature: added, reversed, then collapsed into tier membership

- Status: **reversed / superseded** (the "★ favourite" mechanism no longer exists)
- Date: added; slated for removal 2026-07-09; removal reversed 2026-07-10; superseded by
  "kept = tier membership" 2026-07-17

## Context

Dimension discovery is nondeterministic: a criterion the committee cares about can blink
out of a re-run's chips. To let a member protect an axis across re-runs, a **favourite**
seed was added — a ★ on each criterion meaning "keep this axis across re-runs"
(`criteria.favourited_keys`, `prior_favourited_keys` in `create_run`, favourite injection
at decomposition, auto-favourite on `from_committee_request`).

The feature went through a full arc:

1. **Added** — the ★ "keep this axis" affordance.
2. **Slated for deletion (2026-07-09)** — on the belief that automatic reconcile subsumed it
   (reconcile would silently revive dropped priors, so an explicit keep was redundant).
3. **Removal reversed (2026-07-10)** — the premise collapsed: reconcile was itself being
   deleted (the fan-out redesign retired its revive role — see ADR 0007), so the mechanism
   meant to replace favourite was gone. And K-parallel discovery made dimensions *more*
   stable but not stable enough (a member watched a tiered axis blink out). The "keep this
   axis" need was real again, so favourite stayed.

## Decision

**Collapse "favourite" into tier membership; the ★ is removed (2026-07-17).** The ★ was a
*second* signal a member had to remember on top of tiering, and forgetting it meant a
silently-droppable dimension — the exact destructive behavior being eliminated for a live
committee. The insight: **tiering a dimension already expresses "this matters," so it should
imply "keep it."** New rule: **a dimension in ANY working (non-Ignore) tier is kept; Ignore
is the only "fair game to drop or re-carve" bucket.**

## Consequences

- **No separate stored set.** `kept_keys(run)` derives the kept set from the run's working
  tiers; it can never drift out of sync with the tiers. `criteria.favourited_keys`, the
  `prior_favourited_keys` param, and `set_seeds`'s favourite arg are all gone (`set_seeds` →
  `set_proposals`). `favourited` → `kept` throughout.
- **Two buckets, no "park-but-protect."** The old "★ but leave in Ignore" state
  (protect-but-don't-weight) was deliberately given up: if you care enough to keep it,
  weight it. If the need reappears, the answer is a dedicated "Keep, unweighted" tier.
- **Committee proposals** (`from_committee_request`) survive their introducing run via the
  within-run D9 guard, land in Ignore for triage, and are *not* auto-kept across runs — an
  Ignored axis is "seen, not weighted," fair game on the next Rank.
- **`from_committee_request` is per-run provenance, not a durable mark.** It means "a member
  proposed this axis on *this* Rank," so `enforce_committee_requests` recomputes it
  authoritatively — true iff the settled axis absorbed a fresh proposal — and it clears on the
  next Rank regardless of tier. A kept (tiered) axis carries the flag false: on subsequent runs
  it survives as an ordinary carried dimension (injected at decomposition, never dropped), not
  as a standing "requested" axis. Kept-axis survival is decoupled from the flag.
- **Merge carries tier placement, not a favourite:** consolidation transfers the dropped
  twin's highest-priority tier placement to the survivor, subsuming favourite-transfer-on-merge.
- Illustrates a recurring principle: prefer deriving a signal from existing state
  (tier placement) over a parallel stored structure a user must maintain.
