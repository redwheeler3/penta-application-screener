"""The streaming eval-run endpoints — the pass runs (single + stability) and the blind judge.
Each spends real model calls; each streams the model's reasoning as NDJSON ``thinking`` then a
terminal summary, and persists an EvalRun row (see ``_shared.stream``)."""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai.provider import AIProvider
from app.api.dependencies import get_ai_provider, require_current_user
from app.api.evals._shared import (
    DEFAULT_STABILITY_K,
    case_workers,
    over_cases,
    runs_out,
    seed_str,
    select,
    stream,
)
from app.db.models import User
from app.db.session import get_db
from app.evals import stability
from app.evals.agreement import score_agreement
from app.evals.consolidate import load_cases as load_consolidation_cases
from app.evals.consolidate import run_case as run_consolidation_case
from app.evals.consolidate import stability_run as consolidation_stability_run
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
    AgreementOut,
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
from app.services.settings import get_app_settings

router = APIRouter()


@router.post("/scoring")
def run_scoring(
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a scoring run: golden inputs → real scoring prompt+model → deterministic
    band check (the produced score must fall in the expected [min, max], + confidence). The
    scoring model's reasoning streams as ``thinking``. ``case`` runs just that one golden case
    (per-row run); omitted runs all."""
    from app.ai.dimension_scoring import PROMPT_VERSION as SCORING_PROMPT_VERSION

    settings = get_app_settings(db)
    scoring_model = settings.ai.dimension_scoring_model
    golden = select(list(load_golden()), case, lambda c: c.key)

    def one(c, case_delta):
        case_delta(f"\n\n### {c.key}\n")
        return run_case(provider, c, scoring_model=scoring_model, on_delta=case_delta)

    def work(on_delta) -> ScoringResponse:
        results = over_cases(golden, one, on_delta=on_delta, max_workers=case_workers(settings))
        return ScoringResponse(
            scoring_prompt_version=SCORING_PROMPT_VERSION,
            scoring_model=scoring_model,
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

    return stream(db, "scoring", SCORING_PROMPT_VERSION, work)


@router.post("/scoring-stability")
def run_scoring_stability(
    k: int = DEFAULT_STABILITY_K,
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a scoring STABILITY run: the REAL scoring prompt K times per golden case on
    fixed input, reporting whether each case's assertion pass/fail held (a flip = the score
    wandered across the assertion boundary). No judge — measures the production scoring prompt's
    own stability. ``k`` clamped; ``case`` runs just that one."""
    from app.ai.dimension_scoring import PROMPT_VERSION as SCORING_PROMPT_VERSION

    k = max(2, min(k, 10))
    settings = get_app_settings(db)
    scoring_model = settings.ai.dimension_scoring_model
    golden = select(list(load_golden()), case, lambda c: c.key)

    def one(c, case_delta) -> ScoringStabilityCaseOut:
        case_delta(f"\n\n### {c.key} (x{k})\n")
        res = scoring_stability_run(provider, c, scoring_model=scoring_model, k=k, on_delta=case_delta)
        lo, hi = res.score_spread
        return ScoringStabilityCaseOut(
            key=c.key, marker=res.stability.marker, agreement=res.stability.agreement,
            flipped=res.stability.flipped, tally=res.stability.tally,
            score_min=lo, score_max=hi, runs=runs_out(res.stability),
        )

    def work(on_delta) -> ScoringStabilityResponse:
        out = over_cases(golden, one, on_delta=on_delta, max_workers=case_workers(settings, fan_out=k))
        return ScoringStabilityResponse(
            scoring_prompt_version=SCORING_PROMPT_VERSION, scoring_model=scoring_model, k=k, cases=out,
        )

    return stream(db, "scoring_stability", SCORING_PROMPT_VERSION, work)


@router.post("/consolidation")
def run_consolidation(
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a consolidation run: golden dimension pairs → the REAL consolidation
    confirm prompt+model → merge/keep graded against the label by exact match. ``case`` runs
    just that one pair (per-row run); omitted runs all. A contested case counts as passed
    whichever way it lands (both verdicts defensible) — it's a pass with special treatment, not
    excluded from the tally."""
    from app.ai.dimension_consolidate import (
        PROMPT_VERSION as CONSOLIDATE_PROMPT_VERSION,
    )

    settings = get_app_settings(db)
    model = settings.ai.consolidate_model
    cases = select(list(load_consolidation_cases()), case, lambda c: c.key)

    def one(c, case_delta):
        case_delta(f"\n\n### {c.key}\n")
        return run_consolidation_case(provider, c, consolidate_model=model, on_delta=case_delta)

    def work(on_delta) -> ConsolidationResponse:
        results = over_cases(cases, one, on_delta=on_delta, max_workers=case_workers(settings))
        return ConsolidationResponse(
            prompt_version=CONSOLIDATE_PROMPT_VERSION,
            model=model,
            passed=sum(1 for r in results if r.case.contested or r.passed),
            total=len(results),
            cases=[
                ConsolidationCaseOut(
                    key=r.case.key, passed=r.passed, verdict=r.verdict,
                    expected=r.case.expected, contested=r.case.contested,
                    reason=r.reason, failures=r.failures,
                )
                for r in results
            ],
        )

    return stream(db, "consolidation", CONSOLIDATE_PROMPT_VERSION, work)


@router.post("/consolidation-stability")
def run_consolidation_stability(
    k: int = DEFAULT_STABILITY_K,
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a consolidation STABILITY run: the REAL confirm prompt K times per pair on
    fixed input, reporting verdict stability (flip = the production prompt is unstable). ``k``
    is clamped so a stray value can't blow up spend. ``case`` runs just that one pair."""
    from app.ai.dimension_consolidate import (
        PROMPT_VERSION as CONSOLIDATE_PROMPT_VERSION,
    )

    k = max(2, min(k, 10))
    settings = get_app_settings(db)
    model = settings.ai.consolidate_model
    cases = select(list(load_consolidation_cases()), case, lambda c: c.key)

    def one(c, case_delta) -> ConsolidationStabilityCaseOut:
        case_delta(f"\n\n### {c.key} (x{k})\n")
        rep = consolidation_stability_run(provider, c, consolidate_model=model, k=k, on_delta=case_delta)
        return ConsolidationStabilityCaseOut(
            key=c.key, marker=rep.marker, majority=rep.majority, expected=c.expected,
            contested=c.contested, agreement=rep.agreement, flipped=rep.flipped,
            tally=rep.tally, runs=runs_out(rep),
        )

    def work(on_delta) -> ConsolidationStabilityResponse:
        out = over_cases(cases, one, on_delta=on_delta, max_workers=case_workers(settings, fan_out=k))
        return ConsolidationStabilityResponse(
            prompt_version=CONSOLIDATE_PROMPT_VERSION, model=model, k=k, cases=out,
        )

    return stream(db, "consolidation_stability", CONSOLIDATE_PROMPT_VERSION, work)


@router.post("/matching")
def run_matching(
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a matching run: golden prior/new dimension pairs → the REAL identity-match
    prompt+model → matches/mismatches graded against the label by exact match. ``case`` runs
    just that one pair."""
    from app.ai.dimension_matching import PROMPT_VERSION as MATCH_PROMPT_VERSION

    settings = get_app_settings(db)
    model = settings.ai.match_model
    cases = select(list(load_matching_cases()), case, lambda c: c.key)

    def one(c, case_delta):
        case_delta(f"\n\n### {c.key}\n")
        return run_matching_case(provider, c, match_model=model, on_delta=case_delta)

    def work(on_delta) -> MatchingResponse:
        results = over_cases(cases, one, on_delta=on_delta, max_workers=case_workers(settings))
        return MatchingResponse(
            prompt_version=MATCH_PROMPT_VERSION, model=model,
            passed=sum(1 for r in results if r.case.contested or r.passed), total=len(results),
            cases=[
                MatchingCaseOut(
                    key=r.case.key, passed=r.passed, verdict=r.verdict,
                    expected=r.case.expected, contested=r.case.contested,
                    reason=r.reason, failures=r.failures,
                )
                for r in results
            ],
        )

    return stream(db, "matching", MATCH_PROMPT_VERSION, work)


@router.post("/matching-stability")
def run_matching_stability(
    k: int = DEFAULT_STABILITY_K,
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a matching STABILITY run: the REAL match prompt K times per pair on fixed
    input, reporting verdict stability. ``k`` clamped; ``case`` runs just that one."""
    from app.ai.dimension_matching import PROMPT_VERSION as MATCH_PROMPT_VERSION

    k = max(2, min(k, 10))
    settings = get_app_settings(db)
    model = settings.ai.match_model
    cases = select(list(load_matching_cases()), case, lambda c: c.key)

    def one(c, case_delta) -> MatchingStabilityCaseOut:
        case_delta(f"\n\n### {c.key} (x{k})\n")
        rep = matching_stability_run(provider, c, match_model=model, k=k, on_delta=case_delta)
        return MatchingStabilityCaseOut(
            key=c.key, marker=rep.marker, majority=rep.majority, expected=c.expected,
            contested=c.contested, agreement=rep.agreement, flipped=rep.flipped, tally=rep.tally,
            runs=runs_out(rep),
        )

    def work(on_delta) -> MatchingStabilityResponse:
        out = over_cases(cases, one, on_delta=on_delta, max_workers=case_workers(settings, fan_out=k))
        return MatchingStabilityResponse(prompt_version=MATCH_PROMPT_VERSION, model=model, k=k, cases=out)

    return stream(db, "matching_stability", MATCH_PROMPT_VERSION, work)


@router.post("/decomposition")
def run_decomposition(
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a decomposition run: golden discovery-report sets → the REAL decomposition
    prompt+model → merge/keep DERIVED from the settled set (all carvings in one axis = merge;
    spread across ≥2 = keep), graded against the label by exact match. ``case`` runs just that
    one set."""
    from app.ai.dimension_decompose import PROMPT_VERSION as DECOMPOSE_PROMPT_VERSION

    settings = get_app_settings(db)
    model = settings.ai.decompose_model
    cases = select(list(load_decomposition_cases()), case, lambda c: c.key)

    def one(c, case_delta):
        case_delta(f"\n\n### {c.key}\n")
        return run_decomposition_case(provider, c, decompose_model=model, on_delta=case_delta)

    def work(on_delta) -> DecompositionResponse:
        results = over_cases(cases, one, on_delta=on_delta, max_workers=case_workers(settings))
        return DecompositionResponse(
            prompt_version=DECOMPOSE_PROMPT_VERSION, model=model,
            passed=sum(1 for r in results if r.case.contested or r.passed), total=len(results),
            cases=[
                DecompositionCaseOut(
                    key=r.case.key, passed=r.passed, verdict=r.verdict,
                    expected=r.case.expected, contested=r.case.contested,
                    reason=r.reason, failures=r.failures,
                )
                for r in results
            ],
        )

    return stream(db, "decomposition", DECOMPOSE_PROMPT_VERSION, work)


@router.post("/decomposition-stability")
def run_decomposition_stability(
    k: int = DEFAULT_STABILITY_K,
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a decomposition STABILITY run: the REAL decompose prompt K times per set on
    fixed input, reporting fold/keep stability. ``k`` clamped; ``case`` runs just that one."""
    from app.ai.dimension_decompose import PROMPT_VERSION as DECOMPOSE_PROMPT_VERSION

    k = max(2, min(k, 10))
    settings = get_app_settings(db)
    model = settings.ai.decompose_model
    cases = select(list(load_decomposition_cases()), case, lambda c: c.key)

    def one(c, case_delta) -> DecompositionStabilityCaseOut:
        case_delta(f"\n\n### {c.key} (x{k})\n")
        rep = decomposition_stability_run(provider, c, decompose_model=model, k=k, on_delta=case_delta)
        return DecompositionStabilityCaseOut(
            key=c.key, marker=rep.marker, majority=rep.majority, expected=c.expected,
            contested=c.contested, agreement=rep.agreement, flipped=rep.flipped, tally=rep.tally,
            runs=runs_out(rep),
        )

    def work(on_delta) -> DecompositionStabilityResponse:
        out = over_cases(cases, one, on_delta=on_delta, max_workers=case_workers(settings, fan_out=k))
        return DecompositionStabilityResponse(prompt_version=DECOMPOSE_PROMPT_VERSION, model=model, k=k, cases=out)

    return stream(db, "decomposition_stability", DECOMPOSE_PROMPT_VERSION, work)


@router.post("/screening")
def run_screening(
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a screening run: golden synthetic applicants → the REAL screening
    prompt+model → the produced flag list graded per-category (expected fires present, guarded
    categories absent, clean applicants flag-free). ``case`` runs just that one applicant."""
    from app.ai.screening import screening_prompt_version

    settings = get_app_settings(db)
    model = settings.ai.screening_model
    version = screening_prompt_version(settings)
    cases = select(list(load_screening_cases()), case, lambda c: c.key)

    def one(c, case_delta):
        case_delta(f"\n\n### {c.key}\n")
        return run_screening_case(provider, c, screening_model=model, settings=settings, on_delta=case_delta)

    def work(on_delta) -> ScreeningResponse:
        results = over_cases(cases, one, on_delta=on_delta, max_workers=case_workers(settings))
        return ScreeningResponse(
            prompt_version=version, model=model,
            passed=sum(1 for r in results if r.passed), total=len(results),
            cases=[
                ScreeningCaseOut(
                    key=r.case.key, passed=r.passed, categories=r.categories,
                    fires=[screening_fire_label(f) for f in r.case.fires],
                    absent=r.case.absent, reason=r.reason, failures=r.failures,
                )
                for r in results
            ],
        )

    return stream(db, "screening", version, work)


@router.post("/screening-stability")
def run_screening_stability(
    k: int = DEFAULT_STABILITY_K,
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a screening STABILITY run: the REAL screening prompt K times per applicant
    on fixed input, reporting whether the FLAG SET held. ``k`` clamped; ``case`` runs one."""
    from app.ai.screening import screening_prompt_version

    k = max(2, min(k, 10))
    settings = get_app_settings(db)
    model = settings.ai.screening_model
    version = screening_prompt_version(settings)
    cases = select(list(load_screening_cases()), case, lambda c: c.key)

    def one(c, case_delta) -> ScreeningStabilityCaseOut:
        case_delta(f"\n\n### {c.key} (x{k})\n")
        rep = screening_stability_run(provider, c, screening_model=model, settings=settings, k=k, on_delta=case_delta)
        return ScreeningStabilityCaseOut(
            key=c.key, marker=rep.marker, majority=rep.majority,
            agreement=rep.agreement, flipped=rep.flipped, tally=rep.tally,
            runs=runs_out(rep),
        )

    def work(on_delta) -> ScreeningStabilityResponse:
        out = over_cases(cases, one, on_delta=on_delta, max_workers=case_workers(settings, fan_out=k))
        return ScreeningStabilityResponse(prompt_version=version, model=model, k=k, cases=out)

    return stream(db, "screening_stability", version, work)


@router.post("/judge")
def run_judge(
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a blind label-audit run over every pass's golden cases, then compute
    judge-vs-human agreement. Each case is reproduced by an INDEPENDENT model (blind to the
    label) and graded against the human label — see judge.py. ``case`` runs just that one
    (per-row run); agreement needs ≥2 scored cases, so a single-case run reports no agreement
    block, only the verdict."""
    settings = get_app_settings(db)
    cases = select(list(load_cases()), case, lambda c: c.key)
    pv = judge_prompt_version()  # snapshot the briefs' hash for this run

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
                contested=r.case.contested, detail=r.reproduced.detail,
            )
            for r in results
        ]
        scored = [r for r in results if not r.case.contested]
        agreement = None
        if len(scored) >= 2:
            rep = score_agreement(results)
            agreement = AgreementOut(
                n_scored=rep.n_scored, n_agree=rep.n_agree, n_contested=rep.n_contested,
                agreement=rep.agreement, kappa=rep.kappa,
                per_category={k: [v[0], v[1]] for k, v in rep.per_category.items()},
                failure_total=rep.failure_total, failure_caught=rep.failure_caught,
                failure_recall=rep.failure_recall, failure_precision=rep.failure_precision,
            )
        return JudgeRunResponse(
            judge_prompt_version=pv, judge_model=JUDGE_MODEL,
            cases=case_out, agreement=agreement,
        )

    return stream(db, "judge", pv, work)


@router.post("/stability")
def run_stability(
    k: int = DEFAULT_STABILITY_K,
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a stability run: blind-audit each case K times on fixed inputs, report whether the
    judge's verdict held. ``k`` is clamped to a sane range so a stray value can't blow up spend.
    ``case`` runs just that one (per-row stability check)."""
    k = max(2, min(k, 10))
    settings = get_app_settings(db)
    cases = select(list(load_cases()), case, lambda c: c.key)
    pv = judge_prompt_version()  # snapshot the briefs' hash for this run

    def one(c, case_delta) -> StabilityCaseOut:
        case_delta(f"\n\n### [{c.pass_name}] {c.key} (x{k})\n")
        rep = stability_run(provider, c, k=k, model_id=JUDGE_MODEL, on_delta=case_delta)
        tally = dict(Counter(rep.labels).most_common())
        marker = stability.marker(rep.labels, contested=c.contested)
        case_delta(f"→ {marker} {rep.agreement:.0%}: {tally}\n")
        return StabilityCaseOut(
            key=c.key, pass_name=c.pass_name, marker=marker,
            majority=rep.majority, seed=seed_str(c.expected),
            agreement=rep.agreement, flipped=rep.flipped, tally=tally,
            runs=runs_out(rep),  # per-run reasoning, like the other passes' stability
        )

    def work(on_delta) -> StabilityRunResponse:
        out = over_cases(cases, one, on_delta=on_delta, max_workers=case_workers(settings, fan_out=k))
        return StabilityRunResponse(
            judge_prompt_version=pv, judge_model=JUDGE_MODEL, k=k, cases=out,
        )

    return stream(db, "stability", pv, work)
