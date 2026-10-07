"""Live scoring eval: run golden synthetic inputs through the REAL scoring prompt+model.

The invariant checks (``invariants.py``) grade a *recorded* artifact — so they catch a bad
re-baseline and code rot, but are blind to a prompt/model regression, because the model never
runs. This eval closes that gap: it freezes the INPUTS (hand-authored synthetic applicants +
one dimension each), runs them through the exact production ``dimension_scoring`` prompt on the
configured scoring model, and grades the FRESH output DETERMINISTICALLY: the produced score
must fall in the case's expected ``[score_min, score_max]`` band (+ optional ``confidence``).
That is what "test the actual prompt" means.

No judge tier. Scoring is graded like every other pass — by a deterministic check against the
human label (here a numeric band, since scoring is continuous). The separate label-audit /
calibration question ("is that band itself defensible?") is the Judge tab's job: it re-produces
a score from the SAME ``given`` on an independent model, blind to the label, and compares — see
``judge.py``. Keeping the live eval judge-free makes it cheap and unambiguous.

Inputs are FICTIONAL (see eval-data/scoring_golden.json), so no synthetic-pool guard is
needed. This costs real model calls and is non-deterministic, so it runs from the Evals
tab (POST /evals/scoring, deliberate + spend-confirmed), never as part of pytest/CI.
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
    PoolDimension,
)
from app.evals.case_schema import validate_case
from app.evals.fixture_files import read_json
from app.evals.paths import GOLDEN_PATH
from app.evals.stability import (
    DeltaSink,
    RunDetail,
    StabilityReport,
    emit,
    emit_stability_summary,
    run_stability,
)


@dataclass(frozen=True)
class GoldenCase:
    key: str
    applicant: dict[str, object]
    dimension: PoolDimension
    # The expected band the produced score must fall in: any of score_min/score_max/confidence
    # (a neutral case pins a tight symmetric band around 0). The human label for this case.
    expected: dict[str, object]
    note: str = ""


@dataclass(frozen=True)
class CaseResult:
    case: GoldenCase
    score: float | None
    confidence: str
    evidence: str
    failures: list[str] = field(default_factory=list)  # deterministic band/confidence breaches

    @property
    def passed(self) -> bool:
        return not self.failures


def load_golden(path: Path = GOLDEN_PATH, *, data: dict | None = None) -> tuple[GoldenCase, ...]:
    """Load the golden cases, flattening the by-consumer blocks (metadata / given — see the
    fixture's `_comment`) into the flat GoldenCase the runner uses. The on-disk grouping
    documents WHO sees each field; the runner doesn't care, so it's flattened here."""
    data = read_json(path) if data is None else data
    for case in data["cases"]:
        validate_case("scoring", case)
    return tuple(
        GoldenCase(
            key=c["key"],
            applicant=c["given"]["applicant"],
            dimension=PoolDimension(
                key=c["given"]["dimension"]["key"],
                name=c["given"]["dimension"]["name"],
                definition=c["given"]["dimension"]["definition"],
                high_end=c["given"]["dimension"]["high_end"],
                low_end=c["given"]["dimension"]["low_end"],
                why_it_differentiates="",
            ),
            expected=c["metadata"]["expected"],
            note=c["metadata"].get("note", ""),
        )
        for c in data["cases"]
    )


def _check_expectations(score: DimensionScore, expected: dict[str, object]) -> list[str]:
    """Deterministic band check on one produced score. Returns human-readable failures. The
    score must sit within [score_min, score_max] (either bound optional) and match confidence
    if pinned; a neutral case pins a tight band straddling 0."""
    failures: list[str] = []
    if not (-1.0 <= score.score <= 1.0):
        failures.append(f"score {score.score} out of range [-1, 1]")
    if "score_min" in expected and score.score < float(expected["score_min"]):  # type: ignore[arg-type]
        failures.append(f"score {score.score} below expected min {expected['score_min']}")
    if "score_max" in expected and score.score > float(expected["score_max"]):  # type: ignore[arg-type]
        failures.append(f"score {score.score} above expected max {expected['score_max']}")
    if "confidence" in expected:
        # Any-of: "medium | high" accepts either (mirrors screening's fire-group convention). A
        # single value like "low" splits to a one-element set, so exact-match still holds.
        allowed = {c.strip() for c in str(expected["confidence"]).split("|")}
        if score.confidence.value not in allowed:
            failures.append(f"confidence {score.confidence.value!r} not in expected {sorted(allowed)}")
    if not score.evidence.strip():
        failures.append("evidence is empty (should state the basis, even for an unaddressed dimension)")
    return failures



def _score_once(provider: AIProvider, case: GoldenCase, *, scoring_model: str) -> DimensionScore | None:
    """Run the REAL scoring prompt once on the case's applicant+dimension and return the
    produced DimensionScore (or None if the model returned no score for the dimension).
    Shared by the single graded run and the K-run stability check so both exercise the
    identical production call."""
    applicant_block = json.dumps(case.applicant, indent=2, default=str)
    result = provider.structured_output(
        model_id=scoring_model,
        schema=DimensionScoringReport,
        prompt=_build_prompt(applicant_block, [case.dimension]),
        system_prompt=SYSTEM_PROMPT,
    )
    produced = {s.dimension_key: s for s in result.output.scores}
    return produced.get(case.dimension.key)


def run_case(
    provider: AIProvider,
    case: GoldenCase,
    *,
    scoring_model: str,
    on_delta: DeltaSink = None,
) -> CaseResult:
    """Score one golden case through the REAL prompt, then grade it against the expected band.

    ``on_delta``, when given, receives a NARRATION of the run as markdown (the "thinking"
    the Evals tab shows live). We emulate it from the real model OUTPUT rather than stream
    the model's reasoning: scoring one item is a tight structured_output call that emits ~no
    free-form reasoning, so there is nothing to stream — but the produced score, its grounding,
    and the band-check outcome are exactly what a reader wants to watch. Deterministic;
    identical result whether or not a sink is given.
    """
    emit(on_delta, f"Scoring **{case.dimension.name}** on `{scoring_model}`…\n\n")
    score = _score_once(provider, case, scoring_model=scoring_model)
    if score is None:
        emit(on_delta, f"⚠️ Model returned no score for `{case.dimension.key}`.\n")
        return CaseResult(
            case=case, score=None, confidence="?", evidence="",
            failures=[f"model returned no score for {case.dimension.key}"],
        )

    emit(
        on_delta,
        f"**Score {score.score:+.2f}** ({score.confidence.value} confidence)\n\n"
        f"- _Rationale:_ {score.rationale}\n"
        f"- _Evidence:_ “{score.evidence}”\n\n",
    )

    failures = _check_expectations(score, case.expected)
    emit(
        on_delta,
        f"❌ {'; '.join(failures)}\n\n"
        if failures
        else "✓ Score within the expected band.\n\n",
    )

    return CaseResult(
        case=case, score=score.score, confidence=score.confidence.value,
        evidence=score.evidence, failures=failures,
    )


def band_str(expected: dict[str, object]) -> str:
    """A compact human-label token for an expected band, e.g. '[-0.15, 0.15] low'."""
    lo = expected.get("score_min", "-1")
    hi = expected.get("score_max", "1")
    conf = f" {expected['confidence']}" if "confidence" in expected else ""
    return f"[{lo}, {hi}]{conf}"


def judge_request(given: dict):
    """The exact blind request and output contract, shared with prompt versioning."""
    from app.ai.schemas import DimensionScoringReport
    from app.evals.reproduce import build_judge_prompt

    return build_judge_prompt(
        given,
        'Score the applicant against the dimension on a signed -1..+1 scale and cite your '
        'evidence. Return score, confidence, rationale, evidence.',
    ), DimensionScoringReport


def judge_reproduce(provider: AIProvider, *, given: dict, expected: dict, background: str, model: str):
    """Reproduce the pass blind, then grade its output against the human expectation."""
    from app.evals.reproduce import Reproduced

    dim = given["dimension"]
    prompt, schema = judge_request(given)
    result = provider.structured_output(model_id=model, schema=schema, prompt=prompt, system_prompt=background)
    produced = {s.dimension_key: s for s in result.output.scores}
    score = produced.get(dim["key"])
    from app.ai.pricing import cost_usd
    cost = cost_usd(result.model_id, result.usage)
    if score is None:
        return Reproduced("no score", band_str(expected), False, "judge returned no score", cost, error="judge returned no score")
    agrees = not _check_expectations(score, expected)
    detail = f"judge scored {score.score:+.2f} ({score.confidence.value}): {score.rationale}"
    return Reproduced(f"{score.score:+.2f}", band_str(expected), agrees, detail, cost)


@dataclass(frozen=True)
class ScoringStabilityResult:
    """K runs of the REAL scoring prompt on one fixed golden case. Scoring is CONTINUOUS, so
    the stability question isn't 'did the exact number repeat' (it never will — 0.02 vs 0.05
    is noise) but 'did the case's PASS/FAIL hold across runs' — i.e. did the score wander
    across the assertion boundary. The flip is measured on the assertion outcome (pass/fail),
    via the shared stability core; the score spread (min..max) is the supporting detail that
    shows how noisy the model was."""

    case: GoldenCase
    stability: StabilityReport  # outcomes are "pass"/"fail" tokens
    scores: list[float | None]

    @property
    def score_spread(self) -> tuple[float | None, float | None]:
        real = [s for s in self.scores if s is not None]
        return (min(real), max(real)) if real else (None, None)


def stability_run(
    provider: AIProvider,
    case: GoldenCase,
    *,
    scoring_model: str,
    k: int = 5,
    on_delta: DeltaSink = None,
) -> ScoringStabilityResult:
    """Score one golden case K times on fixed input and report whether its PASS/FAIL held.
    Scoring is continuous, so the question isn't 'did the exact number repeat' (it never will)
    but 'did the score stay on the same side of the expected band across runs'. The outcome
    token per run is 'pass'/'fail' on the band check; the shared core tallies the flip, and the
    score spread is surfaced as informational."""
    emit(on_delta, f"Scoring **{case.dimension.name}** x{k} on `{scoring_model}`…\n\n")
    scores: list[float | None] = []  # order-free: concurrent results only supply the range

    def run_once() -> RunDetail:
        score = _score_once(provider, case, scoring_model=scoring_model)
        if score is None:
            scores.append(None)
            return RunDetail("error", "model returned no score", error="model returned no score")
        scores.append(score.score)
        outcome = "fail" if _check_expectations(score, case.expected) else "pass"
        # Detail = the score + the model's rationale for it (the "why" behind a flip).
        detail = f"score {score.score:+.2f} ({score.confidence.value}): {score.rationale}"
        return RunDetail(outcome, detail)

    # A scoring golden case has no "contested" notion; a pass/fail flip is always a real signal.
    report = run_stability(run_once, k=k, contested=False, on_delta=on_delta)
    out = ScoringStabilityResult(case=case, stability=report, scores=scores)
    lo, hi = out.score_spread
    spread = f"score {lo:+.2f}..{hi:+.2f}" if lo is not None and hi is not None else "no scores returned"
    emit_stability_summary(report, on_delta)
    emit(on_delta, f"{spread}\n")
    return out


# The live scoring eval runs from the Evals tab through POST /evals/scoring.
