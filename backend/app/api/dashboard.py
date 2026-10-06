from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

# Scope + cache-key helpers reused from the passes themselves, so "coverage" counts
# exactly what a re-run would process (never a parallel definition that could drift).
from app.ai.analysis import cache_keys_for, present_cache_keys
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
    ApplicationAISelection,
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
from app.schemas.email_delivery import SocketLabsQueueStatusOut
from app.schemas.settings import effective_reasoning_effort
from app.services.applications.scope import (
    opening_applications,
    resolve_visible_opening_id,
)
from app.services.email.outbox import email_delivery_issues, email_queue_status
from app.services.email.socketlabs_queue import (
    SocketLabsQueueReader,
    SocketLabsQueueStatus,
    get_socketlabs_queue_reader,
)
from app.services.openings.selection import overdue_openings_needing_decision
from app.services.ranking.analysis import (
    current_dimension_kinds,
    get_current_analysis,
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
    # Existing criteria are ready when every in-scope applicant has current scores.
    # Discovery remains an optional paid action; its captured inputs are provenance.
    current_criteria_scored = (
        scoring_coverage is not None
        and scoring_coverage.in_scope > 0
        and scoring_coverage.cached == scoring_coverage.in_scope
    )
    current_analysis = get_current_analysis(db, opening_id)
    email_queue = email_queue_status(db) if user.role == UserRole.ADMIN else None

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
            ranking_current=current_criteria_scored,
        ),
        # Per-AI-step coverage of the current scope. Applicant edits make the cached
        # content key stale, so the UI warns instead of showing a misleading check.
        coverage=coverage,
        admin_actions=(
            AdminActions(
                overdue_openings_needing_decision=[
                    OpeningSelectionAction(
                        opening_id=opening.id,
                        unit_size_bedrooms=opening.unit_size_bedrooms,
                        move_in_date=opening.move_in_date,
                    )
                    for opening in overdue_openings_needing_decision(db)
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
    socketlabs_reader: SocketLabsQueueReader = Depends(get_socketlabs_queue_reader),
) -> EmailDeliveryIssuesResponse:
    socketlabs = socketlabs_reader.cached()
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
        ],
        socketlabs=_socketlabs_status_out(socketlabs),
    )


@router.post(
    "/email-deliveries/socketlabs/refresh",
    response_model=SocketLabsQueueStatusOut,
)
def refresh_socketlabs_delivery_status(
    _admin: User = Depends(require_admin),
    socketlabs_reader: SocketLabsQueueReader = Depends(get_socketlabs_queue_reader),
) -> SocketLabsQueueStatusOut:
    return _socketlabs_status_out(socketlabs_reader.fetch())


def _socketlabs_status_out(
    status: SocketLabsQueueStatus | None,
) -> SocketLabsQueueStatusOut:
    return SocketLabsQueueStatusOut(
        available=status is not None,
        delayed=status.delayed if status else False,
        queued_count=status.queued_count if status else None,
        oldest_queued_at=status.oldest_queued_at if status else None,
        retrieved_at=status.retrieved_at if status else None,
    )


def _as_utc(timestamp: datetime | None) -> datetime | None:
    return as_utc(timestamp) if timestamp is not None else None


def _coverage(db: Session, opening_id: int, settings) -> dict[str, CoverageEntry]:
    # Coverage is a cache-hit count, so each pass must be probed under its configured
    # model — a cache row's key includes the model. Keep pass settings separate.

    # Screening freshness depends only on its prompt and model. Pet limits are evaluated
    # deterministically on read and therefore do not invalidate screening coverage.
    screening_apps = screening_scope(db, opening_id)
    screening_keys = cache_keys_for(screening_apps, ["screening"],
        model_id=settings.ai.screening_model, prompt_version=screening_prompt_version(),
        reasoning_effort=effective_reasoning_effort(settings.ai.screening_model, settings.ai.screening_reasoning_effort))
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
        expected = cache_keys_for(applications, kinds, model_id=settings.ai.dimension_scoring_model,
            prompt_version=SCORING_PROMPT_VERSION, reasoning_effort=effective_reasoning_effort(
                settings.ai.dimension_scoring_model, settings.ai.dimension_scoring_reasoning_effort))
        present = present_cache_keys(db, expected.values())
        fully_scored = sum(all(expected[app.id, kind] in present for kind in kinds) for app in applications)
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
    """Whether any selected AI result matches — exact ``kind`` or a ``prefix`` of it
    (e.g. ``dimension_scoring:`` matches the per-dimension scoring rows)."""
    match = (
        ApplicationAISelection.kind == kind
        if prefix is None
        else ApplicationAISelection.kind.startswith(prefix)
    )
    query = select(ApplicationAISelection.result_id).where(match)
    if application_ids is not None:
        if not application_ids:
            return False
        query = query.where(ApplicationAISelection.application_id.in_(application_ids))
    return db.scalar(query.limit(1)) is not None
