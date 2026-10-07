"""The streaming eval-run endpoints — the pass runs (single + stability) and the blind judge.
Each spends real model calls; each streams the model's reasoning as NDJSON ``thinking`` then a
terminal summary, and persists an EvalRun row (see ``_shared.stream``)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai.dimension_consolidation import PROMPT_VERSION as CONSOLIDATE_PROMPT_VERSION
from app.ai.dimension_decomposition import PROMPT_VERSION as DECOMPOSE_PROMPT_VERSION
from app.ai.dimension_matching import PROMPT_VERSION as MATCH_PROMPT_VERSION
from app.ai.provider import AIProvider
from app.api.dependencies import get_ai_provider, require_admin
from app.api.evals._categorical import CategoricalPass, run_categorical
from app.api.evals._shared import (
    DEFAULT_STABILITY_K,
    ReasoningProvider,
    case_workers,
    over_cases,
    runs_out,
    seed_str,
    select,
    stream,
)
from app.core.problems import Problem
from app.db.models import User
from app.db.session import get_db
from app.evals import stability
from app.evals.consolidate import load_cases as load_consolidation_cases
from app.evals.consolidate import run_case as run_consolidation_case
from app.evals.consolidate import stability_run as consolidation_stability_run
from app.evals.dataset import load_dataset
from app.evals.decompose import load_cases as load_decomposition_cases
from app.evals.decompose import run_case as run_decomposition_case
from app.evals.decompose import stability_run as decomposition_stability_run
from app.evals.judge import DEFAULT_MODEL as JUDGE_MODEL
from app.evals.judge import judge_case, load_cases, stability_run
from app.evals.judge import prompt_version as judge_prompt_version
from app.evals.matching import load_cases as load_matching_cases
from app.evals.matching import run_case as run_matching_case
from app.evals.matching import stability_run as matching_stability_run
from app.evals.scoring import load_golden, run_case
from app.evals.scoring import stability_run as scoring_stability_run
from app.evals.screening import fire_label as screening_fire_label
from app.evals.screening import load_cases as load_screening_cases
from app.evals.screening import run_case as run_screening_case
from app.evals.screening import stability_run as screening_stability_run
from app.schemas.evals import (
    ConsolidationCaseOut,
    ConsolidationResponse,
    ConsolidationStabilityCaseOut,
    ConsolidationStabilityResponse,
    DecompositionCaseOut,
    DecompositionResponse,
    DecompositionStabilityCaseOut,
    DecompositionStabilityResponse,
    JudgeCaseOut,
    JudgeRunResponse,
    MatchingCaseOut,
    MatchingResponse,
    MatchingStabilityCaseOut,
    MatchingStabilityResponse,
    ScoringCaseOut,
    ScoringResponse,
    ScoringStabilityCaseOut,
    ScoringStabilityResponse,
    ScreeningCaseOut,
    ScreeningResponse,
    ScreeningStabilityCaseOut,
    ScreeningStabilityResponse,
    StabilityCaseOut,
    StabilityRunResponse,
)
from app.schemas.settings import effective_reasoning_effort
from app.services.settings import get_app_settings

router = APIRouter()


@router.post("/scoring")
def run_scoring(
    mode: Literal["run", "stability"] = "run",
    k: int = DEFAULT_STABILITY_K,
    case: str | None = None,
    user: User = Depends(require_admin),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a scoring run: golden inputs → real scoring prompt+model → deterministic
    band check (the produced score must fall in the expected [min, max], + confidence). The
    scoring model's reasoning streams as ``thinking``. ``case`` runs just that one golden case
    (per-row run); omitted runs all.

    ``?mode=stability`` instead runs the REAL scoring prompt K times per golden case on fixed
    input, reporting whether each case's assertion pass/fail held (a flip = the score wandered
    across the assertion boundary). No judge — measures the production prompt's own stability."""
    from app.ai.dimension_scoring import PROMPT_VERSION as SCORING_PROMPT_VERSION

    settings = get_app_settings(db)
    scoring_model = settings.ai.dimension_scoring_model
    reasoning_effort = effective_reasoning_effort(
        scoring_model, settings.ai.dimension_scoring_reasoning_effort
    )
    configured_provider = ReasoningProvider(provider, reasoning_effort)
    dataset = load_dataset("scoring")
    fingerprints = dataset.case_fingerprints("scoring")
    golden = select(list(load_golden(data=dataset.families["scoring"])), case, lambda c: c.key)

    if mode == "stability":
        k = max(2, min(k, 10))

        def one_stability(c, case_delta) -> ScoringStabilityCaseOut:
            case_delta(f"\n\n### {c.key} (x{k})\n")
            res = scoring_stability_run(
                configured_provider, c, scoring_model=scoring_model, k=k,
                on_delta=case_delta,
            )
            lo, hi = res.score_spread
            return ScoringStabilityCaseOut(
                key=c.key, marker=res.stability.marker, agreement=res.stability.agreement,
                flipped=res.stability.flipped, tally=res.stability.tally,
                score_min=lo, score_max=hi, runs=runs_out(res.stability),
            )

        def work_stability(on_delta) -> ScoringStabilityResponse:
            out = over_cases(golden, one_stability, on_delta=on_delta, max_workers=case_workers(settings, fan_out=k))
            return ScoringStabilityResponse(
                scoring_prompt_version=SCORING_PROMPT_VERSION,
                scoring_model=scoring_model, reasoning_effort=reasoning_effort,
                k=k, cases=out,
            )

        return stream(db, "scoring_stability", SCORING_PROMPT_VERSION, work_stability, case_fingerprints=fingerprints)

    def one(c, case_delta):
        case_delta(f"\n\n### {c.key}\n")
        return run_case(
            configured_provider, c, scoring_model=scoring_model, on_delta=case_delta
        )

    def work(on_delta) -> ScoringResponse:
        results = over_cases(golden, one, on_delta=on_delta, max_workers=case_workers(settings))
        return ScoringResponse(
            scoring_prompt_version=SCORING_PROMPT_VERSION,
            scoring_model=scoring_model,
            reasoning_effort=reasoning_effort,
            passed=sum(1 for r in results if r.passed),
            total=len(results),
            cases=[
                ScoringCaseOut(
                    key=r.case.key, passed=r.passed, score=r.score, confidence=r.confidence,
                    evidence=r.evidence, failures=r.failures,
                )
                for r in results
            ],
        )

    return stream(db, "scoring", SCORING_PROMPT_VERSION, work, case_fingerprints=fingerprints)


