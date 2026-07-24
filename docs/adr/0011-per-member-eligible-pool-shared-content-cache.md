# 11. Per-member eligible pool on a shared content-addressed cache (M15)

- Status: **accepted** (scoping; implementation pending)
- Date: Milestone 15 scoping (2026-07-23)

## Context

M15 makes the app multi-member (~5 committee screeners). The original SPEC framed this as a
**merge** feature: combine members' shortlists into one committee ranking, flag disagreement,
compare criteria. Talking it through, Jeff reframed it — the committee debates in a meeting
with each member's own list in hand; the app never needs to merge or compare. So M15 is an
**isolation** feature: N independent screening views on shared, expensive AI output.

Two forces pull against each other:

- **Independence:** each member wants their own eligibility rules, eligibility overrides,
  dimension tiering, and ranking.
- **Cost:** AI runs (discovery + per-applicant × per-dimension scoring) are the dominant
  spend. Doing that work once per member would multiply cost by committee size.

The tension concentrates on the **eligible pool**. Rankable applicants are the *eligible*
ones, and eligibility is now per-member (each member's rules + overrides). A naive "score the
whole synced pool once, filter per member" keeps one shared pool but scores applicants who are
ineligible for everyone — waste, since most applicants never clear the initial screen. The
opposite ("each member scores their own pool") forks the cache and re-bills shared work.

## Decision

**Runs operate on the union eligible pool; sharing rides on applicant identity via the
existing content-addressed cache, not on a shared pool.**

- **Globally eligible = passes *any* member's effective screen** (that member's rules *or* an
  explicit override) — a derived predicate over the per-member views, **no new stored state**.
  Discovery and scoring ground on this union floor. **Globally ineligible** applicants (no
  member passes them) are never scored, preserving "don't score applicants who won't clear the
  screen."
- **The score cache stays whole because its key carries no member id** —
  `(raw_row_hash, dimension_key, model, prompt_version)` (see ADR 0010). An applicant scored
  once (because any member ranked them eligible) is free for every other member who later
  includes them. Sharing is at the *applicant* grain, not the *pool* grain.
- **One shared union dimension set.** Any member's Rank can grow it; the existing match pass +
  `dimension_aliases` de-dup a re-discovered concept onto the prior key, so cross-member
  discovery reuses cached scores exactly as cross-run discovery already does. A dimension
  survives a re-rank if it sits in **any** member's working tier.
- **Staleness is per-member and reduces to a cache-gap check:** a member sees "re-rank needed"
  only when their eligible view references an applicant not yet in the shared analysis. A new
  shared dimension lands on every board at **weight 0** (inert until that member tiers it), so
  it costs others nothing until they opt in.
- **Data-model split:** shared `Analysis` (dimension_report + fingerprint + audit;
  `get_current_analysis()` replaces the `max(id)` `get_current_run`) + per-member
  `MemberRanking` (tiers/badges/proposals; weights stay derived) + per-member
  `MemberEligibility` (replaces the global status columns on `Application`). Eligibility rules
  split out of the shared `app_settings` blob into a shared committee default + per-member
  copy-on-write; infra config stays one shared row.

## Consequences

- The carry-forward cost win built for cross-*run* reuse (ADR 0010, `adopt_matched_keys`) now
  spans *members* with **no code change to the cache** — the deliberate exclusion of user/run
  identity from the cache key is what makes committee-scale sharing free. This is the payoff
  the observability/eval/cache investment was building toward.
- The only real AI spend is an applicant entering the union for the first time (or a
  rank-chain prompt/model change). Committee convergence on a common eligible set drives cache
  hit-rate toward 100%.
- **Not built:** merged shortlist, disagreement flags, criteria comparison, cross-member list
  visibility. Members' views are fully private; debate happens in the meeting. This dissolves
  the three prior M15 open questions (merge formula, disagreement calc, comparison layout).
- The per-run spending cap is **kept** for M15; a true atomic *shared* budget ceiling needs
  the hosted DB (single-tenant assumption #3) and is deferred to M16 — at ~5 members the
  caching is the practical cost control.
- Committee-proposed seeds feed the one shared discovery (shared axis); only the requester's
  "you requested this" provenance badge is per-member.
- Observability stays committee-wide (shared spend must be legible to all); runs gain a
  "triggered-by member" stamp so shared cost stays attributable.
- **Accepted corner case (Jeff, 2026-07-23):** consolidation is shared, so one member's run
  merging a true duplicate pair can shift another member's tiering (the survivor inherits the
  highest working-tier placement) without that member acting. This is accepted — a genuine
  duplicate merging is correct for everyone — rather than building per-member consolidation.
  A member adding applicants never ambers another member (staleness is per-member,
  view-scoped); the only cross-member ripples from a run are an inert weight-0 new dimension
  and this consolidation-driven tier shift.
