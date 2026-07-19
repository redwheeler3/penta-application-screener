"""Live screening eval: run golden synthetic applicants through the REAL screening prompt+model.

The outlier among the live evals: the other four exercise a dimension-comparison pass over
criteria text, but screening READS AN APPLICANT (normalized fields + essays) and PRODUCES a
list of integrity flags. So a golden case is a synthetic applicant (an exact slice of the
pool), and the grade is per-CATEGORY over the produced flag list:
  - ``fires``  — categories that MUST appear (a real integrity concern, e.g. pet_policy).
  - ``absent`` — categories that must NOT appear (the OVER-REACH guards: flagging a benign
    thing is the costly error, since a flag gates eligibility — e.g. a child's differing
    surname must not raise internal_inconsistency).
A clean applicant has empty ``fires``; any flag at all fails it (a false positive).

The eval calls the REAL ``screening.build_prompt`` (which reads only ``.normalized`` +
``.raw_row``), so a lightweight stand-in carrying those two dicts exercises the exact
production prompt — no reimplementation. Needs ``settings`` for the resolved pet-policy line
the prompt cites. Inputs are FICTIONAL (synthetic pool), so no synthetic-pool guard is
needed. Costs real model calls and is non-deterministic, so it runs from the AI Quality tab,
never as part of pytest/CI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.ai.provider import AIProvider
from app.ai.schemas import ScreeningReport
from app.ai.screening import SYSTEM_PROMPT, build_prompt
from app.evals.paths import SCREENING_GOLDEN_PATH
from app.evals.stability import StabilityReport, run_stability
from app.schemas.settings import AppSettings


@dataclass(frozen=True)
class _StandInApplication:
    """The minimal shape ``screening.build_prompt`` reads: ``normalized`` (form fields) and
    ``raw_row`` (essays, keyed by their form-question column). Lets the eval feed a synthetic
    applicant through the REAL prompt without a DB row."""

    normalized: dict[str, object]
    raw_row: dict[str, object]


@dataclass(frozen=True)
class ScreeningCase:
    key: str
    fields: dict[str, object]  # normalized form fields
    essays: dict[str, object]  # essay text keyed by form-question column
    fires: list[str]  # flag categories that MUST appear
    absent: list[str]  # flag categories that must NOT appear (over-reach guards)
    note: str = ""

    @property
    def _application(self) -> _StandInApplication:
        return _StandInApplication(normalized=self.fields, raw_row=self.essays)


@dataclass(frozen=True)
class CaseResult:
    case: ScreeningCase
    categories: list[str]  # the flag categories the model actually produced
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def load_cases(path: Path = SCREENING_GOLDEN_PATH) -> tuple[ScreeningCase, ...]:
    """Load the golden screening cases, flattening the by-consumer blocks (metadata / given —
    see docs/eval-case-schema.md) into the flat runner case."""
    data = json.loads(path.read_text())
    cases = []
    for c in data["cases"]:
        given, meta, expect = c["given"], c["metadata"], c["metadata"]["expect"]
        cases.append(
            ScreeningCase(
                key=c["key"],
                fields=given["fields"],
                essays=given["essays"],
                fires=expect.get("fires", []),
                absent=expect.get("absent", []),
                note=meta.get("note", ""),
            )
        )
    return tuple(cases)


def _emit(on_delta: object, text: str) -> None:
    if on_delta is not None:
        on_delta(text)  # type: ignore[operator]


def _screen(provider: AIProvider, case: ScreeningCase, *, screening_model: str, settings: AppSettings) -> tuple[list[str], str]:
    """Run the REAL screening prompt once and return ``(categories, detail)``. ``categories``
    are the produced flag categories (in order, duplicates kept — a pass may raise the same
    twice); ``detail`` pairs each flag with its cited summary/evidence (the model's reasoning
    for the flags), so a stability flip is explainable. Shared by the graded run and stability."""
    result = provider.structured_output(
        model_id=screening_model,
        schema=ScreeningReport,
        prompt=build_prompt(case._application, settings),  # type: ignore[arg-type]
        system_prompt=SYSTEM_PROMPT,
    )
    flags = result.output.flags
    categories = [f.category.value for f in flags]
    detail = "; ".join(f"{f.category.value}: {f.summary}" for f in flags) or "no flags"
    return categories, detail


def _check(case: ScreeningCase, categories: list[str]) -> list[str]:
    """Per-category grade: every ``fires`` present, every ``absent`` gone, and for a clean
    case (no fires) NO flag at all. Returns human-readable failures."""
    present = set(categories)
    failures: list[str] = []
    for cat in case.fires:
        if cat not in present:
            failures.append(f"expected flag {cat!r} did not fire")
    for cat in case.absent:
        if cat in present:
            failures.append(f"over-reach: flag {cat!r} fired but should not")
    # A clean case (nothing expected to fire, nothing specifically guarded) tolerates no flags.
    if not case.fires and not case.absent and categories:
        failures.append(f"clean applicant raised flag(s): {', '.join(sorted(present))}")
    return failures


def run_case(
    provider: AIProvider,
    case: ScreeningCase,
    *,
    screening_model: str,
    settings: AppSettings,
    on_delta: object = None,
) -> CaseResult:
    """Run one golden applicant through the REAL screening prompt, then grade the produced
    flag categories against the case's fires/absent expectations."""
    name = case.fields.get("applicant_name", case.key)
    _emit(on_delta, f"Screening **{name}** on `{screening_model}`…\n\n")
    categories, _detail = _screen(provider, case, screening_model=screening_model, settings=settings)
    shown = ", ".join(categories) if categories else "no flags"
    _emit(on_delta, f"Flags produced: **{shown}**\n\n")

    failures = _check(case, categories)
    if failures:
        for f in failures:
            _emit(on_delta, f"❌ {f}\n")
    else:
        _emit(on_delta, "✓ Flags match expectations.\n")
    return CaseResult(case=case, categories=categories, failures=failures)


def stability_run(
    provider: AIProvider,
    case: ScreeningCase,
    *,
    screening_model: str,
    settings: AppSettings,
    k: int = 5,
    on_delta: object = None,
) -> StabilityReport:
    """Run the REAL screening prompt ``k`` times on the case's fixed applicant and report
    whether the FLAG SET held. The outcome token is the sorted set of produced categories, so
    a flip means the flags fired differently run-to-run (the production instability signal).
    Delegates tallying/marker to the shared stability core."""
    name = case.fields.get("applicant_name", case.key)
    _emit(on_delta, f"Screening **{name}** x{k} on `{screening_model}`…\n\n")
    runs = {"i": 0}

    def run_once() -> tuple[str, str]:
        cats, detail = _screen(provider, case, screening_model=screening_model, settings=settings)
        runs["i"] += 1
        token = ", ".join(sorted(set(cats))) or "none"
        _emit(on_delta, f"- run {runs['i']}: **{token}**\n")
        return token, detail

    # A screening golden case has no "contested" notion; a flag-set flip is always a real signal.
    report = run_stability(run_once, k=k, contested=False)
    tally = ", ".join(f"[{v}] x{n}" for v, n in report.tally.items())
    _emit(on_delta, f"\n**{report.marker}** {report.agreement:.0%} agreement — {tally}\n")
    return report