CONSOLIDATION_EVAL = CategoricalPass(
    key="consolidation",
    load_cases=load_consolidation_cases,
    prompt_version=lambda: CONSOLIDATE_PROMPT_VERSION,
    run_case=lambda provider, item, model, on_delta: run_consolidation_case(
        provider, item, consolidate_model=model, on_delta=on_delta
    ),
    stability_run=lambda provider, item, model, *, k, on_delta: consolidation_stability_run(
        provider, item, consolidate_model=model, k=k, on_delta=on_delta
    ),
    case_out=ConsolidationCaseOut,
    run_response=ConsolidationResponse,
    stability_out=ConsolidationStabilityCaseOut,
    stability_response=ConsolidationStabilityResponse,
)

MATCHING_EVAL = CategoricalPass(
    key="matching",
    load_cases=load_matching_cases,
    prompt_version=lambda: MATCH_PROMPT_VERSION,
    run_case=lambda provider, item, model, on_delta: run_matching_case(
        provider, item, match_model=model, on_delta=on_delta
    ),
    stability_run=lambda provider, item, model, *, k, on_delta: matching_stability_run(
        provider, item, match_model=model, k=k, on_delta=on_delta
    ),
    case_out=MatchingCaseOut,
    run_response=MatchingResponse,
    stability_out=MatchingStabilityCaseOut,
    stability_response=MatchingStabilityResponse,
)

