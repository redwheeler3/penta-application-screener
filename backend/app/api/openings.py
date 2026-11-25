"""Admin-only opening configuration and lifecycle endpoints."""

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.core.problems import Problem
from app.core.time import pacific_today
from app.db.models import Opening, OpeningPhase, User
from app.db.session import get_db
from app.schemas.openings import (
    OpeningCommitOut,
    OpeningCreate,
    OpeningCreationRequest,
    OpeningDetailsOut,
    OpeningLaunchRequest,
    OpeningNotificationVariantOut,
    OpeningOut,
    OpeningPreviewOut,
    OpeningSelectionCandidateOut,
    OpeningSelectionOut,
    OpeningSelectionRequest,
    OpeningsResponse,
    OpeningUpdate,
    OpeningUpdatedOut,
    PreviousApplicantSearch,
    PreviousApplicantSearchOut,
    SocketLabsUsageOut,
)
from app.services.auth.authority import require_admin_write
from app.services.auth.passwordless import as_utc
from app.services.email.sender import EmailSender, get_email_sender
from app.services.email.socketlabs_usage import (
    SocketLabsUsageReader,
    get_socketlabs_usage_reader,
)
from app.services.maintenance import get_outbox_runner
from app.services.openings.catalog import (
    create_opening,
    created_request,
    creation_facts,
    list_openings,
    opening_phase,
    publish_opening,
    update_opening,
)
from app.services.openings.direct_selection import (
    search_previous_applicants,
    select_previous_applicant,
)
from app.services.openings.protection import (
    lock_openings,
)
from app.services.openings.selection import (
    confirm_no_household_selected,
    confirm_opening_selection,
    opening_candidate_summaries,
    retained_selected_households,
)
from app.services.openings.vacancy_notifications import (
    VacancyAudience,
    opening_audience,
    queue_opening_notifications,
)

router = APIRouter(prefix="/openings", tags=["openings"])


def _opening(db: Session, opening_id: int) -> Opening:
    opening = db.get(Opening, opening_id)
    if opening is None:
        raise Problem("not_found", detail="Opening not found.")
    return opening


def _response(db: Session) -> OpeningsResponse:
    openings = list_openings(db)
    selected = retained_selected_households(db, [opening.id for opening, _ in openings])
    return OpeningsResponse(openings=[
        _opening_out(opening, submission_count, selected.get(opening.id))
        for opening, submission_count in openings
    ])


def _opening_out(opening: Opening, submission_count: int, selected: tuple[int, str | None] | None) -> OpeningOut:
    phase = opening_phase(opening)
    decision_exists = opening.decided_at is not None
    return OpeningOut(
        id=opening.id,
        intake_mode=opening.intake_mode,
        min_children=opening.min_children, max_children=opening.max_children,
        unit_size_bedrooms=opening.unit_size_bedrooms,
        housing_charge_cents=opening.housing_charge_cents,
        application_open_date=opening.application_open_date,
        application_close_date=opening.application_close_date,
        move_in_date=opening.move_in_date,
        phase=phase,
        published_at=(
            as_utc(opening.published_at) if opening.published_at is not None else None
        ),
        submission_count=submission_count,
        selected_application_id=selected[0] if selected is not None else None,
        selected_applicant_name=selected[1] if selected is not None else None,
        no_household_selected=opening.no_household_selected,
        needs_decision=(
            not decision_exists and (
                (phase == OpeningPhase.PREPARING and opening.application_close_date < pacific_today())
                or (opening.move_in_date <= pacific_today() and submission_count > 0)
            )
        ),
        created_at=as_utc(opening.created_at),
        updated_at=as_utc(opening.updated_at),
    )


