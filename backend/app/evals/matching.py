"""Live matching eval: run golden prior/new dimension pairs through the REAL identity-match
prompt+model.

Like the other live evals, this closes the gap the judge/invariant layers can't: they grade
recorded artifacts and are blind to a prompt/model regression because the model never runs.
It freezes the INPUT (a prior dimension set + a newly-discovered set, mined from real runs),
runs them through the exact production ``dimension_matching`` prompt on the configured match
model, and grades the FRESH mapping.

Grader — categorical, so deterministic exact-match (see docs/ai-evals.md "Grader
architecture"): the pass maps each NEW dimension to at most one PRIOR one; for a focused case
(one prior + one new) the outcome is ``matches`` when the model mapped the new key onto the
prior key, else ``mismatches``. The case carries the human ``expected``, so the check is
``produced == expected``. No judge tier — the verdict IS the check.

A wrong match is the pass's high-stakes error (it moves tier intent + a cached score onto the
wrong concept), so the fixture carries a CONSTRUCTED mismatch pair to exercise that direction
even though the live pass hasn't erred. Inputs are dimension definitions (criteria text, not
applicant PII), so no synthetic-pool guard is needed. Costs a real model call and is
non-deterministic, so it runs from the AI Quality tab, never as part of pytest/CI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.ai.dimension_matching import SYSTEM_PROMPT, build_prompt
from app.ai.provider import AIProvider
from app.ai.schemas import DimensionMatchReport, PoolDimension, PoolDimensionReport
from app.evals.paths import MATCHING_GOLDEN_PATH
from app.evals.stability import StabilityReport, run_stability

MATCHES, MISMATCHES = "matches", "mismatches"


def _descriptor_to_dim(d: dict[str, object]) -> PoolDimension:
    """A golden descriptor {key, name, definition} → a PoolDimension. Matching only serializes
    key/name/definition (see dimension_matching._dimensions_block), so the poles are unused
    here — filled empty, never sent to the model."""
    return PoolDimension(
        key=str(d["key"]), name=str(d.get("name", "")), definition=str(d["definition"]),
        high_end="", low_end="", why_it_differentiates="",
    )


@dataclass(frozen=True)
class MatchingCase:
    key: str
    prior: list[dict[str, object]]  # prior-run dimension descriptors
    new: list[dict[str, object]]  # newly-discovered dimension descriptors
    expected: str  # "matches" | "mismatches" — the human label
    contested: bool = False
    note: str = ""


@dataclass(frozen=True)
class CaseResult:
    case: MatchingCase
    verdict: str  # "matches" | "mismatches" — what the real prompt produced
    reason: str  # narration of the mapping the model returned
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        if self.failures:
            return False
        return self.verdict == self.case.expected


def load_cases(path: Path = MATCHING_GOLDEN_PATH) -> tuple[MatchingCase, ...]:
    """Load the golden matching cases, flattening the by-consumer blocks (metadata / given —
    see docs/eval-case-schema.md) into the flat runner case."""
    data = json.loads(path.read_text())
    cases = []
    for c in data["cases"]:
        given, meta = c["given"], c["metadata"]
        cases.append(
            MatchingCase(
                key=c["key"],
                prior=given["prior"],
                new=given["new"],
                expected=meta["expected"],
                contested=meta.get("contested", False),
                note=meta.get("note", ""),
            )
        )
    return tuple(cases)


def _emit(on_delta: object, text: str) -> None:
    if on_delta is not None:
        on_delta(text)  # type: ignore[operator]


def _match_verdict(provider: AIProvider, case: MatchingCase, *, match_model: str) -> tuple[str, str]:
    """Run the REAL identity-match prompt once and return ``(verdict, detail)``. For a focused
    (one prior + one new) case, verdict is ``matches`` when the model mapped the new key onto
    the prior key, else ``mismatches``. ``detail`` is the model's own reasoning (its narrative)
    — the ONLY place a mismatch's 'why' lives, since a non-match is just absence from the match
    list, so we surface the narrative rather than a canned string. Shared by the single graded
    run and the K-run stability check."""
    old = PoolDimensionReport(dimensions=[_descriptor_to_dim(d) for d in case.prior])
    new = PoolDimensionReport(dimensions=[_descriptor_to_dim(d) for d in case.new])
    result = provider.structured_output(
        model_id=match_model,
        schema=DimensionMatchReport,
        prompt=build_prompt(old, new),
        system_prompt=SYSTEM_PROMPT,
    )
    prior_keys = {d["key"] for d in case.prior}
    new_keys = {d["key"] for d in case.new}
    # A match on THIS pair = the model emitted a new_key→old_key pair within our given keys.
    hit = next(
        (m for m in result.output.matches if m.new_key in new_keys and m.old_key in prior_keys),
        None,
    )
    verdict = MATCHES if hit is not None else MISMATCHES
    # Prefer the model's own reasoning (narrative); fall back to a description of the mapping.
    detail = (result.narrative or "").strip() or (
        f"mapped {hit.new_key} → {hit.old_key}" if hit else "no mapping between the pair"
    )
    return verdict, detail


def judge_reproduce(provider: AIProvider, *, given: dict, expected: str, background: str, model: str):
    """Blind-judge adapter (see app/evals/reproduce.py): an INDEPENDENT model decides whether
    the new dimension is the same concept as the prior one from the editable ``background`` +
    the two definitions (never the human label), then we exact-match its matches/mismatches
    verdict against ``expected``. A wrong MATCH corrupts a carried-forward score, so 'mismatches'
    is the problem side (feeds failure-recall)."""
    from app.ai.pricing import cost_usd
    from app.ai.schemas import JudgeReport
    from app.evals.reproduce import Reproduced, build_judge_prompt

    prompt = build_judge_prompt(
        given,
        "Decide whether the NEW dimension means the same underlying concept as the PRIOR one: "
        "return verdict 'matches' (same concept) or 'mismatches' (different), with a reason.",
    )
    result = provider.structured_output(model_id=model, schema=JudgeReport, prompt=prompt, system_prompt=background)
    verdict = result.output.verdict.value
    cost = cost_usd(result.model_id, result.usage)
    return Reproduced(
        verdict, expected, verdict == expected,
        expected == MISMATCHES, verdict == MISMATCHES, result.output.reason, cost,
    )


def run_case(
    provider: AIProvider,
    case: MatchingCase,
    *,
    match_model: str,
    on_delta: object = None,
) -> CaseResult:
    """Run one golden pair through the REAL match prompt and grade matches/mismatches against
    the label by exact match."""
    p, n = case.prior[0], case.new[0]
    _emit(on_delta, f"Matching new **{n['name']}** vs prior **{p['name']}** on `{match_model}`…\n\n")
    verdict, reason = _match_verdict(provider, case, match_model=match_model)
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
    case: MatchingCase,
    *,
    match_model: str,
    k: int = 5,
    on_delta: object = None,
) -> StabilityReport:
    """Run the REAL match prompt ``k`` times on the case's fixed pair and report verdict
    stability. Delegates tallying/marker to the shared stability core; the only pass-specific
    part is one match call producing one matches/mismatches token."""
    p, n = case.prior[0], case.new[0]
    _emit(on_delta, f"Matching new **{n['name']}** vs prior **{p['name']}** x{k} on `{match_model}`…\n\n")
    runs = {"i": 0}

    def run_once() -> tuple[str, str]:
        verdict, detail = _match_verdict(provider, case, match_model=match_model)
        runs["i"] += 1
        _emit(on_delta, f"- run {runs['i']}: **{verdict}** — {detail}\n")
        return verdict, detail

    report = run_stability(run_once, k=k, contested=case.contested)
    tally = ", ".join(f"{v} x{n}" for v, n in report.tally.items())
    _emit(on_delta, f"\n**{report.marker}** {report.agreement:.0%} agreement — {tally}\n")
    return report
