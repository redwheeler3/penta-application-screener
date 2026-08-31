from datetime import datetime

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
from app.api.dependencies import require_admin, require_current_user
from app.core.problems import Problem
from app.core.time import as_utc
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
    EmailDeliveryIssueOut,
    EmailDeliveryIssuesResponse,
    OpeningSelectionAction,
    WorkflowState,
)
from app.schemas.settings import effective_reasoning_effort
from app.services.application_scope import (
    opening_applications,
    resolve_visible_opening_id,
)
from app.services.email_outbox import email_delivery_issues, email_queue_status
from app.services.opening_selection import archived_openings_needing_selection
from app.services.ranking.analysis import (
    current_dimension_kinds,
    get_current_analysis,
    ranking_is_current,
)
from app.services.settings import get_app_settings

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
def read_dashboard(
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> DashboardResponse:
    if opening_id is None:
        try:
            opening_id = resolve_visible_opening_id(db, None)
        except Problem:
            opening_id = 0
    settings = get_app_settings(db)
    applications = opening_applications(db, opening_id)
    coverage = _coverage(db, opening_id, settings)
    scoring_coverage = coverage.get("candidatesScored")
    # A current Rank needs both halves: its criteria fingerprint must still match and
    # every in-scope candidate must have current scores for every live dimension. A
    # fingerprint alone cannot make a partial or failed scoring run look complete.
    current_criteria_scored = (
        scoring_coverage is not None
        and scoring_coverage.in_scope > 0
        and scoring_coverage.cached == scoring_coverage.in_scope
    )
    current_analysis = get_current_analysis(db, opening_id)
    current_rank_inputs = ranking_is_current(db, current_analysis, settings)
    email_queue = email_queue_status(db)

    return DashboardResponse(
        # Whether each step has work available or has run, from persisted data so
        # workflow gating survives a reload.
        workflow=WorkflowState(
            applications_available=bool(applications),
            screened=_result_exists(
                db, kind="screening", application_ids=[app.id for app in applications]
            ),
            # Pattern discovery is a ranking run, not a per-application result.
            patterns_discovered=current_analysis is not None,
            # Scoring kinds are per-dimension, so match by prefix.
            candidates_scored=_result_exists(
                db,
                prefix="dimension_scoring:",
                application_ids=[app.id for app in applications],
            ),
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
                ],
                queued_email_count=email_queue.count,
                quota_blocked_email_count=email_queue.quota_blocked,
                recent_failed_email_count=email_queue.recent_failed,
                oldest_queued_email_at=_as_utc(email_queue.oldest_queued_at),
                newest_queued_email_at=_as_utc(email_queue.newest_queued_at),
                last_email_attempt_at=_as_utc(email_queue.last_attempt_at),
            )
            if user.role == UserRole.ADMIN
            else None
        ),
    )


@router.get("/email-deliveries", response_model=EmailDeliveryIssuesResponse)
def read_email_delivery_issues(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> EmailDeliveryIssuesResponse:
    return EmailDeliveryIssuesResponse(
        items=[
            EmailDeliveryIssueOut(
                id=issue.id,
                recipient_email=issue.recipient_email,
                message_kind=issue.message_kind,
                state=issue.state,
                attempted_at=as_utc(issue.attempted_at),
                attempt_count=issue.attempt_count,
                error_code=issue.error_code,
                quota_blocked=issue.quota_blocked,
            )
            for issue in email_delivery_issues(db)
        ]
    )


def _as_utc(timestamp: datetime | None) -> datetime | None:
    return as_utc(timestamp) if timestamp is not None else None


def _coverage(db: Session, opening_id: int, settings) -> dict[str, CoverageEntry]:
    # Coverage is a cache-hit count, so each pass must be probed under the model it
    # actually runs on — a cache row's key includes the model. These are separate
    # settings now, so don't share one variable across passes.

    # Screening freshness depends only on its prompt and model. Pet limits are evaluated
    # deterministically on read and therefore do not invalidate screening coverage.
    screening_apps = screening_scope(db, opening_id)
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
    kinds = current_dimension_kinds(db, opening_id)
    if kinds:
        applications = applications_to_score(db, opening_id)
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


def _result_exists(
    db: Session,
    *,
    kind: str | None = None,
    prefix: str | None = None,
    application_ids: list[int] | None = None,
) -> bool:
    """Whether any ``ApplicationAIResult`` matches — exact ``kind`` or a ``prefix`` of it
    (e.g. ``dimension_scoring:`` matches the per-dimension scoring rows)."""
    match = (
        ApplicationAIResult.kind == kind
        if prefix is None
        else ApplicationAIResult.kind.startswith(prefix)
    )
    query = select(ApplicationAIResult.id).where(match)
    if application_ids is not None:
        if not application_ids:
            return False
        query = query.where(ApplicationAIResult.application_id.in_(application_ids))
    return db.scalar(query.limit(1)) is not None


def _run_exists(db: Session) -> bool:
    return db.scalar(select(Analysis.id).limit(1)) is not None
