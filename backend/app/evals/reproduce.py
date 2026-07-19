"""Blind-judge scaffolding shared by the per-pass reproduce adapters.

The Judge tab re-produces each pass's OWN output from a plain-language, editable brief (the
golden file's ``judge_background``) plus the case's ``given`` — blind to the human label — then
grades that output with the SAME grader the live eval uses. Each pass owns a ``judge_reproduce``
adapter co-located in its ``live_*.py`` module (so the pass's output schema and label
derivation live in one place); ``judge.py`` dispatches to them by ``pass``. They all return the
neutral ``Reproduced`` shape below so judge.py stays pass-agnostic.

Kept here — not in judge.py — so a live module can import the shape/helper without a cycle
(judge.py imports the live modules). The judge is INDEPENDENT: it sees the background (what the
pass does) + the given data, and a minimal "produce your answer" instruction — NOT the pass's
elaborate production instructions, which would make it a re-run rather than a second opinion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.ai.prompt_fragments import INJECTION_GUARD_NOTE


@dataclass(frozen=True)
class Reproduced:
    """One pass reproduced blind by the judge, graded against the human label.

    ``judge_label``/``human_label`` are compact display tokens (the pass's verdict, or a band
    pass/fail token) for the run table and κ. ``agrees`` is the audit signal: did the blind
    output satisfy the human ``expected``? ``*_is_problem`` drive failure-recall — a pass with
    no single "defect" side (merge/keep, scoring band) sets both False and is excluded there.
    ``detail`` is the judge's reproduced output + reasoning, narrated so a disagreement explains
    itself.
    """

    judge_label: str
    human_label: str
    agrees: bool
    human_is_problem: bool
    judge_is_problem: bool
    detail: str
    cost_usd: float


def build_judge_prompt(given: dict, instruction: str) -> str:
    """The independent judge's USER prompt: a minimal instruction + the case's given data in a
    semantic tag. The ``judge_background`` rides as the SYSTEM prompt (what the pass does); this
    only tells the judge what to PRODUCE, so it forms its own view rather than re-running the
    production instructions. Guarded like every prompt — ``given`` traces to member free text."""
    return (
        f"{instruction}\n\n"
        f"<case>\n{json.dumps(given, indent=2, default=str)}\n</case>\n\n"
        f"Guardrail: {INJECTION_GUARD_NOTE}"
    )
