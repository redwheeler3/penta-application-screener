# Archived docs

Point-in-time design/investigation memos whose decisions are now baked into the code and
recorded in `docs/adr/` + `CHANGELOG.md`. Kept for the reasoning trail, not as current docs.

- `score-defensibility-design.md` — the design for the score-defensibility judge (M13). The
  live eval is now a deterministic band grader + a blind Judge-tab auditor; see
  `docs/adr/0002-blind-judge-eval-reframe.md` and `docs/ai-evals.md`.
- `pass-io-investigation.md` — the read-only audit of every pass's real prompt input/output
  that grounded the eval case schema (the `given`/`produced` split, shared `descriptor`,
  and the "unify serialization, not verdict schemas" call). The decided outcomes live in
  `docs/eval-case-schema.md`.
