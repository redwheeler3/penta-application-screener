"""Live screening eval: run golden synthetic applicants through the REAL screening prompt+model.

The outlier among the live evals: the other four exercise a dimension-comparison pass over
criteria text, but screening READS AN APPLICANT (normalized fields + essays) and PRODUCES both
a list of integrity flags AND an extracted pet inventory. So a golden case is a synthetic
applicant (an exact slice of the pool), and the grade has two parts:
  - flags, per-CATEGORY: ``fires`` = categories that MUST appear (a real integrity concern,
    e.g. fake_contact); ``absent`` = categories that must NOT (the OVER-REACH guards: flagging
    a benign thing is the costly error, since a flag gates eligibility — e.g. a child's
    differing surname must not raise internal_inconsistency).
  - pets, when ``expected_pets`` is set (M15 1e): the EXTRACTED inventory must match (dogs/cats
    exact; each other-pet noun present). Pets are no longer a flag — the model extracts neutral
    facts and a deterministic per-member hard filter judges the limits downstream.
A clean applicant (no fires/absent, no pets expectation) produces zero flags; any flag fails it.

The eval calls the REAL ``screening.build_prompt`` (which reads only ``.normalized`` +
``.raw_row``), so a lightweight stand-in carrying those two dicts exercises the exact
production prompt — no reimplementation. Inputs are FICTIONAL (synthetic pool), so no
synthetic-pool guard is needed. Costs real model calls and is non-deterministic, so it runs
from the AI Quality tab, never as part of pytest/CI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.ai.provider import AIProvider
from app.ai.schemas import PetFacts, ScreeningReport
from app.ai.screening import SYSTEM_PROMPT, build_prompt
from app.evals.paths import SCREENING_GOLDEN_PATH
from app.evals.stability import DeltaSink, StabilityReport, emit, run_stability


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
    # Each entry: a category string (must fire) OR a list of categories (at least one must
    # fire — for a concern with more than one defensible bucket).
    fires: list[str | list[str]]
    absent: list[str]  # flag categories that must NOT appear (over-reach guards)
    # Expected EXTRACTED pet facts (M15 1e), or None to skip pet grading. When set, e.g.
    # {"dogs": 2, "cats": 1, "other_pets": ["rabbit"]}, the case grades the model's neutral
    # pet extraction — dogs/cats counted exactly, each expected other-pet noun present — NOT
    # any policy verdict (pets are no longer a flag; per-member limits are judged downstream).
    expected_pets: dict[str, object] | None = None
    note: str = ""

    @property
    def _application(self) -> _StandInApplication:
        return _StandInApplication(normalized=self.fields, raw_row=self.essays)


@dataclass(frozen=True)
class CaseResult:
    case: ScreeningCase
    categories: list[str]  # the flag categories the model actually produced
    reason: str = ""  # the model's reasoning + per-flag evidence (explains a fire or a miss)
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
        given, meta, expected = c["given"], c["metadata"], c["metadata"]["expected"]
        cases.append(
            ScreeningCase(
                key=c["key"],
                fields=given["fields"],
                essays=given["essays"],
                fires=expected.get("fires", []),
                absent=expected.get("absent", []),
                expected_pets=expected.get("pets"),
                note=meta.get("note", ""),
            )
        )
    return tuple(cases)



def _screen(
    provider: AIProvider, case: ScreeningCase, *, screening_model: str
) -> tuple[list[str], PetFacts, str]:
    """Run the REAL screening prompt once and return ``(categories, pets, detail)``.
    ``categories`` are the produced flag categories (in order, duplicates kept — a pass may
    raise the same twice); ``pets`` is the extracted neutral inventory the case's pet-fact
    grade checks (M15 1e); ``detail`` is the per-flag cited evidence + the extracted pets +
    the model's own free-form reasoning (``result.narrative``) when it emits any — the only
    place the rationale for a flag it chose NOT to raise could appear, so a MISS is
    explainable, not just a flip. Shared by the graded run and stability."""
    result = provider.structured_output(
        model_id=screening_model,
        schema=ScreeningReport,
        prompt=build_prompt(case._application),  # type: ignore[arg-type]
        system_prompt=SYSTEM_PROMPT,
    )
    flags = result.output.flags
    categories = [f.category.value for f in flags]
    pets = result.output.pets
    per_flag = "; ".join(f"{f.category.value}: {f.summary}" for f in flags) or "no flags"
    pet_line = f"pets: {pets.dogs} dog(s), {pets.cats} cat(s), other={pets.other_pets or 'none'}"
    narrative = (result.narrative or "").strip()
    # Lead with the model's reasoning (if any), then the per-flag evidence + extracted pets.
    # A miss has no per-flag line by nature, so the narrative is where "why I didn't flag X"
    # would live.
    body = f"{per_flag}\n{pet_line}"
    detail = f"{narrative}\n\n{body}" if narrative else body
    return categories, pets, detail


def _check(case: ScreeningCase, categories: list[str], pets: PetFacts | None = None) -> list[str]:
    """Per-category grade: every ``fires`` requirement met, every ``absent`` gone, and for a
    clean case (no fires) NO flag at all — plus, when the case sets ``expected_pets``, the
    extracted pet inventory matches (M15 1e). Returns human-readable failures.

    A ``fires`` entry is either a category string (that exact category must fire) OR a list of
    categories meaning "at least ONE of these must fire" — for a concern the model may
    reasonably file under more than one bucket. Pet grading is separate from flags: a pet case
    checks the EXTRACTED counts (dogs/cats exact, each expected other-pet noun present), never
    a flag, since pets are no longer flagged (the per-member limit is judged downstream)."""
    present = set(categories)
    failures: list[str] = []
    for req in case.fires:
        if isinstance(req, list):
            if not present.intersection(req):
                failures.append(f"expected one of {req!r} to fire; none did")
        elif req not in present:
            failures.append(f"expected flag {req!r} did not fire")
    for cat in case.absent:
        if cat in present:
            failures.append(f"over-reach: flag {cat!r} fired but should not")
    # A clean case (nothing expected to fire, nothing specifically guarded, no pet
    # expectation) tolerates no flags. A pet-extraction case (expected_pets set) is NOT
    # "clean" in this sense — it has a positive expectation, and any incidental flag is
    # ungraded unless explicitly listed in ``absent`` — so it's exempt from this rule.
    if not case.fires and not case.absent and case.expected_pets is None and categories:
        failures.append(f"clean applicant raised flag(s): {', '.join(sorted(present))}")
    failures.extend(_check_pets(case, pets))
    return failures


def _check_pets(case: ScreeningCase, pets: PetFacts | None) -> list[str]:
    """Grade the extracted pet inventory against ``expected_pets`` (skipped when the case sets
    none, or in the judge/probe path that has no pets). dogs/cats must match exactly; each
    expected ``other_pets`` noun must appear as a substring of some extracted other-pet (so
    'rabbit' matches an extracted 'pet rabbit'), case-insensitively."""
    if case.expected_pets is None or pets is None:
        return []
    failures: list[str] = []
    for kind in ("dogs", "cats"):
        want = case.expected_pets.get(kind, 0)
        got = getattr(pets, kind)
        if got != want:
            failures.append(f"expected {want} {kind}, extracted {got}")
    extracted = [o.lower() for o in pets.other_pets]
    for want in case.expected_pets.get("other_pets", []):
        if not any(str(want).lower() in got for got in extracted):
            failures.append(f"expected other pet {want!r} not extracted (got {pets.other_pets or 'none'})")
    return failures


def judge_reproduce(provider: AIProvider, *, given: dict, expected: dict, background: str, model: str):
    """Blind-judge adapter (see app/evals/reproduce.py): an INDEPENDENT model re-screens the
    applicant from the editable ``background`` (which carries the policy context the production
    prompt gets from settings) + the given fields/essays — never the human label — then we grade
    its flag categories with the SAME fires/absent check the live eval uses. A screening case
    HAS a defect notion: a missed required flag or an over-reach is the failure, so it feeds
    failure-recall (human_is_problem = the case guards something; judge_is_problem = it failed)."""
    from app.ai.pricing import cost_usd
    from app.evals.reproduce import Reproduced, build_judge_prompt

    prompt = build_judge_prompt(
        given,
        "Review the applicant's fields and essays for integrity concerns. Return a list of "
        "flags; each flag has a category, one-sentence summary, and cited evidence. "
        "Flag only genuine concerns — a benign detail must not be flagged.",
    )
    result = provider.structured_output(model_id=model, schema=ScreeningReport, prompt=prompt, system_prompt=background)
    categories = [f.category.value for f in result.output.flags]
    probe = ScreeningCase(
        key="judge", fields={}, essays={},
        fires=list(expected.get("fires", [])), absent=list(expected.get("absent", [])),
    )
    failures = _check(probe, categories)
    cost = cost_usd(result.model_id, result.usage)
    shown = ", ".join(categories) or "no flags"
    detail = "; ".join(f"{f.category.value}: {f.summary}" for f in result.output.flags) or "no flags"
    human_is_problem = bool(probe.fires or probe.absent)  # the case guards a real defect
    return Reproduced(shown, expected_str(expected), not failures, human_is_problem, bool(failures), detail, cost)


def fire_label(req: object) -> str:
    """Display token for one ``fires`` requirement: a category, or 'a | b' for an any-of group."""
    return " | ".join(req) if isinstance(req, list) else str(req)


def expected_str(expected: dict) -> str:
    """Compact human-label token for a screening expectation, e.g. 'fires: fake_contact' or
    'pets: 2 dogs, 1 cat'."""
    parts = []
    if expected.get("fires"):
        parts.append("fires: " + ", ".join(fire_label(r) for r in expected["fires"]))
    if expected.get("absent"):
        parts.append("absent: " + ", ".join(expected["absent"]))
    pets = expected.get("pets")
    if pets is not None:
        pet_bits = [f"{pets.get('dogs', 0)} dogs", f"{pets.get('cats', 0)} cats"]
        if pets.get("other_pets"):
            pet_bits.append("other: " + ", ".join(pets["other_pets"]))
        parts.append("pets: " + ", ".join(pet_bits))
    return " · ".join(parts) or "clean"


def run_case(
    provider: AIProvider,
    case: ScreeningCase,
    *,
    screening_model: str,
    on_delta: DeltaSink = None,
) -> CaseResult:
    """Run one golden applicant through the REAL screening prompt, then grade the produced
    flag categories (and extracted pet facts) against the case's expectations."""
    name = case.fields.get("applicant_name", case.key)
    emit(on_delta, f"Screening **{name}** on `{screening_model}`…\n\n")
    categories, pets, detail = _screen(provider, case, screening_model=screening_model)
    shown = ", ".join(categories) if categories else "no flags"
    emit(on_delta, f"Flags produced: **{shown}**\n\n")
    # Surface the model's reasoning + per-flag evidence so a miss (an expected flag that didn't
    # fire) is explainable, not just visible as a red ❌ with no "why".
    emit(on_delta, f"_{detail}_\n\n")

    failures = _check(case, categories, pets)
    if failures:
        for f in failures:
            emit(on_delta, f"❌ {f}\n")
    else:
        emit(on_delta, "✓ Flags match expectations.\n")
    return CaseResult(case=case, categories=categories, reason=detail, failures=failures)


