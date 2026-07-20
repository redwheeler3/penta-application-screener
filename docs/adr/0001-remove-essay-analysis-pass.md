# 1. Remove the essay-analysis pass (Milestone 6)

- Status: **superseded** (built in M6, removed in M13)
- Date: built ~M6; removed 2026 (M13 changelog "essay-analysis PASS deleted")

## Context

Milestone 6 added a per-candidate essay-analysis pass on top of the shared AI engine
(`analyze_application`, caching, cost estimate, cap, prompt versioning). It ran with
`kind="essay_analysis"` and produced a neutral committee-facing `EssayAnalysisReport`: a
fixed schema mirroring the four essay questions 1:1 (household context, employment,
interests, values, skills, prior co-op experience, motivations, contributions, evidence).
Its deliberate boundary was *extract and normalize what applicants said; do not judge* —
judgment was reserved for the M7 pattern-discovery/ranking passes so the differentiating
criteria are discovered against the actual pool, not pre-committed.

The stated intent: a normalized digest lets a screener skim ~300 candidates, and the
structured fields feed the ranker.

## Decision

**Delete the essay-analysis pass entirely.** Discovery and scoring now read the raw essays
(and structured `applicant_facts`) directly. See `pool_digest.py` and the Pattern Discovery
section of the SPEC for the current pool view.

## Consequences

- The decision was made **on measurement, not taste**: the digest inflated tokens ~172%
  over the raw essays while buying no additional discovery coverage. It was a net cost with
  no downstream benefit once discovery/scoring could read the source.
- Removing an intermediate lens removed a place for information to be lost or distorted —
  the raw essays were always preserved as the source of truth anyway, so the pass was an
  *additive* layer that turned out not to earn its cost.
- Confirms the project's measure-first discipline (the same stance later applied to model
  choice and to the fan-out bake-off): a plausible-sounding intermediate step must justify
  its tokens against a measured baseline.
- The M6 section is retained in git/history as the design record; the current spec keeps
  only the removal note.
