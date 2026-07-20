"""Shared mechanics for the three CATEGORICAL live evals — consolidation, matching,
decomposition.

Each of those passes produces ONE verdict token exact-matched against a human label
(merge/keep, matches/mismatches), so their grading + stability plumbing is identical; only the
production call that yields the verdict differs. This module holds the identical parts — the
result shape, the grade-a-verdict ladder, the stability summary line, and the
descriptor→PoolDimension helper — so the three modules keep only their own ``_verdict`` fn and
case loader. (Scoring and screening are deliberately NOT here: scoring grades a continuous band
and screening a per-category flag SET — genuinely different graders, not one verdict.)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.ai.schemas import PoolDimension
from app.evals.stability import DeltaSink, StabilityReport, emit


@dataclass(frozen=True)
class CategoricalResult:
    """One categorical case graded: the produced ``verdict`` vs the case's label, plus any
    ``failures`` (a non-empty list = failed). ``case`` is the pass's own case object (it carries
    ``expected``/``contested``); typed ``object`` here since the three passes each have their
    own case dataclass."""

    case: object
    verdict: str
    reason: str
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        # Raw direction-agreement. A CONTESTED case that diverges returns False here, but the
        # endpoint counts contested as passed regardless (both verdicts defensible — it passes
        # by running stably, not by matching the leaning); see the endpoint's `contested or r.passed`.
        if self.failures:
            return False
        return self.verdict == self.case.expected  # type: ignore[attr-defined]


def grade_verdict(case, verdict: str, reason: str, on_delta: DeltaSink) -> CategoricalResult:
    """Grade one produced ``verdict`` against ``case.expected`` and narrate it — the identical
    contested / mismatch / match ladder all three categorical passes share. ``case`` must carry
    ``expected`` and ``contested``. Callers handle a no-verdict result before calling this."""
    emit(on_delta, f"**Verdict: {verdict}** (expected {case.expected})\n\n- _{reason}_\n\n")
    failures: list[str] = []
    if case.contested:
        emit(on_delta, "◐ Contested case — both verdicts defensible; not counted pass/fail.\n")
    elif verdict != case.expected:
        failures.append(f"verdict {verdict!r} != expected {case.expected!r}")
        emit(on_delta, f"❌ Verdict disagrees with the label ({verdict} vs {case.expected}).\n")
    else:
        emit(on_delta, "✓ Verdict matches the label.\n")
    return CategoricalResult(case=case, verdict=verdict, reason=reason, failures=failures)


def emit_stability_summary(report: StabilityReport, on_delta: DeltaSink) -> None:
    """The identical closing line all three categorical stability runs emit: marker, agreement,
    and the per-verdict tally."""
    tally = ", ".join(f"{v} x{n}" for v, n in report.tally.items())
    emit(on_delta, f"\n**{report.marker}** {report.agreement:.0%} agreement — {tally}\n")


def descriptor_to_dim(d: dict[str, object]) -> PoolDimension:
    """A golden descriptor ``{key, name, definition}`` → a PoolDimension. The categorical passes
    serialize only key/name/definition, so the poles are unused here — filled empty, never sent
    to the model."""
    return PoolDimension(
        key=str(d["key"]), name=str(d.get("name", "")), definition=str(d["definition"]),
        high_end="", low_end="", why_it_differentiates="",
    )