def stability_run(
    provider: AIProvider,
    case: ScreeningCase,
    *,
    screening_model: str,
    k: int = 5,
    on_delta: DeltaSink = None,
) -> StabilityReport:
    """Run the REAL screening prompt ``k`` times on the case's fixed applicant and report
    whether the case's GRADE held run-to-run. The outcome token is pass/fail against the case's
    own fires/absent (+ pet-fact) check (NOT the raw flag set): a run that satisfies the case —
    including via an "at least one of" group where a concern has more than one defensible
    bucket — is a pass, so a flip only registers when the graded verdict actually wobbled, not
    when two equally-acceptable categories differ. (Same pass/fail tokening scoring stability
    uses.) The
    produced flag set + reasoning ride in the per-run detail so a real flip is still explainable.
    Delegates tallying/marker to the shared stability core."""
    name = case.fields.get("applicant_name", case.key)
    emit(on_delta, f"Screening **{name}** x{k} on `{screening_model}`…\n\n")

    def run_once() -> tuple[str, str]:
        cats, pets, reasoning = _screen(provider, case, screening_model=screening_model)
        outcome = "fail" if _check(case, cats, pets) else "pass"
        shown = ", ".join(cats) or "none"
        return outcome, f"flags: {shown} — {reasoning}"

    # A screening golden case has no "contested" notion; a graded pass/fail flip is a real signal.
    report = run_stability(run_once, k=k, contested=False, on_delta=on_delta)
    tally = ", ".join(f"[{v}] x{n}" for v, n in report.tally.items())
    emit(on_delta, f"\n**{report.marker}** {report.agreement:.0%} agreement — {tally}\n")
    return report
