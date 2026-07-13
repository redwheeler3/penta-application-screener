"""Eval checks over a recorded Rank, split into two kinds by whether they can honestly
pass/fail deterministically:

  INVARIANTS — things that are ALWAYS a bug regardless of pool. Pure, deterministic, and
  discovered-green (they pass on a blessed fixture because the output is genuinely good,
  NOT because the assertion was tuned around the data). These hard-fail pytest.

  SIGNALS — judgement calls a human must make (is a high-correlation pair an escaped
  duplicate or a legitimate confound? is a carry-forward rate healthy?). A model's output
  varies here for real reasons, so these are REPORTED and watched, never hard-failed —
  forcing them green would just teach us to weaken the check.

The line matters: an invariant you'd have to soften to keep green isn't an invariant, it's
a signal. Overlap started life mis-filed as an invariant and moved here for exactly that
reason. The score-vector math is imported from production so "correlated" has one meaning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.ai.score_vectors import MIN_SUPPORT, pearson
from app.evals.fixture import EvalFixture

# --- invariants ---------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    """An INVARIANT breach — a real bug. ``check`` groups by property, ``subject`` is the
    offending dimension key, ``detail`` the human-readable why."""

    check: str
    subject: str
    detail: str


# Terms that must never appear in a criterion's key/name/definition/poles: a housing
# screener may not score on a protected class. Matched whole-word (\b…\b), case-
# insensitive. Deliberately ONLY unambiguous terms: a string check can't tell "faith" the
# religion from "accept on faith", "race" the class from "charity races", or "age" the
# class from "child age profile" — those need semantics, so they're excluded rather than
# flagged as noise (a check that cries wolf trains you to ignore it). This is a coarse
# net for the blatant case; the human review is the real backstop.
PROTECTED_TERMS = [
    "racial", "ethnicity", "religion", "religious", "nationality", "immigration",
    "citizenship", "sexual orientation", "disability", "disabled", "marital status",
]


def _key(d: dict) -> str:
    return d.get("key", "?")


def check_poles_present(fixture: EvalFixture) -> list[Violation]:
    """Every dimension defines BOTH poles and they differ. A 0..1 score is meaningless
    without a stated high and low end — this is the mechanical form of the household-size
    'direction is policy-dependent' punt we fixed. Empty or duplicated pole → breach."""
    out: list[Violation] = []
    for d in fixture.dimensions:
        hi, lo = (d.get("high_end") or "").strip(), (d.get("low_end") or "").strip()
        if not hi:
            out.append(Violation("poles_present", _key(d), "high_end is empty"))
        if not lo:
            out.append(Violation("poles_present", _key(d), "low_end is empty"))
        if hi and lo and hi.lower() == lo.lower():
            out.append(Violation("poles_present", _key(d), "high_end == low_end (no direction)"))
    return out


def check_no_protected_attributes(fixture: EvalFixture) -> list[Violation]:
    """No criterion keys on a protected class. Scans key/name/definition/poles."""
    out: list[Violation] = []
    for d in fixture.dimensions:
        text = " ".join(
            str(d.get(f, "")) for f in ("key", "name", "definition", "high_end", "low_end")
        ).lower()
        for term in PROTECTED_TERMS:
            if re.search(rf"\b{re.escape(term)}\b", text):
                out.append(Violation("no_protected_attributes", _key(d), f"mentions '{term}'"))
    return out


# Invariants, in report order. These gate CI. (One-concept is NOT here: "X & Y" in a name
# is too often a single conventional concept — "Health & Safety", "Trade & Maintenance" —
# for a string check to flag reliably; it's a semantic judgement, left to the discovery
# prompt's own guard and, later, an LLM-judge eval.)
INVARIANTS = [check_poles_present, check_no_protected_attributes]


def run_invariants(fixture: EvalFixture) -> list[Violation]:
    out: list[Violation] = []
    for check in INVARIANTS:
        out.extend(check(fixture))
    return out


# --- signals ------------------------------------------------------------------------


@dataclass(frozen=True)
class Signal:
    """A judgement-worthy observation — NOT a pass/fail. ``note`` says what a human should
    weigh; ``concern`` flags the ones most worth a look (still not a failure)."""

    check: str
    note: str
    concern: bool = False


def _aligned(a: list[float | None], b: list[float | None]) -> tuple[list[float], list[float]]:
    """The two vectors over the columns BOTH filled (drop a None in either)."""
    xs, ys = [], []
    for x, y in zip(a, b, strict=True):
        if x is not None and y is not None:
            xs.append(x)
            ys.append(y)
    return xs, ys


def signal_overlap(fixture: EvalFixture, threshold: float = 0.85) -> list[Signal]:
    """Report every pair of THIS run's dimensions whose score vectors correlate at/above
    ``threshold``. Not a failure: a high-r pair may be an escaped duplicate OR a genuine
    confound the committee wants kept apart — only a human knows which, so we surface it
    for review rather than assert on it. (This is the check that was mis-filed as an
    invariant; it can't honestly pass/fail without a human, so it's a signal.)"""
    keys = [d["key"] for d in fixture.dimensions if d.get("key") in fixture.score_vectors]
    pairs: list[tuple[float, str, str]] = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            xs, ys = _aligned(fixture.score_vectors[a], fixture.score_vectors[b])
            if len(xs) < MIN_SUPPORT:
                continue
            r = pearson(xs, ys)
            if r is not None and r >= threshold:
                pairs.append((r, a, b))
    pairs.sort(reverse=True)
    return [
        Signal("overlap", f"r={r:.2f}  {a} ~ {b}", concern=True) for r, a, b in pairs
    ] or [Signal("overlap", f"no pair correlates ≥ {threshold}")]


def signal_match_rate(fixture: EvalFixture) -> list[Signal]:
    """Report the carry-forward rate (how many of this run's dimensions matched a prior
    one). Not a failure: a high rate is expected once the set stabilises. Flag only the
    degenerate ends — 0% (nothing carried, a possible match-pass miss) or 100% (nothing
    new, worth confirming discovery still explored) — as worth a look."""
    match = fixture.match
    if not match:
        return [Signal("match_rate", "first run — no prior dimensions to match against")]
    raw = match.get("raw_discovery_dimensions") or []
    mapping = match.get("new_to_old") or {}
    total = len(raw)
    if total == 0:
        return [Signal("match_rate", "no discovery dimensions recorded")]
    matched = sum(1 for d in raw if d.get("key") in mapping)
    rate = matched / total
    degenerate = matched == 0 or matched == total
    return [
        Signal(
            "match_rate",
            f"{matched}/{total} carried forward ({rate:.0%})",
            concern=degenerate,
        )
    ]


SIGNALS = [signal_overlap, signal_match_rate]


def run_signals(fixture: EvalFixture) -> list[Signal]:
    out: list[Signal] = []
    for sig in SIGNALS:
        out.extend(sig(fixture))
    return out
