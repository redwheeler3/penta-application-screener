# 8. Grader matched to output shape + prompt versions derived by hashing

- Status: **accepted** (still holds)
- Date: 2026-07-18 (grader architecture); prompt-version derivation predates it (M13 foundation)

## Context

Honest evals of non-deterministic passes require two things: a grader that can *honestly*
pass/fail a given pass's output, and a way to attribute every stored result to the exact
prompt that produced it. Two anti-patterns to avoid: putting fuzzy/nondeterministic checks in
the commit gate, and reusing cached results judged under a since-edited prompt.

## Decision

**Match the grader to the pass's output shape:**

- **Categorical** output (consolidation/decomposition `merge·keep`, matching
  `matches·mismatches`, screening flag supported/unsupported) → **deterministic exact-match**
  against the human label.
- **Scoring** (continuous) → **band check** (`expected = {score_min, score_max}`; produced
  score must land in range). See ADR 0002 for how the LLM judge role was reframed to a
  separate blind auditor rather than an inline grader.

**Derive each cached pass's `prompt_version` by hashing its static prompt text** (system
prompt + instruction template + any shared fragment it embeds), computed once at import via
`derive_prompt_version(...)` and threaded into `cache_key`. Only the *template* is hashed —
applicant content is already covered by `raw_row_hash`, and per-application values are
interpolated at call time, outside the hash. **Exception:** per-settings values that change
the model's answer (the filled pet-policy line) *are* folded into the version.

## Consequences

- **The eval split is by determinism, not "is it an eval":** things that are always a bug are
  hard-fail **invariants** in CI (`poles_present`, `no_protected_attributes` — narrowed to
  whole-word unambiguous terms after a crude version false-flagged "charity **race**s"); fuzzy
  judgement calls are report-only **signals** (`overlap`, `match_rate`). A check you'd have to
  soften to keep green is a signal, not an invariant.
- Invariants are **discovered-green** — they pass because the output is genuinely good, never
  because a check was tuned to the data. Fixtures are a blessed baseline, re-recorded only
  after a human confirms a new run is genuinely fine.
- **Editing a prompt changes only that pass's version and re-runs only its cache,
  automatically** — no global version constant to remember to bump. An eval set is thus
  auto-partitioned by prompt revision, and a prompt change can never silently reuse results
  judged under the old wording. (The pet-policy inclusion fixed a real bug where a policy
  change reused stale results and reported "up to date" while over-limit applicants stayed
  flagged.)
- **A dimension key's descriptive tuple is frozen at mint** (`(key, definition, poles,
  why_it_differentiates)`) — different text means a different key — so a cached score always
  represents the definition the model actually scored against. History builders return each
  key's earliest (mint) definition; a retired alias donates no text. Guarded by regression test.
- Pattern discovery and matching are uncached and have no version. See `docs/ai-evals.md`
  and `docs/eval-case-schema.md`.
