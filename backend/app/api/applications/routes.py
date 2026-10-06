from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.applications.presentation import (
    committee_notes,
    committee_opening,
    eligibility_update,
    serialize_detail,
    serialize_summary,
)
from app.api.dependencies import require_admin, require_current_user
from app.core.problems import Problem
from app.core.time import as_utc
from app.db.models import (
    Application,
    ApplicationCommitteeNote,
    ApplicationNote,
    ApplicationParticipation,
    ApplicationShortlist,
    ApplicationStar,
    ApplicationStatus,
    MemberEligibility,
    OpeningOutcome,
    User,
)
from app.db.session import get_db
from app.schemas.applications import (
    ApplicationEnvelope,
    ApplicationListResponse,
    CommitteeNoteCreate,
    CommitteeNotesResponse,
    CommitteeNoteWrite,
    EligibilityResponse,
    FavouriteResponse,
    PrivateNoteResponse,
    PrivateNoteUpdate,
    ShortlistResponse,
)
from app.schemas.base import RequestModel
from app.services.applications.locking import lock_application
from app.services.applications.retention import retention_is_current
from app.services.applications.scope import (
    opening_ai_applications_query,
    opening_application,
    opening_applications,
    resolve_visible_opening_id,
    visible_committee_openings,
)
from app.services.applications.screening_results import screening_findings_by_app
from app.services.applications.shared_shortlist import is_shortlisted, shortlisted_ids
from app.services.applications.stars import is_starred, starred_ids
from app.services.eligibility.evaluation import (
    active_flags,
    overrides_by_app,
)
from app.services.eligibility.rules import (
    hard_filter_reasons_for,
    rules_config_for,
)
from app.services.eligibility.status import (
    findings_fingerprint,
)
from app.services.openings.catalog import opening_phase
from app.services.openings.direct_selection import available_previous_applicant

router = APIRouter(prefix="/applications", tags=["applications"])


def _get_application_or_404(
    db: Session, opening_id: int, application_id: int
) -> Application:
    application = opening_application(db, opening_id, application_id)
    if application is None:
        raise Problem("not_found", detail="Application not found.")
    return application


def _lock_mutable_application_or_404(
    db: Session, opening_id: int, application_id: int
) -> Application:
    lock_application(db, application_id)
    application = db.scalar(
        opening_ai_applications_query(opening_id).where(Application.id == application_id)
    )
    if application is None:
        raise Problem("not_found", detail="Application not found.")
    return application


def _application_envelope(
    application: Application,
    db: Session,
    user: User,
    opening_id: int,
) -> ApplicationEnvelope:
    detail = serialize_detail(application, db, user, opening_id)
    return ApplicationEnvelope(application=detail)


