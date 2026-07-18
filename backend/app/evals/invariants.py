"""Deterministic INVARIANT checks over a recorded Rank — things that are ALWAYS a bug
regardless of pool (a dimension missing a pole, a criterion keyed on a protected class).
Pure and discovered-green: they pass on a blessed fixture because the output is genuinely
good, NOT because the assertion was tuned around the data. These hard-fail pytest.

Only invariants live here. Judgement observations that can't honestly pass/fail (high-r
dimension pairs, carry-forward rate) were once "signals" reported alongside these, but
they duplicate — worse — what the Insights tab (Consolidation, Matching) shows over the
live run, so they were dropped. An invariant you'd have to soften to keep green isn't an
invariant; if one appears, it belongs in the LLM-judge evals, not here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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