DECOMPOSITION_EVAL = CategoricalPass(
    key="decomposition",
    load_cases=load_decomposition_cases,
    prompt_version=lambda: DECOMPOSE_PROMPT_VERSION,
    run_case=lambda provider, item, model, on_delta: run_decomposition_case(
        provider, item, decompose_model=model, on_delta=on_delta
    ),
    stability_run=lambda provider, item, model, *, k, on_delta: decomposition_stability_run(
        provider, item, decompose_model=model, k=k, on_delta=on_delta
    ),
    case_out=DecompositionCaseOut,
    run_response=DecompositionResponse,
    stability_out=DecompositionStabilityCaseOut,
    stability_response=DecompositionStabilityResponse,
)


def _run_categorical_endpoint(
    spec: CategoricalPass,
    mode: str,
    k: int,
    case: str | None,
    provider: AIProvider,
    db: Session,
) -> StreamingResponse:
    return run_categorical(
        spec, mode=mode, k=k, case=case, provider=provider, db=db
    )


@router.post("/consolidation")
def run_consolidation(
    mode: Literal["run", "stability"] = "run",
    k: int = DEFAULT_STABILITY_K,
    case: str | None = None,
    _user: User = Depends(require_admin),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    return _run_categorical_endpoint(CONSOLIDATION_EVAL, mode, k, case, provider, db)


@router.post("/matching")
def run_matching(
    mode: Literal["run", "stability"] = "run",
    k: int = DEFAULT_STABILITY_K,
    case: str | None = None,
    _user: User = Depends(require_admin),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    return _run_categorical_endpoint(MATCHING_EVAL, mode, k, case, provider, db)


@router.post("/decomposition")
def run_decomposition(
    mode: Literal["run", "stability"] = "run",
    k: int = DEFAULT_STABILITY_K,
    case: str | None = None,
    _user: User = Depends(require_admin),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    return _run_categorical_endpoint(DECOMPOSITION_EVAL, mode, k, case, provider, db)


@router.post("/screening")
def run_screening(
    mode: Literal["run", "stability"] = "run",
    k: int = DEFAULT_STABILITY_K,
    case: str | None = None,
    user: User = Depends(require_admin),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a screening run: golden synthetic applicants → the REAL screening
    prompt+model → the produced flag list graded per-category (expected fires present, guarded
    categories absent, clean applicants flag-free). ``case`` runs just that one applicant.

    ``?mode=stability`` instead runs the REAL screening prompt K times per applicant on fixed
    input, reporting whether the FLAG SET held. ``k`` clamped."""
    from app.ai.screening import screening_prompt_version

    settings = get_app_settings(db)
    model = settings.ai.screening_model
    reasoning_effort = effective_reasoning_effort(
        model, settings.ai.screening_reasoning_effort
    )
    configured_provider = ReasoningProvider(provider, reasoning_effort)
    version = screening_prompt_version()
    dataset = load_dataset("screening")
    fingerprints = dataset.case_fingerprints("screening")
    cases = select(list(load_screening_cases(data=dataset.families["screening"])), case, lambda c: c.key)

    if mode == "stability":
        k = max(2, min(k, 10))

        def one_stability(c, case_delta) -> ScreeningStabilityCaseOut:
            case_delta(f"\n\n### {c.key} (x{k})\n")
            rep = screening_stability_run(
                configured_provider, c, screening_model=model, k=k,
                on_delta=case_delta,
            )
            return ScreeningStabilityCaseOut(
                key=c.key, marker=rep.marker, majority=rep.majority,
                agreement=rep.agreement, flipped=rep.flipped, tally=rep.tally,
                runs=runs_out(rep),
            )

        def work_stability(on_delta) -> ScreeningStabilityResponse:
            out = over_cases(cases, one_stability, on_delta=on_delta, max_workers=case_workers(settings, fan_out=k))
            return ScreeningStabilityResponse(
                prompt_version=version, model=model,
                reasoning_effort=reasoning_effort, k=k, cases=out,
            )

        return stream(db, "screening_stability", version, work_stability, case_fingerprints=fingerprints)

    def one(c, case_delta):
        case_delta(f"\n\n### {c.key}\n")
        return run_screening_case(
            configured_provider, c, screening_model=model, on_delta=case_delta
        )

    def work(on_delta) -> ScreeningResponse:
        results = over_cases(cases, one, on_delta=on_delta, max_workers=case_workers(settings))
        return ScreeningResponse(
            prompt_version=version, model=model, reasoning_effort=reasoning_effort,
            passed=sum(1 for r in results if r.passed), total=len(results),
            cases=[
                ScreeningCaseOut(
                    key=r.case.key, passed=r.passed, categories=r.categories,
                    fires=[screening_fire_label(f) for f in r.case.fires],
                    absent=r.case.absent, contested=r.case.contested,
                    reason=r.reason, failures=r.failures,
                )
                for r in results
            ],
        )

    return stream(db, "screening", version, work, case_fingerprints=fingerprints)


@router.post("/judge")
def run_judge(
    mode: Literal["run", "stability"] = "run",
    k: int = DEFAULT_STABILITY_K,
    case: str | None = None,
    pass_name: str | None = Query(default=None, alias="passName"),
    user: User = Depends(require_admin),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a blind label-audit run over every pass's golden cases, then compute
    judge-vs-human agreement. Each case is reproduced by an INDEPENDENT model (blind to the
    label) and graded against the human label — see judge.py. ``case`` runs just that one
    (per-row run); case results carry the agreement evidence.

    ``?mode=stability`` instead blind-audits each case K times on fixed inputs and reports
    whether the judge's verdict held (persisted under eval_key ``stability``). ``k`` is clamped
    so a stray value can't blow up spend."""
    settings = get_app_settings(db)
    dataset = load_dataset()
    fingerprints = dataset.case_fingerprints("judge")
    all_cases = list(load_cases(dataset))
    if case is not None and pass_name is None:
        raise Problem("validation_error", detail="A Judge case requires its passName as well as its key.")
    cases = select([item for item in all_cases if pass_name is None or item.pass_name == pass_name], case, lambda c: c.key)
    pv = judge_prompt_version(dataset)

    if mode == "stability":
        k = max(2, min(k, 10))

        def one_stability(c, case_delta) -> StabilityCaseOut:
            case_delta(f"\n\n### [{c.pass_name}] {c.key} (x{k})\n")
            rep = stability_run(provider, c, k=k, model_id=JUDGE_MODEL, on_delta=case_delta)
            stability.emit_stability_summary(rep, case_delta)
            return StabilityCaseOut(
                key=c.key, pass_name=c.pass_name, marker=rep.marker,
                majority=rep.majority, seed=seed_str(c.expected),
                agreement=rep.agreement, flipped=rep.flipped, tally=rep.tally,
                runs=runs_out(rep),  # per-run reasoning, like the other passes' stability
            )

        def work_stability(on_delta) -> StabilityRunResponse:
            out = over_cases(cases, one_stability, on_delta=on_delta, max_workers=case_workers(settings, fan_out=k))
            return StabilityRunResponse(
                judge_prompt_version=pv, judge_model=JUDGE_MODEL, k=k, cases=out,
            )

        return stream(db, "stability", pv, work_stability, case_fingerprints=fingerprints)

    def one(c, case_delta):
        case_delta(f"\n\n### [{c.pass_name}] {c.key}\n")
        case_delta(f"Reproducing blind on `{JUDGE_MODEL}`…\n\n")
        r = judge_case(provider, c, model_id=JUDGE_MODEL)
        rp = r.reproduced
        agree = "agrees with" if rp.agrees else "DISAGREES with"
        case_delta(f"**judge: {rp.judge_label}** — {agree} label ({rp.human_label}). {rp.detail}\n")
        return r

    def work(on_delta) -> JudgeRunResponse:
        results = over_cases(cases, one, on_delta=on_delta, max_workers=case_workers(settings))
        case_out = [
            JudgeCaseOut(
                key=r.case.key, pass_name=r.case.pass_name, marker=r.marker,
                human_label=r.reproduced.human_label, judge_label=r.reproduced.judge_label,
                contested=r.case.contested, detail=r.reproduced.detail, error=r.reproduced.error,
                label_rationale=r.case.label_rationale,
            )
            for r in results
        ]
        return JudgeRunResponse(
            judge_prompt_version=pv, judge_model=JUDGE_MODEL,
            cases=case_out,
        )

    return stream(db, "judge", pv, work, case_fingerprints=fingerprints)
