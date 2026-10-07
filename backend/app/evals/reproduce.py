"""Blind-judge scaffolding shared by the per-pass reproduce adapters.

The Judge tab re-produces each pass's OWN output from a plain-language, editable brief (the
golden file's ``judge_background``) plus the case's ``given`` — blind to the human label — then
grades that output with the SAME grader the live eval uses. Each pass owns a ``judge_reproduce``
adapter co-located in its pass module (so the pass's output schema and label
derivation live in one place); ``judge.py`` dispatches to them by ``pass``. They all return the
neutral ``Reproduced`` shape below so judge.py stays pass-agnostic.

This separate module lets live modules import the shape/helper without a cycle because `judge.py`
imports the live modules. The judge is INDEPENDENT: it sees the background (what the
pass does) + the given data, and a minimal "produce your answer" instruction — NOT the pass's
elaborate production instructions, which would make it a re-run rather than a second opinion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.ai.prompt_fragments import INJECTION_GUARD_NOTE


@dataclass(frozen=True)
class Reproduced:
    """One blind output, its human expectation, grade, explanation, and known cost."""

    judge_label: str
    human_label: str
    agrees: bool
    detail: str
    cost_usd: float
    error: str | None = None


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
