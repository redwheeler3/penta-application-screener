"""Live consolidation eval: run golden dimension pairs through the REAL consolidation
confirm prompt+model.

Like ``scoring.py``, this closes the gap the judge/invariant layers can't: they grade
recorded artifacts and are blind to a prompt/model regression because the model never runs.
This freezes the INPUT (a hand-picked pair of dimension definitions, mined from real runs),
runs it through the exact production ``dimension_consolidation`` confirm prompt on the
configured consolidate model, and grades the FRESH verdict.

Grader — categorical, so deterministic exact-match (see docs/ai-evals.md "Grader
architecture"): consolidation returns merge/keep, and the case carries the human ``expected``
verdict, so the check is ``produced_verdict == expected``. No judge tier — every live eval is
deterministic; the independent label-audit judge is the Judge tab's job (it re-produces the
verdict blind and compares — see ``judge.py``), not an inline per-run cost. A ``contested`` case
has no honest pass/fail on verdict direction, so it is reported but not counted toward
passed/total — its signal is stability, not verdict.

The pass bypasses the deterministic NOMINATE stage (correlation) — the eval hands it the pair
directly — and calls the CONFIRM prompt via ``build_prompt`` + ``structured_output``, exactly
as ``consolidate_dimensions`` does for one pair. Inputs are dimension definitions (criteria
text, not applicant PII), so no synthetic-pool guard is needed. Costs a real model call and is
non-deterministic, so it runs from the AI Quality tab, never as part of pytest/CI.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.ai.dimension_consolidation import SYSTEM_PROMPT, NominatedPair, build_prompt
from app.ai.provider import AIProvider
from app.ai.schemas import ConsolidationReport
from app.evals._categorical import CategoricalResult as CaseResult
from app.evals._categorical import grade_verdict
from app.evals.case_schema import validate_case
from app.evals.fixture_files import read_json
from app.evals.paths import CONSOLIDATION_GOLDEN_PATH
from app.evals.stability import (
    DeltaSink,
    RunDetail,
    StabilityReport,
    emit,
    emit_stability_summary,
    run_stability,
)

# The two verdict strings a consolidation case can expect (the categorical label).
MERGE, KEEP = "merge", "keep"


@dataclass(frozen=True)
class ConsolidationCase:
    key: str
    # The two dimension descriptors the confirm call compares. Each is {key, name, definition}.
    pair: tuple[dict[str, object], dict[str, object]]
    expected: str  # "merge" | "keep" — the human label
    contested: bool = False
    note: str = ""


def load_cases(path: Path = CONSOLIDATION_GOLDEN_PATH, *, data: dict | None = None) -> tuple[ConsolidationCase, ...]:
    """Load the golden consolidation cases, flattening the by-consumer blocks (metadata /
    given — see docs/eval-case-schema.md) into the flat runner case."""
    data = read_json(path) if data is None else data
    cases = []
    for c in data["cases"]:
        validate_case("consolidation", c)
        pair = c["given"]["pair"]
        meta = c["metadata"]
        cases.append(
            ConsolidationCase(
                key=c["key"],
                pair=(pair[0], pair[1]),
                expected=meta["expected"],
                contested=meta.get("contested", False),
                note=meta.get("note", ""),
            )
        )
    return tuple(cases)



def _confirm_verdict(
    provider: AIProvider, case: ConsolidationCase, *, consolidate_model: str
) -> tuple[str | None, str]:
    """Run the REAL consolidation confirm prompt once on the case's pair and return
    ``(verdict, reason)`` — verdict is "merge"/"keep", or None if the model returned no
    verdict for the pair. Shared by the single-run grade and the K-run stability check, so
    both exercise the exact same production call."""
    a, b = case.pair
    keep_key, drop_key = str(a["key"]), str(b["key"])
    defs = {keep_key: str(a["definition"]), drop_key: str(b["definition"])}
    # One nominated pair; the eval supplies it directly (bypassing correlation nomination).
    pair = NominatedPair(keep=keep_key, drop=drop_key, r=1.0)
    result = provider.structured_output(
        model_id=consolidate_model,
        schema=ConsolidationReport,
        prompt=build_prompt([pair], defs),
        system_prompt=SYSTEM_PROMPT,
    )
    # The confirm returns one verdict per pair; find ours regardless of key order.
    verdict_obj = next(
        (v for v in result.output.verdicts if {v.key_a, v.key_b} == {keep_key, drop_key}),
        None,
    )
    if verdict_obj is None:
        return None, ""
    return (MERGE if verdict_obj.same_concept else KEEP), verdict_obj.reason


def judge_request(given: dict):
    """The exact blind request and output contract, shared with prompt versioning."""
    from app.ai.schemas import JudgeReport
    from app.evals.reproduce import build_judge_prompt

    return build_judge_prompt(
        given,
        'Decide whether the two dimension definitions measure the SAME underlying concept: '
        "return verdict 'merge' (same concept) or 'keep' (genuinely distinct), with a reason.",
    ), JudgeReport


def judge_reproduce(provider: AIProvider, *, given: dict, expected: str, background: str, model: str):
    """Reproduce the pass blind, then grade its output against the human expectation."""
    from app.ai.pricing import cost_usd
    from app.evals.reproduce import Reproduced

    prompt, schema = judge_request(given)
    result = provider.structured_output(model_id=model, schema=schema, prompt=prompt, system_prompt=background)
    verdict = result.output.verdict.value
    cost = cost_usd(result.model_id, result.usage)
    error = None if verdict in (MERGE, KEEP) else f"model returned an invalid verdict: {verdict}"
    return Reproduced(verdict, expected, verdict == expected, result.output.reason, cost, error=error)


def run_case(
    provider: AIProvider,
    case: ConsolidationCase,
    *,
    consolidate_model: str,
    on_delta: DeltaSink = None,
) -> CaseResult:
    """Run one golden pair through the REAL consolidation confirm prompt and grade the verdict
    against the label by exact match.

    ``on_delta``, when given, receives a NARRATION of the run as markdown (the "thinking" the
    AI Quality tab shows). As in scoring, we emulate it from the real model OUTPUT — a
    tight structured_output call streams ~no free-form reasoning, so there is nothing to
    stream, but the produced verdict and its grounding are what a reader wants to watch.
    """
    a, b = case.pair

    emit(on_delta, f"Consolidating **{a['name']}** ~ **{b['name']}** on `{consolidate_model}`…\n\n")
    verdict, reason = _confirm_verdict(provider, case, consolidate_model=consolidate_model)
    if verdict is None:
        emit(on_delta, f"⚠️ Model returned no verdict for `{a['key']}` ~ `{b['key']}`.\n")
        return CaseResult(case=case, verdict="?", reason="", failures=["model returned no verdict for the pair"], error="model returned no verdict for the pair")
    return grade_verdict(case, verdict, reason, on_delta)


def stability_run(
    provider: AIProvider,
    case: ConsolidationCase,
    *,
    consolidate_model: str,
    k: int = 5,
    on_delta: DeltaSink = None,
) -> StabilityReport:
    """Run the REAL confirm prompt ``k`` times on the case's fixed pair and report verdict
    stability (does the production prompt return the same merge/keep every time?). Delegates
    the tallying/marker to the shared stability core — the only pass-specific part is one
    confirm call producing one verdict token. Evidence this matters: the run-5/6/7
    keep→merge→merge wobble on the trade-skills pair."""
    a, b = case.pair
    emit(on_delta, f"Consolidating **{a['name']}** ~ **{b['name']}** x{k} on `{consolidate_model}`…\n\n")

    def run_once() -> RunDetail:
        verdict, reason = _confirm_verdict(provider, case, consolidate_model=consolidate_model)
        return RunDetail(verdict or "error", reason or "model returned no verdict",
                         error="model returned no verdict" if verdict is None else None)

    report = run_stability(run_once, k=k, contested=case.contested, on_delta=on_delta)
    emit_stability_summary(report, on_delta)
    return report
