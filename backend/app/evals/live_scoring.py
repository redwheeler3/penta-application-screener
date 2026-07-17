"""Live scoring eval: run golden synthetic inputs through the REAL scoring prompt+model.

The judge eval (``judge.py``) and the invariant checks (``properties.py``) both grade a
*recorded* artifact — so they catch a bad re-baseline and code rot, but are blind to a
prompt/model regression, because the model never runs. This eval closes that gap: it
freezes the INPUTS (hand-authored synthetic applicants + one dimension each), runs them
through the exact production ``dimension_scoring`` prompt on the configured scoring model,
and grades the FRESH output. That is what "test the actual prompt" means.

Two grader tiers, by what each can honestly decide:
  - **Deterministic assertions** (the bulk) — crisp properties any correct output must
    satisfy: score in range, an unaddressed dimension scores 0 (neutral), stated evidence.
    Cheap, unambiguous; these are the regression net (the signed-scale absence bug is one).
  - **Rubric judge** (the subjective residue) — for a case that asserts "this SHOULD score
    high/low", ask the existing LLM judge whether the produced score is defensible against
    the cited evidence. Reuses ``judge.py`` so the judge is the same validated one.

Inputs are FICTIONAL (see fixtures/scoring_golden.json), so no synthetic-pool guard is
needed. This costs real model calls and is non-deterministic, so it is an explicit opt-in
run (``python -m app.evals.live_scoring``), never part of pytest/CI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.ai.dimension_scoring import SYSTEM_PROMPT, _build_prompt
from app.ai.provider import AIProvider
from app.ai.schemas import (
    DimensionScore,
    DimensionScoringReport,
    JudgeVerdict,
    PoolDimension,
)

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "scoring_golden.json"

# Absolute tolerance for a "score_equals" expectation. The model is non-deterministic even
# at temp 0, and 0 (neutral) is the value we most care about pinning — a tiny drift off 0.0
# is fine, a slide toward a pole is the failure. Kept tight so a real regression still trips.
_SCORE_TOL = 0.15


@dataclass(frozen=True)
class GoldenCase:
    key: str
    applicant: dict[str, object]
    dimension: PoolDimension
    expect: dict[str, object]
    judge: str | None = None
    note: str = ""


@dataclass(frozen=True)
class CaseResult:
    case: GoldenCase
    score: float
    confidence: str
    evidence: str
    failures: list[str] = field(default_factory=list)  # deterministic assertion breaches
    judge_verdict: JudgeVerdict | None = None  # rubric judge, when the case asks for it

    @property
    def passed(self) -> bool:
        # A case passes when no deterministic assertion failed AND (if judged) the judge
        # found the score defensible. The judge is advisory for a case with no `judge`.
        if self.failures:
            return False
        if self.judge_verdict is not None:
            return self.judge_verdict == JudgeVerdict.SUPPORTED
        return True


def load_golden(path: Path = GOLDEN_PATH) -> tuple[GoldenCase, ...]:
    data = json.loads(path.read_text())
    return tuple(
        GoldenCase(
            key=c["key"],
            applicant=c["applicant"],
            dimension=PoolDimension(
                key=c["dimension"]["key"],
                name=c["dimension"]["name"],
                definition=c["dimension"]["definition"],
                high_end=c["dimension"]["high_end"],
                low_end=c["dimension"]["low_end"],
                why_it_differentiates="",
            ),
            expect=c["expect"],
            judge=c.get("judge"),
            note=c.get("note", ""),
        )
        for c in data["cases"]
    )


def _check_expectations(score: DimensionScore, expect: dict[str, object]) -> list[str]:
    """Deterministic assertions on one produced score. Returns human-readable failures."""
    failures: list[str] = []
    if not (-1.0 <= score.score <= 1.0):
        failures.append(f"score {score.score} out of range [-1, 1]")
    if "score_equals" in expect:
        target = float(expect["score_equals"])  # type: ignore[arg-type]
        if abs(score.score - target) > _SCORE_TOL:
            failures.append(f"score {score.score} not ≈ {target} (±{_SCORE_TOL})")
    if "score_min" in expect and score.score < float(expect["score_min"]):  # type: ignore[arg-type]
        failures.append(f"score {score.score} below expected min {expect['score_min']}")
    if "score_max" in expect and score.score > float(expect["score_max"]):  # type: ignore[arg-type]
        failures.append(f"score {score.score} above expected max {expect['score_max']}")
    if "confidence" in expect and score.confidence.value != expect["confidence"]:
        failures.append(f"confidence {score.confidence.value!r} != expected {expect['confidence']!r}")
    if not score.evidence.strip():
        failures.append("evidence is empty (should state the basis, even for an unaddressed dimension)")
    return failures


def _judge_defensible(
    provider: AIProvider, case: GoldenCase, score: DimensionScore, *, judge_model: str
) -> JudgeVerdict:
    """Ask the validated rubric judge whether the produced score is defensible. Reuses the
    judge's SUPPORTED/UNSUPPORTED rubric via a scoring-defensibility case."""
    from app.evals.judge import JudgeCase, judge_case

    d = case.dimension
    jc = JudgeCase(
        key=f"live::{case.key}",
        title=case.judge or "Is this score defensible?",
        task="Given the dimension and the applicant's cited evidence, decide whether the "
        "score is SUPPORTED or UNSUPPORTED by that evidence.",
        evidence={
            "dimension": d.name,
            "dimension_definition": d.definition,
            "high_end": d.high_end,
            "low_end": d.low_end,
            "cited_evidence": score.evidence,
            "score": score.score,
        },
        expected=JudgeVerdict.SUPPORTED,  # a leaning; the judge's own verdict is what we read
        pass_name="scoring",
    )
    return judge_case(provider, jc, model_id=judge_model).report.verdict


