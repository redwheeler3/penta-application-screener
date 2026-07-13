"""``uv run python -m app.evals.run`` — the human-facing eval report.

Prints both tiers over the committed fixture:
  INVARIANTS — pass/fail; a breach is a real bug (and also fails pytest, the CI gate).
  SIGNALS    — judgement observations to read like a manual audit; never pass/fail.

This never exits non-zero on a signal — only the pytest gate (invariants) blocks a
commit. Run this to eyeball a run's health; run pytest to enforce the invariants.

Sample output::

    AI evals — 31 dimensions, 37 score vectors  (fixture: rank_baseline.json)

    INVARIANTS (gate CI)
      ✓ poles_present
      ✓ no_protected_attributes
      ✓ one_concept

    SIGNALS (review, never block)
      overlap
        ! r=0.86  communal_social_orientation ~ cooperative_values_alignment
          r=0.74  breadth_of_contribution_roles ~ essay_specificity
      match_rate
        ! 26/26 carried forward (100%)
"""

from __future__ import annotations

from app.evals.fixture import FIXTURE_PATH, EvalFixture, load
from app.evals.properties import (
    INVARIANTS,
    SIGNALS,
    Signal,
    Violation,
    run_invariants,
    run_signals,
)


def format_report(fixture: EvalFixture, violations: list[Violation], signals: list[Signal]) -> str:
    lines = [
        f"AI evals — {len(fixture.dimensions)} dimensions, "
        f"{len(fixture.score_vectors)} score vectors  (fixture: {FIXTURE_PATH.name})",
        "",
        "INVARIANTS (gate CI)",
    ]
    by_check: dict[str, list[Violation]] = {}
    for v in violations:
        by_check.setdefault(v.check, []).append(v)
    for check in INVARIANTS:
        name = check.__name__.removeprefix("check_")
        hits = by_check.get(name, [])
        lines.append(f"  {'✓' if not hits else '✗'} {name}")
        lines.extend(f"      {v.subject}: {v.detail}" for v in hits)

    lines += ["", "SIGNALS (review, never block)"]
    by_sig: dict[str, list[Signal]] = {}
    for s in signals:
        by_sig.setdefault(s.check, []).append(s)
    for sig in SIGNALS:
        name = sig.__name__.removeprefix("signal_")
        lines.append(f"  {name}")
        for s in by_sig.get(name, []):
            lines.append(f"      {'! ' if s.concern else ''}{s.note}")
    return "\n".join(lines)


def main() -> None:
    fixture = load()
    print(format_report(fixture, run_invariants(fixture), run_signals(fixture)))


if __name__ == "__main__":
    main()
