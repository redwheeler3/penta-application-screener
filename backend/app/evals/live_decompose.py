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
    # Optional judge question (PRESENCE IS THE SWITCH — docs/eval-case-schema.md).
    judge: str = ""

    @property
    def _source_keys(self) -> set[str]:
        return {str(d["key"]) for report in self.reports for d in report}


@dataclass(frozen=True)
class CaseResult:
    case: DecompositionCase
    verdict: str  # "merge" | "keep" — derived from the settled set
    reason: str  # narration of how the source keys settled
    failures: list[str] = field(default_factory=list)
    judge_verdict: str | None = None

    @property
    def passed(self) -> bool:
        if self.failures:
            return False
        return self.verdict == self.case.expected


def load_cases(path: Path = DECOMPOSITION_GOLDEN_PATH) -> tuple[DecompositionCase, ...]:
    """Load the golden decomposition cases, flattening the by-consumer blocks (metadata /
    given / judge — see docs/eval-case-schema.md) into the flat runner case."""
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
                judge=(c.get("judge") or {}).get("question", ""),
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
    if n == 1:
        return MERGE, f"all {len(src)} carvings folded into one axis `{landing[0].key}`"
    if n == 0:
        # No settled axis lists our keys — shouldn't happen (coverage invariant), treat as no-verdict.
        return "?", "no settled axis referenced the input keys"
    names = ", ".join(f"`{a.key}`" for a in landing)
    return KEEP, f"kept across {n} distinct axes ({names})"


def run_case(
    provider: AIProvider,
    case: DecompositionCase,
    *,
    decompose_model: str,
    judge_model: str | None = None,
    on_delta: object = None,
) -> CaseResult:
    """Run one golden set through the REAL decompose prompt, grade merge/keep (derived from the
    settled set) against the label by exact match, and — when the case carries a judge question
    AND a ``judge_model`` is given — ALSO run the independent judge as a label audit."""
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

    judge_verdict: str | None = None
    if case.judge and judge_model:
        _emit(on_delta, f"\nAuditing the label with the judge on `{judge_model}`…\n\n")
        report = _judge_label(provider, case, judge_model=judge_model)
        judge_verdict = report.verdict.value
        agree = "agrees with" if judge_verdict == case.expected else "DISAGREES with"
        _emit(on_delta, f"**Judge: {judge_verdict}** — {agree} the label ({case.expected}). {report.reason}\n")

    return CaseResult(case=case, verdict=verdict, reason=reason, failures=failures, judge_verdict=judge_verdict)


def _judge_label(provider: AIProvider, case: DecompositionCase, *, judge_model: str):
    """Ask the independent rubric judge the case's merge/keep question from the definitions
    alone — a LABEL AUDIT. Reuses judge.py via a MERGE/KEEP case; evidence is the numbered
    definitions the decomposer folded (or kept)."""
    from app.ai.schemas import JudgeVerdict
    from app.evals.judge import JudgeCase, judge_case

    evidence = {
        f"definition_{i + 1}": str(d["definition"])
        for i, d in enumerate(d for report in case.reports for d in report)
    }
    jc = JudgeCase(
        key=f"live-decompose::{case.key}",
        title=case.judge,
        task=case.judge,
        evidence=evidence,
        expected=JudgeVerdict(case.expected),
        pass_name="decomposition",
    )
    return judge_case(provider, jc, model_id=judge_model).report


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

    def run_once() -> str:
        verdict, _reason = _decompose_verdict(provider, case, decompose_model=decompose_model)
        runs["i"] += 1
        _emit(on_delta, f"- run {runs['i']}: **{verdict}**\n")
        return verdict

    report = run_stability(run_once, k=k, contested=case.contested)
    tally = ", ".join(f"{v} x{n}" for v, n in report.tally.items())
    _emit(on_delta, f"\n**{report.marker}** {report.agreement:.0%} agreement — {tally}\n")
    return report
