from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

# Scope + cache-key helpers reused from the passes themselves, so "coverage" counts
# exactly what a re-run would process (never a parallel definition that could drift).
from app.ai.analysis import cache_key, present_cache_keys
from app.ai.dimension_scoring import (
    PROMPT_VERSION as SCORING_PROMPT_VERSION,
)
from app.ai.dimension_scoring import applications_to_score
from app.ai.screening import applications_for_screening as screening_scope
from app.ai.screening import screening_prompt_version
from app.api.dependencies import require_current_user
from app.db.models import (
    Analysis,
    ApplicationAIResult,
    User,
    UserRole,
)
from app.db.session import get_db
from app.schemas.dashboard import (
    AdminActions,
    CoverageEntry,
    DashboardResponse,
    OpeningSelectionAction,
    WorkflowState,
)
from app.schemas.settings import effective_reasoning_effort
from app.services.analysis import (
    current_dimension_kinds,
    get_current_analysis,
    ranking_is_current,
)
from app.services.application_scope import committee_applications
from app.services.opening_selection import archived_openings_needing_selection
from app.services.settings import get_app_settings

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
def read_dashboard(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> DashboardResponse:
    settings = get_app_settings(db)
    applications = committee_applications(db)
    coverage = _coverage(db, settings)
    scoring_coverage = coverage.get("candidatesScored")
    # A current Rank needs both halves: its criteria fingerprint must still match and
    # every in-scope candidate must have current scores for every live dimension. A
    # fingerprint alone cannot make a partial or failed scoring run look complete.
    current_criteria_scored = (
        scoring_coverage is not None
        and scoring_coverage.in_scope > 0
        and scoring_coverage.cached == scoring_coverage.in_scope
    )
    current_analysis = get_current_analysis(db)
    current_rank_inputs = ranking_is_current(db, current_analysis, settings)

    return DashboardResponse(
        # Whether each step has work available or has run, from persisted data so
        # workflow gating survives a reload.
        workflow=WorkflowState(
            applications_available=bool(applications),
            screened=_result_exists(db, kind="screening"),
            # Pattern discovery is a ranking run, not a per-application result.
            patterns_discovered=_run_exists(db),
            # Scoring kinds are per-dimension, so match by prefix.
            candidates_scored=_result_exists(db, prefix="dimension_scoring:"),
            # Analyses without dimensions have no scoring coverage to require. Once
            # dimensions exist, incomplete coverage always leaves Rank out of date.
            ranking_current=(
                current_rank_inputs
                and (scoring_coverage is None or current_criteria_scored)
            ),
        ),
        # Per-AI-step coverage of the current scope. Applicant edits make the cached
        # content key stale, so the UI warns instead of showing a misleading check.
        coverage=coverage,
        admin_actions=(
            AdminActions(
                archived_openings_needing_selection=[
                    OpeningSelectionAction(
                        opening_id=opening.id,
                        unit_size_bedrooms=opening.unit_size_bedrooms,
                        move_in_date=opening.move_in_date,
                    )
                    for opening in archived_openings_needing_selection(db)
                ]
            )
            if user.role == UserRole.ADMIN
            else None
        ),
    )

def _coverage(db: Session, settings) -> dict[str, CoverageEntry]:
    # Coverage is a cache-hit count, so each pass must be probed under the model it
    # actually runs on — a cache row's key includes the model. These are separate
    # settings now, so don't share one variable across passes.

    # Screening's version is a pure function of the prompt text (M15 1e: pets left the
    # prompt for a deterministic per-member filter), so pet-limit changes no longer drop
    # Screen coverage — they're a hard-filter change, judged on read. Only a prompt/model
    # change shows Screen out of date now.
    screening_apps = screening_scope(db)
    screening_keys = {
        app.id: cache_key(
            application=app, kind="screening",
            model_id=settings.ai.screening_model,
            prompt_version=screening_prompt_version(),
            reasoning_effort=effective_reasoning_effort(
                settings.ai.screening_model, settings.ai.screening_reasoning_effort
            ),
        )
        for app in screening_apps
    }
    present = present_cache_keys(db, set(screening_keys.values()))
    result = {
        "screened": CoverageEntry(
            cached=sum(1 for key in screening_keys.values() if key in present),
            in_scope=len(screening_apps),
        ),
    }

    # Scoring coverage is only meaningful against the current run. A candidate counts as
    # scored once it has a cached row for EVERY dimension key, so partial coverage reads as
    # not-yet-complete. All expected (candidate × dimension) keys are fetched in one query,
    # then membership is checked in memory.
    kinds = current_dimension_kinds(db)
    if kinds:
        applications = applications_to_score(db)
        keys_by_app = {
            app.id: [
                cache_key(
                    application=app, kind=kind,
                    model_id=settings.ai.dimension_scoring_model,
                    prompt_version=SCORING_PROMPT_VERSION,
                    reasoning_effort=effective_reasoning_effort(
                        settings.ai.dimension_scoring_model,
                        settings.ai.dimension_scoring_reasoning_effort,
                    ),
                )
                for kind in kinds
            ]
            for app in applications
        }
        present = present_cache_keys(
            db, {key for keys in keys_by_app.values() for key in keys}
        )
        fully_scored = sum(
            1
            for keys in keys_by_app.values()
            if all(key in present for key in keys)
        )
        result["candidatesScored"] = CoverageEntry(
            cached=fully_scored, in_scope=len(applications)
        )
    return result


def _result_exists(db: Session, *, kind: str | None = None, prefix: str | None = None) -> bool:
    """Whether any ``ApplicationAIResult`` matches — exact ``kind`` or a ``prefix`` of it
    (e.g. ``dimension_scoring:`` matches the per-dimension scoring rows)."""
    match = (
        ApplicationAIResult.kind == kind
        if prefix is None
        else ApplicationAIResult.kind.startswith(prefix)
    )
    return db.scalar(select(ApplicationAIResult.id).where(match).limit(1)) is not None


def _run_exists(db: Session) -> bool:
    return db.scalar(select(Analysis.id).limit(1)) is not None
