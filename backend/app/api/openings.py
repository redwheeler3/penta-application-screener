"""Admin-only opening configuration and lifecycle endpoints."""

from collections.abc import Callable

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.core.problems import Problem
from app.db.models import Application, Opening, User
from app.db.session import get_db
from app.schemas.openings import (
    DirectSelectionOpeningCreate,
    OpeningCreate,
    OpeningCreateConfirmation,
    OpeningCreatedOut,
    OpeningNotificationVariantOut,
    OpeningOut,
    OpeningPreviewOut,
    OpeningSelectionCandidateOut,
    OpeningSelectionOut,
    OpeningSelectionRequest,
    OpeningsResponse,
    OpeningWrite,
    PreviousApplicantSearch,
    PreviousApplicantSearchOut,
    SocketLabsUsageOut,
)
from app.services.direct_openings import (
    create_direct_selection_opening,
    remove_direct_selection_opening,
    search_previous_applicants,
)
from app.services.email_sender import EmailSender, get_email_sender
from app.services.maintenance import run_email_outbox
from app.services.opening_notifications import send_due_unsuccessful_notices
from app.services.opening_selection import (
    active_opening_participants,
    confirm_no_household_selected,
    confirm_opening_selection,
    selectable_opening_candidates,
    selected_participation,
    undo_opening_selection,
)
from app.services.openings import (
    create_opening,
    list_openings,
    opening_phase,
    update_opening,
)
from app.services.passwordless_auth import as_utc
from app.services.socketlabs_usage import (
    SocketLabsUsageReader,
    get_socketlabs_usage_reader,
)
from app.services.vacancy_notifications import (
    VacancyAudience,
    opening_audience,
    queue_opening_notifications,
)

router = APIRouter(prefix="/openings", tags=["openings"])


def get_outbox_runner() -> Callable[[EmailSender], None]:
    return run_email_outbox


def _opening(db: Session, opening_id: int) -> Opening:
    opening = db.get(Opening, opening_id)
    if opening is None:
        raise Problem("not_found", detail="Opening not found.")
    return opening


def _response(db: Session) -> OpeningsResponse:
    return OpeningsResponse(
        openings=[
            _opening_out(db, opening, submission_count)
            for opening, submission_count in list_openings(db)
        ]
    )


def _opening_out(db: Session, opening: Opening, submission_count: int) -> OpeningOut:
    selected = selected_participation(db, opening.id)
    selected_application = (
        db.get(Application, selected.application_id) if selected is not None else None
    )
    phase = opening_phase(opening)
    decision_exists = selected is not None or opening.no_household_selected_at is not None
    return OpeningOut(
        id=opening.id,
        intake_mode=opening.intake_mode,
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
        selected_application_id=selected.application_id if selected is not None else None,
        selected_applicant_name=(
            selected_application.applicant_name if selected_application is not None else None
        ),
        no_household_selected=opening.no_household_selected_at is not None,
        decision_permanent=phase.value == "archived" and decision_exists,
        needs_decision=(
            phase.value == "archived"
            and not decision_exists
            and submission_count > 0
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
                application_id=application.id,
                applicant_name=application.applicant_name,
                primary_email=application.primary_email,
            )
            for application in search_previous_applicants(db, body.query)
        ]
    )


