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
- [spec-milestones.md](spec-milestones.md) — completed delivery plans and point-in-time
  validation evidence moved out of the current specification on November 24, 2026.
- [Completed codebase audits](completed-audits-2026-11-24.md) covers the 13-finding and seven-finding rounds, their implementation decisions, and the validation receipts.

- [ponytail-audit-validation-2026-11-24.json](ponytail-audit-validation-2026-11-24.json) — fictional real-provider pipeline and five-repeat scoring evidence for the Ponytail fixes; includes failed attempts and unstable cases.