def run_case(
    provider: AIProvider, case: GoldenCase, *, scoring_model: str, judge_model: str
) -> CaseResult:
    """Score one golden case through the REAL prompt, then grade it (assertions + judge)."""
    applicant_block = json.dumps(case.applicant, indent=2, default=str)
    result = provider.structured_output(
        model_id=scoring_model,
        schema=DimensionScoringReport,
        prompt=_build_prompt(applicant_block, [case.dimension]),
        system_prompt=SYSTEM_PROMPT,
    )
    produced = {s.dimension_key: s for s in result.output.scores}
    score = produced.get(case.dimension.key)
    if score is None:
        return CaseResult(
            case=case, score=float("nan"), confidence="?", evidence="",
            failures=[f"model returned no score for {case.dimension.key}"],
        )
    failures = _check_expectations(score, case.expect)
    verdict = (
        _judge_defensible(provider, case, score, judge_model=judge_model)
        if case.judge
        else None
    )
    return CaseResult(
        case=case, score=score.score, confidence=score.confidence.value,
        evidence=score.evidence, failures=failures, judge_verdict=verdict,
    )


def format_report(results: list[CaseResult]) -> str:
    from app.ai.dimension_scoring import PROMPT_VERSION

    passed = sum(1 for r in results if r.passed)
    lines = [
        "Live scoring eval — golden inputs → REAL prompt+model → assertions + rubric judge",
        f"Scoring prompt: {PROMPT_VERSION}",
        f"{passed}/{len(results)} cases passed",
        "",
    ]
    for r in results:
        marker = "[ok]" if r.passed else "[FAIL]"
        lines.append(f"{marker} {r.case.key}: score={r.score} conf={r.confidence}")
        lines.append(f"  evidence: {r.evidence[:100]}")
        for f in r.failures:
            lines.append(f"  ✗ {f}")
        if r.judge_verdict is not None:
            jm = "ok" if r.judge_verdict == JudgeVerdict.SUPPORTED else "FAIL"
            lines.append(f"  judge[{jm}]: {r.judge_verdict.value}")
        lines.append("  " + "-" * 60)
    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the live scoring eval (real model calls).")
    parser.add_argument("--scoring-model", default=None, help="Override the scoring model")
    parser.add_argument("--judge-model", default=None, help="Override the judge model")
    args = parser.parse_args()

    from app.ai.strands_provider import StrandsProvider
    from app.db.session import SessionLocal
    from app.evals.judge import DEFAULT_MODEL as JUDGE_DEFAULT
    from app.services.settings import get_app_settings

    db = SessionLocal()
    try:
        settings = get_app_settings(db)
    finally:
        db.close()
    scoring_model = args.scoring_model or settings.ai.dimension_scoring_model
    judge_model = args.judge_model or JUDGE_DEFAULT
    provider = StrandsProvider(region=settings.ai.region, max_pool_connections=1)

    results = [
        run_case(provider, c, scoring_model=scoring_model, judge_model=judge_model)
        for c in load_golden()
    ]
    print(format_report(results))


if __name__ == "__main__":
    main()
