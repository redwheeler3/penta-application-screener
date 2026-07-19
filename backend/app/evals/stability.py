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

T = TypeVar("T", bound=Hashable)

# --- the math, over any hashable outcome token (string verdict, typed enum, bool) -----------
# Free functions so a pass with its own richer report (the judge: typed verdicts + cost) can
# delegate the counting without adopting the string-native dataclass below.


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


# --- string-native convenience report (consolidation, scoring) ------------------------------


@dataclass(frozen=True)
class RunDetail:
    """One run within a stability check: its outcome token + the model's own reasoning for it
    (the narrative, or a per-outcome reason). Kept per-run so a FLIP explains itself — the run
    that disagreed shows what the model said that time, not just that it differed."""

    outcome: str
    detail: str = ""


@dataclass(frozen=True)
class StabilityReport:
    """K runs of one case on fixed input, plus whether the case is contested (which decides how
    a flip is read). Each run keeps its outcome AND the model's reasoning (``runs``), so a flip
    is legible; the read-outs delegate to the free functions above. A pass builds this from its
    own ``run_once`` and reads ``marker``/``agreement`` uniformly. (The judge keeps its own
    typed report and delegates to the same functions.)"""

    runs: list[RunDetail]
    contested: bool = False

    @property
    def outcomes(self) -> list[str]:
        return [r.outcome for r in self.runs]

    @property
    def majority(self) -> str:
        return majority(self.outcomes)

    @property
    def agreement(self) -> float:
        return agreement(self.outcomes)

    @property
    def flipped(self) -> bool:
        return flipped(self.outcomes)

    @property
    def marker(self) -> str:
        return marker(self.outcomes, contested=self.contested)

    @property
    def tally(self) -> dict[str, int]:
        """Outcome token -> count, most common first."""
        return dict(Counter(self.outcomes).most_common())


def run_stability(
    run_once: Callable[[], tuple[str, str]], *, k: int, contested: bool = False
) -> StabilityReport:
    """Call ``run_once`` ``k`` times (each a fresh model call on the SAME fixed input) and
    collect the results into a StabilityReport. The caller's ``run_once`` is the only
    pass-specific part — it makes one production call and returns ``(outcome_token, detail)``,
    where ``detail`` is the model's reasoning for that run (so a flip is explainable)."""
    runs = [RunDetail(*run_once()) for _ in range(k)]
    return StabilityReport(runs=runs, contested=contested)