@router.post(
    "/previous-applicants/search",
    response_model=PreviousApplicantSearchOut,
)
def find_previous_applicants(
    body: PreviousApplicantSearch,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> PreviousApplicantSearchOut:
    return PreviousApplicantSearchOut(
        candidates=[
            OpeningSelectionCandidateOut(
                application_id=application.application_id,
                applicant_name=application.applicant_name,
                primary_email=application.primary_email,
            )
            for application in search_previous_applicants(db, body.query)
        ]
    )


@router.post("/{opening_id}/direct-selection", response_model=OpeningsResponse)
def add_direct_selection_opening(
    opening_id: int,
    body: OpeningSelectionRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> OpeningsResponse:
    select_previous_applicant(db, _opening(db, opening_id), body.application_id, decided_by=admin)
    return _response(db)


@router.get("", response_model=OpeningsResponse)
def read_openings(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> OpeningsResponse:
    return _response(db)


@router.post("/preview", response_model=OpeningPreviewOut)
def preview_opening(
    body: OpeningCreate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> OpeningPreviewOut:
    audience = opening_audience(db, body.unit_size_bedrooms)
    return _preview_out(audience)


@router.get("/email-usage", response_model=SocketLabsUsageOut)
def read_opening_email_usage(
    audience_count: int = Query(ge=0),
    _admin: User = Depends(require_admin),
    usage_reader: SocketLabsUsageReader = Depends(get_socketlabs_usage_reader),
) -> SocketLabsUsageOut:
    usage = usage_reader.fetch()
    if usage is None:
        return SocketLabsUsageOut(available=False)
    return SocketLabsUsageOut(
        available=True,
        retrieved_at=usage.retrieved_at,
        billing_period_start=usage.billing_period_start,
        billing_period_end=usage.billing_period_end,
        messages_used=usage.messages_used,
        message_allowance=usage.message_allowance,
        messages_used_percent=usage.messages_used_percent,
        allow_overages=usage.allow_overages,
        projected_messages_used=usage.messages_used + audience_count,
    )


@router.post("", response_model=OpeningCommitOut)
def add_opening(
    body: OpeningCreationRequest,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> OpeningCommitOut:
    lock_openings(db)
    require_admin_write(db, _admin.id)
    opening = created_request(db, body)
    if opening is not None:
        return OpeningCommitOut(openings=_response(db).openings,
            queued_notification_count=0)
    try:
        opening = create_opening(db, body,
            creation_request_id=str(body.creation_request_id),
            creation_request=creation_facts(body))
    except IntegrityError:
        db.rollback()
        # Reconcile a competing creation with the same request identity.
        opening = created_request(db, body)
        if opening is None:
            raise
        return OpeningCommitOut(openings=_response(db).openings,
            queued_notification_count=0)
    db.commit()
    response = _response(db)
    return OpeningCommitOut(
        openings=response.openings,
        queued_notification_count=0,
    )


@router.post("/{opening_id}/open", response_model=OpeningCommitOut)
def open_applications(
    opening_id: int, body: OpeningLaunchRequest, background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin), db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
    outbox_runner: Callable[[EmailSender], None] = Depends(get_outbox_runner),
) -> OpeningCommitOut:
    lock_openings(db)
    require_admin_write(db, admin.id)
    opening = _opening(db, opening_id)
    db.refresh(opening)
    if opening.decided_at is not None:
        raise Problem("invalid_settings", detail="This opening already has a final decision.")
    if opening.published_at is not None:
        return OpeningCommitOut(openings=_response(db).openings, queued_notification_count=0)
    if any(getattr(opening, field) != value for field, value in body.original.model_dump().items()):
        raise Problem("stale_opening", detail="This opening changed. Review its saved details before opening applications.")
    now = datetime.now(UTC)
    if opening.application_close_date < pacific_today(now=now):
        raise Problem("invalid_settings", detail="Extend the application deadline before opening applications.")
    audience = opening_audience(db, opening.unit_size_bedrooms)
    if body.expected_variants != _preview_out(audience).variants:
        raise Problem("opening_audience_changed", detail="The audience changed. Preview the opening again.", audienceCount=audience.total)
    publish_opening(db, opening, now=now)
    queue_opening_notifications(db, opening, audience)
    db.commit()
    background_tasks.add_task(outbox_runner, sender)
    return OpeningCommitOut(openings=_response(db).openings, queued_notification_count=audience.total)


@router.put("/{opening_id}", response_model=OpeningUpdatedOut)
def edit_opening(
    opening_id: int,
    body: OpeningUpdate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> OpeningUpdatedOut:
    lock_openings(db)
    require_admin_write(db, _admin.id)
    update_opening(db, _opening(db, opening_id), body)
    return OpeningUpdatedOut(
        openings=_response(db).openings,
        saved=OpeningDetailsOut(id=opening_id, **body.changes.model_dump()),
    )


def _preview_out(audience: VacancyAudience) -> OpeningPreviewOut:
    return OpeningPreviewOut(
        audience_count=audience.total,
        subscriber_only_count=len(audience.subscriber_only),
        application_only_count=len(audience.application_only),
        overlap_count=len(audience.overlaps),
        variants=[
            OpeningNotificationVariantOut(
                kind="notification_list",
                recipient_count=len(audience.subscriber_only),
            ),
            OpeningNotificationVariantOut(
                kind="current_application",
                recipient_count=len(audience.application_only),
            ),
            OpeningNotificationVariantOut(
                kind="application_and_notification_list",
                recipient_count=len(audience.overlaps),
            ),
        ],
    )


@router.get("/{opening_id}/selection", response_model=OpeningSelectionOut)
def read_opening_selection(
    opening_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> OpeningSelectionOut:
    return _selection_response(db, _opening(db, opening_id))


@router.post("/{opening_id}/selection", response_model=OpeningCommitOut)
def select_successful_applicant(
    opening_id: int, body: OpeningSelectionRequest, background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin), db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
    outbox_runner: Callable[[EmailSender], None] = Depends(get_outbox_runner),
) -> OpeningCommitOut:
    opening = _opening(db, opening_id)
    queued = confirm_opening_selection(db, opening, body.application_id, decided_by=admin)
    background_tasks.add_task(outbox_runner, sender)
    return OpeningCommitOut(openings=_response(db).openings, queued_notification_count=queued)


@router.post("/{opening_id}/selection/no-household", response_model=OpeningCommitOut)
def select_no_household(
    opening_id: int, background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin), db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
    outbox_runner: Callable[[EmailSender], None] = Depends(get_outbox_runner),
) -> OpeningCommitOut:
    opening = _opening(db, opening_id)
    queued = confirm_no_household_selected(db, opening, decided_by=admin)
    background_tasks.add_task(outbox_runner, sender)
    return OpeningCommitOut(openings=_response(db).openings, queued_notification_count=queued)


def _selection_response(db: Session, opening: Opening) -> OpeningSelectionOut:
    phase = opening_phase(opening)
    selected = retained_selected_households(db, [opening.id]).get(opening.id)
    participant_count, candidates = opening_candidate_summaries(db, opening)
    return OpeningSelectionOut(
        opening_id=opening.id,
        intake_mode=opening.intake_mode,
        phase=phase,
        selected_application_id=selected[0] if selected is not None else None,
        selected_applicant_name=selected[1] if selected is not None else None,
        no_household_selected=opening.no_household_selected,
        active_participant_count=participant_count,
        candidates=[
            OpeningSelectionCandidateOut(
                application_id=application.application_id,
                applicant_name=application.applicant_name,
                primary_email=application.primary_email,
            )
            for application in candidates
        ],
    )
