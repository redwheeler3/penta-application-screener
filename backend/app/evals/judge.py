"""The Judge tab: a periodic, blind LABEL AUDIT over every pass's golden cases.

The live evals are the routine regression net — each runs its pass's REAL production prompt on
the golden inputs and grades the fresh output DETERMINISTICALLY against the human label. They
answer "did production still behave?". They cannot answer "is the human label itself sound?" —
for that you need an INDEPENDENT opinion.

That is this module. For every golden case (across all five ``<pass>_golden.json`` files) it
asks a second, independent model to REPRODUCE that pass's output — from a plain-language,
editable brief (the file's ``judge_background``, "what this pass does") + the case's ``given``,
BLIND to the human label — then grades the blind output with the SAME grader the live eval
uses. Two reads come out of it:
  - **Label audit.** A case where the independent judge consistently disagrees with the human
    ``expected`` is a signal the LABEL may be wrong (not the judge). That is the reframed Judge
    tab's value.
  - **Calibration.** Aggregate judge-vs-human agreement (Cohen's κ, failure-recall — see
    ``agreement.py``) says whether the judge is itself trustworthy before you lean on it.

It owns NO case files: it reads every pass's golden file. Blindness (never showing the judge
``metadata.expected``) is the load-bearing rule — a judge shown the answer rubber-stamps it.
Costs real model calls, so it runs from the Evals tab (POST /evals/judge), never in CI.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass

from app.ai.analysis import derive_prompt_version
from app.evals import stability
from app.evals.paths import (
    CONSOLIDATION_GOLDEN_PATH,
    DECOMPOSITION_GOLDEN_PATH,
    GOLDEN_PATH,
    MATCHING_GOLDEN_PATH,
    SCREENING_GOLDEN_PATH,
)
from app.evals.reproduce import Reproduced

DEFAULT_MODEL = "us.anthropic.claude-sonnet-4-6"

# Each pass's golden file + the reproduce adapter that re-runs that pass blind (see
# app/evals/reproduce.py). Kept as lazy imports inside the dispatcher so judge.py has no
# import cycle with the live modules (they don't import judge). One entry per pass.
_PASS_FILES = {
    "scoring": GOLDEN_PATH,
    "consolidation": CONSOLIDATION_GOLDEN_PATH,
    "matching": MATCHING_GOLDEN_PATH,
    "decomposition": DECOMPOSITION_GOLDEN_PATH,
    "screening": SCREENING_GOLDEN_PATH,
}


def prompt_version() -> str:
    """The judge's version, derived from the five editable ``judge_background`` briefs (in a
    fixed pass order) — the ONLY thing that changes what the blind judge is told. Computed per
    call, not at import: the briefs are UI-editable and live on disk, so a run must be stamped
    with the briefs it actually used. Editing and saving any brief changes this hash, which is
    what marks a prior judge run stale (the ``blind-audit`` constant never did). Uses the same
    ``derive_prompt_version`` sha the production passes use, so the two read alike."""
    briefs = [json.loads(path.read_text()).get("judge_background", "") for path in _PASS_FILES.values()]
    return derive_prompt_version(*briefs)


@dataclass(frozen=True)
class JudgeCase:
    """One golden case seen as an audit target: which pass it exercises, the exact ``given`` the
    pass receives, the human ``expected`` label, and the pass's editable ``background`` brief.

    ``contested`` marks a case where BOTH labels are defensible from the given alone — the call
    turns on information neither production nor the judge can see. For a contested case the label
    is a human *leaning*: agreement is neither pass nor fail, disagreement is expected review
    material (never a signal to tune anything), and consistency across repeated runs is the real
    signal. ``label_rationale`` records WHY the human chose ``expected`` — for a reader weighing
    a judge disagreement — but is HARNESS-ONLY: it is never shown to the judge (it often states
    the answer), preserving the blind-audit rule.
    """

    key: str
    pass_name: str
    given: dict
    expected: object  # str verdict (categorical) | dict band (scoring) | dict fires/absent (screening)
    background: str
    contested: bool = False
    label_rationale: str = ""


def load_cases() -> tuple[JudgeCase, ...]:
    """Every golden case across all five passes, as audit targets. Each file carries a
    top-level ``judge_background`` (what the pass does, editable in the UI) attached to each of
    its cases; ``metadata``/``given`` are read straight from the uniform envelope
    (docs/eval-case-schema.md). Order: the pipeline order of _PASS_FILES."""
    cases: list[JudgeCase] = []
    for pass_name, path in _PASS_FILES.items():
        data = json.loads(path.read_text())
        background = data.get("judge_background", "")
        for c in data["cases"]:
            meta = c["metadata"]
            cases.append(
                JudgeCase(
                    key=c["key"],
                    pass_name=pass_name,
                    given=c["given"],
                    expected=meta["expected"],
                    background=background,
                    contested=meta.get("contested", False),
                    label_rationale=meta.get("label_rationale", ""),
                )
            )
    return tuple(cases)


def _reproduce(provider, case: JudgeCase, *, model_id: str) -> Reproduced:
    """Dispatch to the pass's blind reproduce adapter. Lazy imports avoid an import cycle
    (the live modules don't import judge; judge imports them here, at call time)."""
    if case.pass_name == "scoring":
        from app.evals.scoring import judge_reproduce
    elif case.pass_name == "consolidation":
        from app.evals.consolidate import judge_reproduce
    elif case.pass_name == "matching":
        from app.evals.matching import judge_reproduce
    elif case.pass_name == "decomposition":
        from app.evals.decompose import judge_reproduce
    elif case.pass_name == "screening":
        from app.evals.screening import judge_reproduce
    else:  # pragma: no cover - _PASS_FILES is the closed set
        raise ValueError(f"no reproduce adapter for pass {case.pass_name!r}")
    return judge_reproduce(
        provider, given=case.given, expected=case.expected, background=case.background, model=model_id
    )


@dataclass(frozen=True)
class JudgeResult:
    case: JudgeCase
    reproduced: Reproduced
    model_id: str

    @property
    def agrees_with_label(self) -> bool:
        return self.reproduced.agrees

    @property
    def cost_usd(self) -> float:
        return self.reproduced.cost_usd

    @property
    def marker(self) -> str:
        """How to read this result. A contested case can't pass/fail on direction (both labels
        defensible) — it's always review material, so it never shows ``[ok]``."""
        if self.case.contested:
            return "[contested]"
        return "[ok]" if self.reproduced.agrees else "[review]"


def judge_case(provider, case: JudgeCase, *, model_id: str = DEFAULT_MODEL) -> JudgeResult:
    """Reproduce one case's pass output blind and grade it against the human label."""
    return JudgeResult(case=case, reproduced=_reproduce(provider, case, model_id=model_id), model_id=model_id)


@dataclass(frozen=True)
class StabilityReport:
    """The outcome of auditing one case K times on FIXED inputs. The question is not "did the
    judge agree with the label?" (one call answers that) but "does the SAME blind audit, on the
    SAME given, return the SAME verdict every time?" A judge that flip-flops run-to-run on
    identical input is the noise that would make its label-audit unreliable; a steady one is
    trustworthy. Counting/marker delegate to the shared stability core."""

    case: JudgeCase
    labels: list[str]  # the judge's reproduced label token per run
    total_cost_usd: float

    @property
    def counts(self) -> dict[str, int]:
        return dict(Counter(self.labels))

    @property
    def majority(self) -> str:
        return stability.majority(self.labels)

    @property
    def agreement(self) -> float:
        return stability.agreement(self.labels)

    @property
    def flipped(self) -> bool:
        return stability.flipped(self.labels)


def stability_run(provider, case: JudgeCase, *, k: int = 5, model_id: str = DEFAULT_MODEL) -> StabilityReport:
    """Audit ``case`` ``k`` times on identical input and report verdict stability. Every call
    sees the exact same brief + given, so any variation is the judge model's own run-to-run
    noise — the thing stability needs measured. The K calls run concurrently (independent
    fixed-input requests); the tally is order-free."""
    from app.ai.analysis import run_in_pool

    results = [
        r for _i, r, err in run_in_pool(list(range(k)), call=lambda _i: judge_case(provider, case, model_id=model_id), max_workers=k)
        if not err and r is not None
    ]
    return StabilityReport(
        case=case,
        labels=[r.reproduced.judge_label for r in results],
        total_cost_usd=sum(r.cost_usd for r in results),
    )


def format_stability(reports: list[StabilityReport]) -> str:
    lines = ["Blind label-audit stability — K runs per case on fixed inputs", ""]
    for r in reports:
        k = len(r.labels)
        tally = ", ".join(f"{v} x{n}" for v, n in Counter(r.labels).most_common())
        marker = stability.marker(r.labels, contested=r.case.contested)
        lines.extend(
            (
                f"{marker} [{r.case.pass_name}] {r.case.key}",
                f"  {r.agreement:.0%} agreement over {k} runs — {tally}",
                f"  total ${r.total_cost_usd:.4f}",
                "  " + "-" * 60,
            )
        )
    return "\n".join(lines)


def format_report(results: list[JudgeResult]) -> str:
    lines = ["Blind label audit — judge reproduces each pass, compared to the human label", ""]
    for r in results:
        rp = r.reproduced
        lines.extend(
            (
                f"{r.marker} [{r.case.pass_name}] {r.case.key}",
                f"  judge: {rp.judge_label}; label: {rp.human_label}",
                f"  {rp.detail}",
                f"  {r.model_id} / ${rp.cost_usd:.4f}",
                "  " + "-" * 60,
            )
        )
    return "\n".join(lines)
