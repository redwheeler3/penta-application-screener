"""Shared stability measurement — run one eval case K times on FIXED input and read whether
the outcome held.

Every LLM pass is non-deterministic, so each live eval and the judge ask the same question:
"on identical input, does the model return the SAME outcome every time, or flip-flop?" The
outcome TOKEN differs by pass — a judge/consolidation verdict (merge/keep), a scoring
assertion's pass/fail — but the tallying is identical (modal outcome, its share of K, did it
flip, how to mark it). This module is that identical core; each pass contributes only a
callback that turns one run into one token, and the tallying/marker logic lives here once.

A flip is the escalation-ladder signal: a single call that wobbles run-to-run on fixed input
is the noise that would justify spending up on multi-call voting. For a CONTESTED case a flip
is expected (both outcomes defensible), so it reads as ``[contested-split]`` — informational,
not a failure — versus ``[UNSTABLE]`` for a non-contested flip (a real regression signal).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from typing import TypeVar

STABLE = "[stable]"
UNSTABLE = "[UNSTABLE]"
CONTESTED_SPLIT = "[contested-split]"
INCOMPLETE = "[incomplete]"

T = TypeVar("T", bound=Hashable)

# The narration callback every eval pass streams its "thinking" through (the AI Quality tab
# reads it). Optional: a pass called without a sink just runs silently.
DeltaSink = Callable[[str], None] | None


def emit(sink: DeltaSink, text: str) -> None:
    """Write a narration chunk to the thinking sink, if one was given. Shared by every eval
    pass so the ``on_delta`` plumbing (and its None-guard) lives in one place."""
    if sink is not None:
        sink(text)

# Complete measurements share these small, deterministic statistics.


def majority(outcomes: list[T]) -> T:
    """The modal outcome (ties broken by first-seen via Counter)."""
    return Counter(outcomes).most_common(1)[0][0]


def agreement(outcomes: list[T]) -> float:
    """The modal outcome's share of K (1.0 = every run agreed; 0.5 = a two-way coin flip)."""
    return Counter(outcomes).most_common(1)[0][1] / len(outcomes)


def flipped(outcomes: list[T]) -> bool:
    """True if more than one distinct outcome appeared — the cheap headline signal."""
    return len(set(outcomes)) > 1


def marker(outcomes: list[T], *, contested: bool) -> str:
    """How to read the run: stable when every run agreed; a flip is UNSTABLE for a
    non-contested case (a real regression signal) but an expected contested-split for a
    contested one (both outcomes defensible, so the wobble is informational)."""
    if not flipped(outcomes):
        return STABLE
    return CONTESTED_SPLIT if contested else UNSTABLE


# Every consumer uses the same attempt list and completeness rule.


@dataclass(frozen=True)
class RunDetail:
    """One attempt's graded token, explanation, optional display label, and known cost."""

    outcome: str
    detail: str = ""
    error: str | None = None
    display: str | None = None
    cost_usd: float = 0.0


@dataclass(frozen=True)
class StabilityReport:
    """Every attempted repetition, in submission order. Failed attempts remain evidence."""

    runs: list[RunDetail]
    contested: bool = False

    @property
    def complete(self) -> bool:
        return bool(self.runs) and all(run.error is None for run in self.runs)

    @property
    def outcomes(self) -> list[str]:
        return [run.outcome for run in self.runs]

    @property
    def majority(self) -> str | None:
        return majority(self.outcomes) if self.complete else None

    @property
    def agreement(self) -> float | None:
        return agreement(self.outcomes) if self.complete else None

    @property
    def flipped(self) -> bool | None:
        return flipped(self.outcomes) if self.complete else None

    @property
    def marker(self) -> str:
        return marker(self.outcomes, contested=self.contested) if self.complete else INCOMPLETE

    @property
    def tally(self) -> dict[str, int]:
        return dict(Counter(run.outcome if run.error is None else "error" for run in self.runs).most_common())

    @property
    def total_cost_usd(self) -> float:
        return sum(run.cost_usd for run in self.runs)


def emit_stability_summary(report: StabilityReport, on_delta: DeltaSink) -> None:
    measured = f"{report.agreement:.0%} agreement" if report.complete else "measurement incomplete"
    tally = ", ".join(f"{v} x{n}" for v, n in report.tally.items())
    emit(on_delta, f"\n**{report.marker}** {measured} — {tally}\n")


def run_stability(
    run_once: Callable[[], RunDetail], *, k: int, max_workers: int | None = None, contested: bool = False, on_delta: DeltaSink = None,
) -> StabilityReport:
    """Run independent calls concurrently and retain every success/error in original order.

    Cancellation propagates through run_in_pool; it does not produce a completed report.
    The callback owns grading and returns an explicit error for unusable model output.
    """
    from app.ai.analysis import run_in_pool

    if k < 1:
        raise ValueError("Stability requires at least one attempt")
    packed = sorted(run_in_pool(list(range(k)), call=lambda _i: run_once(), max_workers=min(k, max_workers) if max_workers is not None else k), key=lambda item: item[0])
    runs = []
    for index, result, error in packed:
        if error is not None:
            message = f"{type(error).__name__}: {error}"
            result = RunDetail("error", message, error=message)
        if result is None:
            raise RuntimeError("Stability attempt returned no outcome")
        runs.append(result)
        emit(on_delta, f"- run {index + 1}: **{result.display or result.outcome}** — {result.detail}\n")
    return StabilityReport(runs=runs, contested=contested)