@router.get("", response_model=ApplicationListResponse)
def list_applications(
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ApplicationListResponse:
    """Every application, unpaginated. A co-op pool is a few hundred rows at most, so
    the client holds the whole list and owns filtering, sorting, facet counts, and the
    favourites view — no server-side paging to keep consistent."""
    openings = visible_committee_openings(db)
    valid_ids = {opening.id for opening in openings}
    if opening_id not in valid_ids:
        current = [
            opening
            for opening in openings
            if opening_phase(opening).value != "archived"
        ]
        selected_opening = current[0] if current else (openings[-1] if openings else None)
        opening_id = selected_opening.id if selected_opening is not None else None
    applications = opening_applications(db, opening_id) if opening_id is not None else []
    applications.sort(
        key=lambda application: (
            as_utc(application.submitted_at).timestamp()
            if application.submitted_at is not None
            else 0
        ),
        reverse=True,
    )
    ids = [app.id for app in applications]
    flags, facts = screening_findings_by_app(db, ids)
    starred = starred_ids(db, user.id, ids)
    shortlisted = shortlisted_ids(db, opening_id, ids) if opening_id is not None else set()
    selected = set(db.scalars(select(ApplicationParticipation.application_id).where(
        ApplicationParticipation.opening_id == opening_id,
        ApplicationParticipation.application_id.in_(ids),
        ApplicationParticipation.outcome == OpeningOutcome.SELECTED,
    ))) if ids else set()
    overrides = (
        overrides_by_app(db, user.id, opening_id, ids)
        if opening_id is not None
        else {}
    )
    # This member's rules are one ruleset, so resolve once and evaluate the hard filters
    # once per application — the reasons are computed on read (no stored column).
    rules_config = rules_config_for(db, user.id, opening_id) if opening_id is not None else None
    return ApplicationListResponse(
        applications=[
            serialize_summary(
                app,
                reasons=hard_filter_reasons_for(
                    rules_config,
                    app,
                    pet_facts=facts.get(app.id),
                ),
                override=overrides.get(app.id),
                # Active flags drive both status and display; muted categories do neither.
                flags=active_flags(flags.get(app.id), rules_config.disabled_checks),
                starred=app.id in starred,
                shortlisted=app.id in shortlisted,
                opening_ids=[opening_id],
                selected=app.id in selected,
            )
            for app in applications
        ],
        openings=[committee_opening(opening) for opening in openings],
        selected_opening_id=opening_id,
    )


@router.get("/{application_id}", response_model=ApplicationEnvelope)
def get_application(
    application_id: int,
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ApplicationEnvelope:
    opening_id = resolve_visible_opening_id(db, opening_id)
    application = _get_application_or_404(db, opening_id, application_id)
    return _application_envelope(application, db, user, opening_id)


@router.get("/{application_id}/retained", response_model=ApplicationEnvelope)
def get_retained_application(
    application_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ApplicationEnvelope:
    """Read a selected or direct-fill-eligible application outside ordinary scope."""
    application = db.get(Application, application_id)
    selected = db.scalar(
        select(ApplicationParticipation.id).where(
            ApplicationParticipation.application_id == application_id,
            ApplicationParticipation.outcome == OpeningOutcome.SELECTED,
        )
    )
    available_for_direct_fill = available_previous_applicant(db, application_id)
    if application is None or not retention_is_current(application) or (selected is None and available_for_direct_fill is None):
        raise Problem("not_found", detail="Retained application not found.")
    context_opening_id = db.scalar(
        select(ApplicationParticipation.opening_id)
        .where(ApplicationParticipation.application_id == application_id)
        .order_by(ApplicationParticipation.id.desc())
        .limit(1)
    )
    if context_opening_id is None:
        raise Problem("not_found", detail="Retained application has no opening context.")
    return _application_envelope(application, db, admin, context_opening_id)


class StatusOverride(RequestModel):
    status: ApplicationStatus


@router.patch("/{application_id}/status", response_model=EligibilityResponse)
def override_status(
    application_id: int,
    body: StatusOverride,
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> EligibilityResponse:
    """This member's human override of an application's eligibility.

    Any committee member may set their own status. Upserts a ``MemberEligibility`` row
    (the row's existence IS the human override) and snapshots the current findings
    fingerprint, so later runs that change the findings mark the override stale. The
    override is per-member — it never changes the shared machine baseline or anyone
    else's view.
    """
    opening_id = resolve_visible_opening_id(db, opening_id)
    application = _lock_mutable_application_or_404(db, opening_id, application_id)
    rules_config = rules_config_for(db, user.id, opening_id)
    flags_by_app, facts_by_app = screening_findings_by_app(db, [application_id])
    flags = active_flags(flags_by_app.get(application_id), rules_config.disabled_checks)
    pet_facts = facts_by_app.get(application_id)
    reasons = hard_filter_reasons_for(
        rules_config,
        application,
        pet_facts=pet_facts,
    )
    fingerprint = findings_fingerprint(reasons, flags)
    override = db.scalar(
        select(MemberEligibility).where(
            MemberEligibility.application_id == application_id,
            MemberEligibility.user_id == user.id,
            MemberEligibility.opening_id == opening_id,
        )
    )
    if override is None:
        override = MemberEligibility(
            application_id=application_id,
            user_id=user.id,
            opening_id=opening_id,
            status=body.status,
            reviewed_fingerprint=fingerprint,
        )
        db.add(override)
    else:
        override.status = body.status
        override.reviewed_fingerprint = fingerprint
    db.commit()

    return EligibilityResponse(application=eligibility_update(application, db, user, opening_id))


@router.delete("/{application_id}/status", response_model=EligibilityResponse)
def clear_status_override(
    application_id: int,
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> EligibilityResponse:
    """Remove this member's override, reverting their view to the machine verdict.

    The machine verdict is recomputed on read from the *current* findings (rules then
    AI), so the result can differ from the overridden value — which is the point of
    reverting to automatic. No-op if this member has no override.
    """
    opening_id = resolve_visible_opening_id(db, opening_id)
    application = _lock_mutable_application_or_404(db, opening_id, application_id)
    override = db.scalar(
        select(MemberEligibility).where(
            MemberEligibility.application_id == application_id,
            MemberEligibility.user_id == user.id,
            MemberEligibility.opening_id == opening_id,
        )
    )
    if override is not None:
        db.delete(override)
        db.commit()

    return EligibilityResponse(application=eligibility_update(application, db, user, opening_id))


@router.put("/{application_id}/note", response_model=PrivateNoteResponse)
def save_private_note(
    application_id: int,
    body: PrivateNoteUpdate,
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> PrivateNoteResponse:
    """Create or replace the current member's private application note."""
    opening_id = resolve_visible_opening_id(db, opening_id)
    _lock_mutable_application_or_404(db, opening_id, application_id)
    note = db.scalar(
        select(ApplicationNote).where(
            ApplicationNote.application_id == application_id,
            ApplicationNote.user_id == user.id,
        )
    )
    if note is None:
        note = ApplicationNote(application_id=application_id, user_id=user.id, note=body.note)
        db.add(note)
    else:
        note.note = body.note
    db.commit()

    return PrivateNoteResponse(application={"id": application_id, "private_note": body.note})


def _committee_note_or_404(
    db: Session, application_id: int, note_id: int, *, include_deleted: bool = False
) -> ApplicationCommitteeNote:
    note = db.scalar(
        select(ApplicationCommitteeNote).where(
            ApplicationCommitteeNote.id == note_id,
            ApplicationCommitteeNote.application_id == application_id,
            True if include_deleted else ApplicationCommitteeNote.deleted_at.is_(None),
        )
    )
    if note is None:
        raise Problem("not_found", detail="Committee note not found.")
    return note


def _require_committee_note_author(
    note: ApplicationCommitteeNote, user: User
) -> None:
    if note.author_user_id != user.id:
        raise Problem(
            "forbidden",
            title="Cannot change this committee note",
            detail="Only the member who added this note can change it.",
        )


@router.post("/{application_id}/committee-notes", response_model=CommitteeNotesResponse)
def add_committee_note(
    application_id: int,
    body: CommitteeNoteCreate,
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> CommitteeNotesResponse:
    """Add one attributed application-wide note visible to the committee."""
    opening_id = resolve_visible_opening_id(db, opening_id)
    _lock_mutable_application_or_404(db, opening_id, application_id)
    existing = db.scalar(select(ApplicationCommitteeNote).where(
        ApplicationCommitteeNote.application_id == application_id,
        ApplicationCommitteeNote.author_user_id == user.id,
        ApplicationCommitteeNote.creation_key == str(body.creation_key),
    ))
    if existing is None:
        db.add(ApplicationCommitteeNote(
            application_id=application_id, author_user_id=user.id,
            body=body.body, creation_key=str(body.creation_key),
        ))
    db.commit()
    return CommitteeNotesResponse(application={
        "id": application_id, "committee_notes": committee_notes(db, application_id, user.id),
    })


@router.patch(
    "/{application_id}/committee-notes/{note_id}",
    response_model=CommitteeNotesResponse,
)
def update_committee_note(
    application_id: int,
    note_id: int,
    body: CommitteeNoteWrite,
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> CommitteeNotesResponse:
    opening_id = resolve_visible_opening_id(db, opening_id)
    _lock_mutable_application_or_404(db, opening_id, application_id)
    note = _committee_note_or_404(db, application_id, note_id)
    _require_committee_note_author(note, user)
    note.body = body.body
    db.commit()
    return CommitteeNotesResponse(application={
        "id": application_id, "committee_notes": committee_notes(db, application_id, user.id),
    })


@router.delete(
    "/{application_id}/committee-notes/{note_id}",
    response_model=CommitteeNotesResponse,
)
def delete_committee_note(
    application_id: int,
    note_id: int,
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> CommitteeNotesResponse:
    opening_id = resolve_visible_opening_id(db, opening_id)
    _lock_mutable_application_or_404(db, opening_id, application_id)
    note = _committee_note_or_404(db, application_id, note_id, include_deleted=True)
    _require_committee_note_author(note, user)
    if note.creation_key is None:
        db.delete(note)
    elif note.deleted_at is None:
        note.body = ""
        note.deleted_at = datetime.now(UTC)
    db.commit()
    return CommitteeNotesResponse(application={
        "id": application_id, "committee_notes": committee_notes(db, application_id, user.id),
    })


@router.put("/{application_id}/star", response_model=FavouriteResponse)
def add_star(
    application_id: int,
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> FavouriteResponse:
    """Star (favourite) this applicant for the current member. Idempotent: the row's
    existence is the state, so re-starring is a no-op guarded by the unique
    constraint. A personal working aid — no effect on ranking, eligibility, or reports."""
    opening_id = resolve_visible_opening_id(db, opening_id)
    _lock_mutable_application_or_404(db, opening_id, application_id)
    if not is_starred(db, application_id, user.id):
        db.add(ApplicationStar(application_id=application_id, user_id=user.id))
        db.commit()

    return FavouriteResponse(application={"id": application_id, "starred_by_me": True})


@router.delete("/{application_id}/star", response_model=FavouriteResponse)
def remove_star(
    application_id: int,
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> FavouriteResponse:
    """Unstar this applicant for the current member. No-op if not starred."""
    opening_id = resolve_visible_opening_id(db, opening_id)
    _lock_mutable_application_or_404(db, opening_id, application_id)
    star = db.scalar(
        select(ApplicationStar).where(
            ApplicationStar.application_id == application_id,
            ApplicationStar.user_id == user.id,
        )
    )
    if star is not None:
        db.delete(star)
        db.commit()

    return FavouriteResponse(application={"id": application_id, "starred_by_me": False})


@router.put("/{application_id}/shortlist", response_model=ShortlistResponse)
def add_to_shortlist(
    application_id: int,
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ShortlistResponse:
    """Add an applicant to the committee's shared shortlist, idempotently."""
    opening_id = resolve_visible_opening_id(db, opening_id)
    _lock_mutable_application_or_404(db, opening_id, application_id)
    if not is_shortlisted(db, opening_id, application_id):
        db.add(
            ApplicationShortlist(
                opening_id=opening_id,
                application_id=application_id,
                added_by_user_id=user.id,
            )
        )
        try:
            db.commit()
        except IntegrityError:
            # Another member added the same shared row between our read and write.
            # The requested state already exists, so preserve idempotent PUT semantics.
            db.rollback()
    return ShortlistResponse(application={"id": application_id, "shortlisted": True})


@router.delete("/{application_id}/shortlist", response_model=ShortlistResponse)
def remove_from_shortlist(
    application_id: int,
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ShortlistResponse:
    """Remove an applicant from the committee's shared shortlist, idempotently."""
    opening_id = resolve_visible_opening_id(db, opening_id)
    _lock_mutable_application_or_404(db, opening_id, application_id)
    db.execute(
        delete(ApplicationShortlist).where(
            ApplicationShortlist.opening_id == opening_id,
            ApplicationShortlist.application_id == application_id
        )
    )
    db.commit()
    return ShortlistResponse(application={"id": application_id, "shortlisted": False})
