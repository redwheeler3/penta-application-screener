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
from typing import Protocol

from app.ai.schemas import PoolDimension
from app.evals.stability import DeltaSink, emit


class CategoricalCase(Protocol):
    """The labelled fields shared by each pass's immutable case dataclass."""

    @property
    def key(self) -> str: ...

    @property
    def expected(self) -> str: ...

    @property
    def contested(self) -> bool: ...


@dataclass(frozen=True)
class CategoricalResult:
    """One categorical case graded: the produced ``verdict`` vs the case's label, plus any
    ``failures`` (a non-empty list = failed). ``case`` is the pass's own case object (it carries
    the shared label fields); its additional input fields remain pass-specific."""

    case: CategoricalCase
    verdict: str
    reason: str
    failures: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def passed(self) -> bool:
        # A missing/invalid verdict is an error even when valid disagreement is contested.
        if self.error or self.failures:
            return False
        return self.verdict == self.case.expected


def grade_verdict(case: CategoricalCase, verdict: str, reason: str, on_delta: DeltaSink) -> CategoricalResult:
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


def descriptor_to_dim(d: dict[str, object]) -> PoolDimension:
    """A golden descriptor → a PoolDimension. ``high_end``/``low_end`` are carried through when
    the descriptor supplies them, empty otherwise: the decomposition pass serializes the poles
    into its prompt (they are what tells an inverse pair from a duplicate), so its cases must
    provide them to run the model on the same input production sends; the matching pass drops
    poles from its prompt, so its cases omit them and get the empty fallback."""
    return PoolDimension(
        key=str(d["key"]), name=str(d.get("name", "")), definition=str(d["definition"]),
        high_end=str(d.get("high_end", "")), low_end=str(d.get("low_end", "")),
        why_it_differentiates="",
    )