@router.post("/direct-selection", response_model=OpeningsResponse)
def add_direct_selection_opening(
    body: DirectSelectionOpeningCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> OpeningsResponse:
    create_direct_selection_opening(db, body, decided_by=admin)
    return _response(db)


@router.delete("/{opening_id}/direct-selection", response_model=OpeningsResponse)
def delete_direct_selection_opening(
    opening_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> OpeningsResponse:
    remove_direct_selection_opening(db, _opening(db, opening_id))
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
    usage_reader: SocketLabsUsageReader = Depends(get_socketlabs_usage_reader),
) -> OpeningPreviewOut:
    audience = opening_audience(db, body.unit_size_bedrooms)
    return _preview_out(audience, usage_reader)


@router.post("", response_model=OpeningCreatedOut)
def add_opening(
    body: OpeningCreateConfirmation,
    background_tasks: BackgroundTasks,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
    outbox_runner: Callable[[EmailSender], None] = Depends(get_outbox_runner),
) -> OpeningCreatedOut:
    audience = opening_audience(db, body.unit_size_bedrooms)
    if audience.total != body.expected_audience_count:
        raise Problem(
            "opening_audience_changed",
            detail="The audience changed while you were reviewing it. Preview the opening again.",
            audienceCount=audience.total,
        )
    opening = create_opening(db, body)
    queue_opening_notifications(db, opening, audience)
    db.commit()
    response = _response(db)
    background_tasks.add_task(outbox_runner, sender)
    return OpeningCreatedOut(
        openings=response.openings,
        queued_notification_count=audience.total,
    )


@router.put("/{opening_id}", response_model=OpeningsResponse)
def edit_opening(
    opening_id: int,
    body: OpeningWrite,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> OpeningsResponse:
    update_opening(db, _opening(db, opening_id), body)
    return _response(db)


def _preview_out(
    audience: VacancyAudience,
    usage_reader: SocketLabsUsageReader,
) -> OpeningPreviewOut:
    usage = usage_reader.fetch()
    socketlabs = SocketLabsUsageOut(available=False)
    if usage is not None:
        socketlabs = SocketLabsUsageOut(
            available=True,
            retrieved_at=usage.retrieved_at,
            billing_period_start=usage.billing_period_start,
            billing_period_end=usage.billing_period_end,
            messages_used=usage.messages_used,
            message_allowance=usage.message_allowance,
            messages_used_percent=usage.messages_used_percent,
            allow_overages=usage.allow_overages,
            projected_messages_used=usage.messages_used + audience.total,
        )
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
        socketlabs=socketlabs,
    )


@router.get("/{opening_id}/selection", response_model=OpeningSelectionOut)
def read_opening_selection(
    opening_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> OpeningSelectionOut:
    return _selection_response(db, _opening(db, opening_id))


@router.post("/{opening_id}/selection", response_model=OpeningSelectionOut)
def select_successful_applicant(
    opening_id: int,
    body: OpeningSelectionRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
) -> OpeningSelectionOut:
    opening = _opening(db, opening_id)
    confirm_opening_selection(
        db,
        opening,
        body.application_id,
        decided_by=admin,
    )
    send_due_unsuccessful_notices(db, sender)
    return _selection_response(db, opening)


@router.post("/{opening_id}/selection/no-household", response_model=OpeningSelectionOut)
def select_no_household(
    opening_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
) -> OpeningSelectionOut:
    opening = _opening(db, opening_id)
    confirm_no_household_selected(db, opening, decided_by=admin)
    send_due_unsuccessful_notices(db, sender)
    return _selection_response(db, opening)


@router.delete("/{opening_id}/selection", response_model=OpeningSelectionOut)
def undo_successful_applicant(
    opening_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> OpeningSelectionOut:
    opening = _opening(db, opening_id)
    undo_opening_selection(db, opening)
    return _selection_response(db, opening)


def _selection_response(db: Session, opening: Opening) -> OpeningSelectionOut:
    phase = opening_phase(opening)
    selected = selected_participation(db, opening.id)
    participants = active_opening_participants(db, opening)
    selected_application = (
        db.get(Application, selected.application_id) if selected is not None else None
    )
    decision_exists = selected is not None or opening.no_household_selected_at is not None
    return OpeningSelectionOut(
        opening_id=opening.id,
        intake_mode=opening.intake_mode,
        phase=phase,
        selected_application_id=selected.application_id if selected is not None else None,
        selected_applicant_name=(
            selected_application.applicant_name if selected_application is not None else None
        ),
        no_household_selected=opening.no_household_selected_at is not None,
        decision_permanent=phase.value == "archived" and decision_exists,
        active_participant_count=len(participants),
        candidates=[
            OpeningSelectionCandidateOut(
                application_id=application.id,
                applicant_name=application.applicant_name,
                primary_email=application.primary_email,
            )
            for _, application in selectable_opening_candidates(db, opening)
        ],
    )
