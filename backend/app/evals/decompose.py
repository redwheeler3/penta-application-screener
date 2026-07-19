"""Live decomposition eval: run golden discovery reports through the REAL decomposition
prompt+model.

Like the other live evals, this closes the gap the judge/invariant layers can't: they grade
recorded artifacts and are blind to a prompt/model regression because the model never runs.
It freezes the INPUT (a set of dimension descriptors, each as its own discovery report, mined
from real runs), runs them through the exact production ``dimension_decompose`` prompt on the
configured decompose model, and grades the FRESH settled set.

Grader — categorical, so deterministic exact-match (see docs/ai-evals.md "Grader
architecture"). Decomposition is an N-way GROUPER, not a pairwise verdict, so the verdict is
DERIVED from the settled set: MERGE = every input descriptor's key landed in ONE settled
axis's ``source_keys`` (the carvings were folded into one concept); KEEP = they spread across
≥2 settled axes (kept distinct). The case carries the human ``expected``, so the check is
``derived == expected``. No judge tier — the settled grouping IS the check.

The two failure modes decomposition guards are OVER-fold (collapse genuinely distinct axes →
lose a real lever) and UNDER-fold (keep N carvings of one concept → weight it N times), so the
fixture carries one clean MERGE (three carvings of one concept) and one clean KEEP (capacity
vs. intent). Inputs are dimension definitions (criteria text, not applicant PII), so no
synthetic-pool guard is needed. Costs a real model call and is non-deterministic, so it runs
from the AI Quality tab, never as part of pytest/CI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.ai.dimension_decompose import SYSTEM_PROMPT, build_prompt
from app.ai.provider import AIProvider
from app.ai.schemas import DecompositionReport, PoolDimension, PoolDimensionReport
from app.evals.paths import DECOMPOSITION_GOLDEN_PATH
from app.evals.stability import StabilityReport, run_stability

MERGE, KEEP = "merge", "keep"


def _descriptor_to_dim(d: dict[str, object]) -> PoolDimension:
    """A golden descriptor → a PoolDimension. Decomposition serializes key/name/definition +
    poles + committee flag; poles are filled empty (unused by these fold/keep cases)."""
    return PoolDimension(
        key=str(d["key"]), name=str(d.get("name", "")), definition=str(d["definition"]),
        high_end="", low_end="", why_it_differentiates="",
    )


@dataclass(frozen=True)
class DecompositionCase:
    key: str
    reports: list[list[dict[str, object]]]  # K discovery reports, each a list of descriptors
    expected: str  # "merge" | "keep" — the human label
    contested: bool = False
    note: str = ""

    @property
    def _source_keys(self) -> set[str]:
        return {str(d["key"]) for report in self.reports for d in report}


@dataclass(frozen=True)
class CaseResult:
    case: DecompositionCase
    verdict: str  # "merge" | "keep" — derived from the settled set
    reason: str  # narration of how the source keys settled
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        if self.failures:
            return False
        return self.verdict == self.case.expected


def load_cases(path: Path = DECOMPOSITION_GOLDEN_PATH) -> tuple[DecompositionCase, ...]:
    """Load the golden decomposition cases, flattening the by-consumer blocks (metadata /
    given — see docs/eval-case-schema.md) into the flat runner case."""
    data = json.loads(path.read_text())
    cases = []
    for c in data["cases"]:
        meta = c["metadata"]
        cases.append(
            DecompositionCase(
                key=c["key"],
                reports=c["given"]["reports"],
                expected=meta["expected"],
                contested=meta.get("contested", False),
                note=meta.get("note", ""),
            )
        )
    return tuple(cases)


def _emit(on_delta: object, text: str) -> None:
    if on_delta is not None:
        on_delta(text)  # type: ignore[operator]


def _decompose_verdict(provider: AIProvider, case: DecompositionCase, *, decompose_model: str) -> tuple[str, str]:
    """Run the REAL decomposition prompt once and derive ``(verdict, reason)``. MERGE = all the
    case's source keys landed in ONE settled axis; KEEP = they spread across ≥2. Shared by the
    single graded run and the K-run stability check."""
    reports = [
        PoolDimensionReport(dimensions=[_descriptor_to_dim(d) for d in report])
        for report in case.reports
    ]
    result = provider.structured_output(
        model_id=decompose_model,
        schema=DecompositionReport,
        prompt=build_prompt(reports),
        system_prompt=SYSTEM_PROMPT,
    )
    src = case._source_keys
    # Which settled axes absorbed any of our source keys?
    landing = [a for a in result.output.dimensions if src & set(a.source_keys)]
    n = len(landing)
    # Detail = the model's own per-axis decision reasoning (why it folded/kept), not just the
    # derived count — that's the "why" a flip needs. Fall back to the narrative, then a summary.
    decisions = " | ".join(a.decision for a in landing if a.decision)
    narrative = (result.narrative or "").strip()
    if n == 1:
        return MERGE, decisions or narrative or f"all {len(src)} carvings folded into one axis {landing[0].key}"
    if n == 0:
        # No settled axis lists our keys — shouldn't happen (coverage invariant), treat as no-verdict.
        return "?", "no settled axis referenced the input keys"
    names = ", ".join(a.key for a in landing)
    return KEEP, decisions or narrative or f"kept across {n} distinct axes ({names})"


def judge_reproduce(provider: AIProvider, *, given: dict, expected: str, background: str, model: str):
    """Blind-judge adapter (see app/evals/reproduce.py): an INDEPENDENT model decides whether the
    discovery carvings describe ONE concept (merge) or ≥2 distinct axes (keep) from the editable
    ``background`` + the definitions (never the human label), then we exact-match its verdict
    against ``expected``. merge/keep has no single 'problem' side, so no failure-recall
    contribution."""
    from app.ai.pricing import cost_usd
    from app.ai.schemas import JudgeReport
    from app.evals.reproduce import Reproduced, build_judge_prompt

    prompt = build_judge_prompt(
        given,
        "These definitions were each discovered separately, then folded into one settled axis. "
        "Decide 'merge' (they are one concept, the fold is correct) or 'keep' (at least one is a "
        "genuinely distinct axis), with a reason.",
    )
    result = provider.structured_output(model_id=model, schema=JudgeReport, prompt=prompt, system_prompt=background)
    verdict = result.output.verdict.value
    cost = cost_usd(result.model_id, result.usage)
    return Reproduced(verdict, expected, verdict == expected, False, False, result.output.reason, cost)


def run_case(
    provider: AIProvider,
    case: DecompositionCase,
    *,
    decompose_model: str,
    on_delta: object = None,
) -> CaseResult:
    """Run one golden set through the REAL decompose prompt and grade merge/keep (derived from
    the settled set) against the label by exact match."""
    _emit(on_delta, f"Decomposing {len(case._source_keys)} carvings on `{decompose_model}`…\n\n")
    verdict, reason = _decompose_verdict(provider, case, decompose_model=decompose_model)
    if verdict == "?":
        _emit(on_delta, f"⚠️ {reason}\n")
        return CaseResult(case=case, verdict="?", reason=reason, failures=["no verdict derivable from the settled set"])
    _emit(on_delta, f"**Verdict: {verdict}** (expected {case.expected})\n\n- _{reason}_\n\n")

    failures: list[str] = []
    if case.contested:
        _emit(on_delta, "◐ Contested case — both verdicts defensible; not counted pass/fail.\n")
    elif verdict != case.expected:
        failures.append(f"verdict {verdict!r} != expected {case.expected!r}")
        _emit(on_delta, f"❌ Verdict disagrees with the label ({verdict} vs {case.expected}).\n")
    else:
        _emit(on_delta, "✓ Verdict matches the label.\n")

    return CaseResult(case=case, verdict=verdict, reason=reason, failures=failures)


def stability_run(
    provider: AIProvider,
    case: DecompositionCase,
    *,
    decompose_model: str,
    k: int = 5,
    on_delta: object = None,
) -> StabilityReport:
    """Run the REAL decompose prompt ``k`` times on the case's fixed carvings and report
    fold/keep stability. Delegates tallying/marker to the shared stability core; the only
    pass-specific part is one decompose call producing one merge/keep token."""
    _emit(on_delta, f"Decomposing {len(case._source_keys)} carvings x{k} on `{decompose_model}`…\n\n")
    runs = {"i": 0}

    def run_once() -> tuple[str, str]:
        verdict, reason = _decompose_verdict(provider, case, decompose_model=decompose_model)
        runs["i"] += 1
        _emit(on_delta, f"- run {runs['i']}: **{verdict}** — {reason}\n")
        return verdict, reason

    report = run_stability(run_once, k=k, contested=case.contested)
    tally = ", ".join(f"{v} x{n}" for v, n in report.tally.items())
    _emit(on_delta, f"\n**{report.marker}** {report.agreement:.0%} agreement — {tally}\n")
    return report
