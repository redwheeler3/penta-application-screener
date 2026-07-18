"""Live scoring eval: run golden synthetic inputs through the REAL scoring prompt+model.

The judge eval (``judge.py``) and the invariant checks (``invariants.py``) both grade a
*recorded* artifact — so they catch a bad re-baseline and code rot, but are blind to a
prompt/model regression, because the model never runs. This eval closes that gap: it
freezes the INPUTS (hand-authored synthetic applicants + one dimension each), runs them
through the exact production ``dimension_scoring`` prompt on the configured scoring model,
and grades the FRESH output. That is what "test the actual prompt" means.

Two grader tiers, run on EVERY case, by what each can honestly decide:
  - **Deterministic assertions** — crisp properties any correct output must satisfy: score
    in range, an unaddressed dimension scores 0 (neutral), stated evidence. Cheap,
    unambiguous; these are the regression net (the signed-scale absence bug is one). They
    check the NUMBER.
  - **Rubric judge** — asks the existing LLM judge whether the produced score is defensible
    against the cited evidence: is a high/low score justified, and (just as important) is a
    NEUTRAL score on a silent applicant justified rather than a negative? This checks the
    REASONING the model wrote, which an assertion on the number can't — a case could hit
    0.0 with garbage justification. Reuses ``judge.py`` so the judge is the same validated
    one. A case's ``judge`` field is the question posed.

Inputs are FICTIONAL (see eval-data/scoring_golden.json), so no synthetic-pool guard is
needed. This costs real model calls and is non-deterministic, so it runs from the Evals
tab (POST /evals/live-scoring, deliberate + spend-confirmed), never as part of pytest/CI.
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
    JudgeReport,
    JudgeVerdict,
    PoolDimension,
)
from app.evals.paths import (
    GOLDEN_PATH,
)

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
    # The judge question — REQUIRED. It's the single source for both what the rubric judge
    # is asked (task) and what the UI shows (title); every case is graded by assertions AND
    # the judge. Phrase it as the instruction (SUPPORTED/UNSUPPORTED against the evidence).
    judge: str
    note: str = ""


@dataclass(frozen=True)
class CaseResult:
    case: GoldenCase
    score: float
    confidence: str
    evidence: str
    failures: list[str] = field(default_factory=list)  # deterministic assertion breaches
    # The rubric judge's verdict. Normally set (every golden case is judged); None only on
    # the early-return path where the model produced no score to judge.
    judge_verdict: JudgeVerdict | None = None

    @property
    def passed(self) -> bool:
        # A case passes when no deterministic assertion failed AND the judge found the score
        # defensible. (judge_verdict is None only when scoring failed outright, already a
        # failure via `failures`.)
        if self.failures:
            return False
        if self.judge_verdict is not None:
            return self.judge_verdict == JudgeVerdict.SUPPORTED
        return True


def load_golden(path: Path = GOLDEN_PATH) -> tuple[GoldenCase, ...]:
    """Load the golden cases, flattening the by-consumer blocks (metadata / input / judge —
    see the fixture's `_comment`) into the flat GoldenCase the runner uses. The on-disk
    grouping documents WHO sees each field; the runner doesn't care, so it's flattened here."""
    data = json.loads(path.read_text())
    return tuple(
        GoldenCase(
            key=c["key"],
            applicant=c["input"]["applicant"],
            dimension=PoolDimension(
                key=c["input"]["dimension"]["key"],
                name=c["input"]["dimension"]["name"],
                definition=c["input"]["dimension"]["definition"],
                high_end=c["input"]["dimension"]["high_end"],
                low_end=c["input"]["dimension"]["low_end"],
                why_it_differentiates="",
            ),
            expect=c["metadata"]["expect"],
            judge=c["judge"]["question"],  # single-source judge question (KeyError if absent)
            note=c["metadata"].get("note", ""),
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
) -> JudgeReport:
    """Ask the validated rubric judge whether the produced score is defensible. Reuses the
    judge's SUPPORTED/UNSUPPORTED rubric via a scoring-defensibility case. Returns the full
    report (verdict + reason) so the caller can both grade AND narrate the judge's thinking."""
    from app.evals.judge import JudgeCase, judge_case

    d = case.dimension
    # The case's `judge` question is the SINGLE source: it's both what the model reads (task)
    # and what the UI shows (title), so the two can't drift. It must be phrased as the actual
    # instruction to the judge (SUPPORTED/UNSUPPORTED against the cited evidence). Every
    # golden case carries one (load_golden enforces it), so there is no fallback.
    question = case.judge
    jc = JudgeCase(
        key=f"live::{case.key}",
        title=question,
        task=question,
        evidence={
            "dimension": d.name,
            "dimension_definition": d.definition,
            "high_end": d.high_end,
            "low_end": d.low_end,
            "cited_evidence": score.evidence,
            "score": score.score,
            "confidence": score.confidence.value,
        },
        expected=JudgeVerdict.SUPPORTED,  # a leaning; the judge's own verdict is what we read
        pass_name="scoring",
    )
    return judge_case(provider, jc, model_id=judge_model).report


def _emit(on_delta: object, text: str) -> None:
    """Write a narration chunk to the thinking sink, if one was given."""
    if on_delta is not None:
        on_delta(text)  # type: ignore[operator]


def run_case(
    provider: AIProvider,
    case: GoldenCase,
    *,
    scoring_model: str,
    judge_model: str,
    on_delta: object = None,
) -> CaseResult:
    """Score one golden case through the REAL prompt, then grade it (assertions + judge).

    ``on_delta``, when given, receives a NARRATION of the run as markdown (the "thinking"
    the Evals tab shows live). We emulate it from the real model OUTPUT rather than stream
    the model's reasoning: scoring/judging one item are tight structured_output calls that
    emit ~no free-form reasoning, so there is nothing to stream — but the produced score,
    its grounding, the assertion outcomes, and the judge's verdict+reason are exactly what a
    reader wants to watch. Deterministic; identical result whether or not a sink is given.
    """
    applicant_block = json.dumps(case.applicant, indent=2, default=str)
    _emit(on_delta, f"Scoring **{case.dimension.name}** on `{scoring_model}`…\n\n")
    result = provider.structured_output(
        model_id=scoring_model,
        schema=DimensionScoringReport,
        prompt=_build_prompt(applicant_block, [case.dimension]),
        system_prompt=SYSTEM_PROMPT,
    )
    produced = {s.dimension_key: s for s in result.output.scores}
    score = produced.get(case.dimension.key)
    if score is None:
        _emit(on_delta, f"⚠️ Model returned no score for `{case.dimension.key}`.\n")
        return CaseResult(
            case=case, score=float("nan"), confidence="?", evidence="",
            failures=[f"model returned no score for {case.dimension.key}"],
        )

    _emit(
        on_delta,
        f"**Score {score.score:+.2f}** ({score.confidence.value} confidence)\n\n"
        f"- _Rationale:_ {score.rationale}\n"
        f"- _Evidence:_ “{score.evidence}”\n\n",
    )

    failures = _check_expectations(score, case.expect)
    _emit(
        on_delta,
        f"❌ Assertions: {'; '.join(failures)}\n\n"
        if failures
        else "✓ Deterministic assertions passed.\n\n",
    )

    # Every scored case is judged (the question is required).
    _emit(on_delta, f"Asking the judge on `{judge_model}` — _{case.judge}_\n\n")
    report = _judge_defensible(provider, case, score, judge_model=judge_model)
    verdict = report.verdict
    _emit(on_delta, f"**Judge: {verdict.value}** — {report.reason}\n")

    return CaseResult(
        case=case, score=score.score, confidence=score.confidence.value,
        evidence=score.evidence, failures=failures, judge_verdict=verdict,
    )


# NB: no CLI entry point. The live scoring eval runs from the Evals tab
# (POST /evals/live-scoring, which calls load_golden/run_case directly).
