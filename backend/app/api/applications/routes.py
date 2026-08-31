
from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.applications.presentation import (
    committee_opening,
    serialize_detail,
    serialize_summary,
)
from app.api.dependencies import require_admin, require_current_user
from app.core.problems import Problem
from app.core.time import as_utc
from app.db.models import (
    Application,
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
    PrivateNoteUpdate,
)
from app.schemas.base import RequestModel
from app.services.application_scope import (
    opening_ai_applications_query,
    opening_application,
    opening_applications,
    resolve_visible_opening_id,
    visible_committee_openings,
)
from app.services.direct_openings import available_previous_applicant
from app.services.eligibility import (
    active_flags,
    machine_flags_by_app,
    overrides_by_app,
    pet_facts_by_app,
)
from app.services.openings import opening_phase
from app.services.rules import (
    hard_filter_reasons_for,
    rules_config_for,
)
from app.services.shared_shortlist import is_shortlisted, shortlisted_ids
from app.services.stars import is_starred, starred_ids
from app.services.status_resolution import (
    findings_fingerprint,
)

router = APIRouter(prefix="/applications", tags=["applications"])


def _get_application_or_404(
    db: Session, opening_id: int, application_id: int
) -> Application:
    application = opening_application(db, opening_id, application_id)
    if application is None:
        raise Problem("not_found", detail="Application not found.")
    return application


def _get_mutable_application_or_404(
    db: Session, opening_id: int, application_id: int
) -> Application:
    application = db.scalar(
        opening_ai_applications_query(opening_id).where(Application.id == application_id)
    )
    if application is None:
        raise Problem("not_found", detail="Application not found.")
    return application


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
    flags = machine_flags_by_app(db, ids)
    facts = pet_facts_by_app(db, ids)
    starred = starred_ids(db, user.id, ids)
    shortlisted = shortlisted_ids(db, opening_id, ids) if opening_id is not None else set()
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
                selected=(
                    db.scalar(
                        select(ApplicationParticipation.id).where(
                            ApplicationParticipation.application_id == app.id,
                            ApplicationParticipation.opening_id == opening_id,
                            ApplicationParticipation.outcome == OpeningOutcome.SELECTED,
                        )
                    )
                    is not None
                ),
            )
            for app in applications
        ],
        openings=[committee_opening(db, opening) for opening in openings],
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
    return ApplicationEnvelope(
        application=serialize_detail(application, db, user, opening_id)
    )


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
    if application is None or (selected is None and available_for_direct_fill is None):
        raise Problem("not_found", detail="Retained application not found.")
    context_opening_id = db.scalar(
        select(ApplicationParticipation.opening_id)
        .where(ApplicationParticipation.application_id == application_id)
        .order_by(ApplicationParticipation.id.desc())
        .limit(1)
    )
    if context_opening_id is None:
        raise Problem("not_found", detail="Retained application has no opening context.")
    return ApplicationEnvelope(
        application=serialize_detail(application, db, admin, context_opening_id)
    )


class StatusOverride(RequestModel):
    status: ApplicationStatus


@router.patch("/{application_id}/status", response_model=ApplicationEnvelope)
def override_status(
    application_id: int,
    body: StatusOverride,
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ApplicationEnvelope:
    """This member's human override of an application's eligibility.

    Any committee member may set their own status. Upserts a ``MemberEligibility`` row
    (the row's existence IS the human override) and snapshots the current findings
    fingerprint, so later runs that change the findings mark the override stale. The
    override is per-member — it never changes the shared machine baseline or anyone
    else's view.
    """
    opening_id = resolve_visible_opening_id(db, opening_id)
    application = _get_mutable_application_or_404(db, opening_id, application_id)
    rules_config = rules_config_for(db, user.id, opening_id)
    flags = active_flags(machine_flags_by_app(db, [application_id]).get(application_id), rules_config.disabled_checks)
    pet_facts = pet_facts_by_app(db, [application_id]).get(application_id)
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

    return ApplicationEnvelope(
        application=serialize_detail(application, db, user, opening_id)
    )


@router.delete("/{application_id}/status", response_model=ApplicationEnvelope)
def clear_status_override(
    application_id: int,
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ApplicationEnvelope:
    """Remove this member's override, reverting their view to the machine verdict.

    The machine verdict is recomputed on read from the *current* findings (rules then
    AI), so the result can differ from the overridden value — which is the point of
    reverting to automatic. No-op if this member has no override.
    """
    opening_id = resolve_visible_opening_id(db, opening_id)
    application = _get_mutable_application_or_404(db, opening_id, application_id)
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

    return ApplicationEnvelope(
        application=serialize_detail(application, db, user, opening_id)
    )


@router.put("/{application_id}/note", response_model=ApplicationEnvelope)
def save_private_note(
    application_id: int,
    body: PrivateNoteUpdate,
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ApplicationEnvelope:
    """Create or replace the current member's private application note."""
    opening_id = resolve_visible_opening_id(db, opening_id)
    application = _get_mutable_application_or_404(db, opening_id, application_id)
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

    return ApplicationEnvelope(
        application=serialize_detail(application, db, user, opening_id)
    )


@router.put("/{application_id}/star", response_model=ApplicationEnvelope)
def add_star(
    application_id: int,
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ApplicationEnvelope:
    """Star (favourite) this applicant for the current member. Idempotent: the row's
    existence is the state, so re-starring is a no-op guarded by the unique
    constraint. A personal working aid — no effect on ranking, eligibility, or reports."""
    opening_id = resolve_visible_opening_id(db, opening_id)
    application = _get_mutable_application_or_404(db, opening_id, application_id)
    if not is_starred(db, application_id, user.id):
        db.add(ApplicationStar(application_id=application_id, user_id=user.id))
        db.commit()

    return ApplicationEnvelope(
        application=serialize_detail(application, db, user, opening_id)
    )


@router.delete("/{application_id}/star", response_model=ApplicationEnvelope)
def remove_star(
    application_id: int,
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ApplicationEnvelope:
    """Unstar this applicant for the current member. No-op if not starred."""
    opening_id = resolve_visible_opening_id(db, opening_id)
    application = _get_mutable_application_or_404(db, opening_id, application_id)
    star = db.scalar(
        select(ApplicationStar).where(
            ApplicationStar.application_id == application_id,
            ApplicationStar.user_id == user.id,
        )
    )
    if star is not None:
        db.delete(star)
        db.commit()

    return ApplicationEnvelope(
        application=serialize_detail(application, db, user, opening_id)
    )


@router.put("/{application_id}/shortlist", response_model=ApplicationEnvelope)
def add_to_shortlist(
    application_id: int,
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ApplicationEnvelope:
    """Add an applicant to the committee's shared shortlist, idempotently."""
    opening_id = resolve_visible_opening_id(db, opening_id)
    application = _get_mutable_application_or_404(db, opening_id, application_id)
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
    return ApplicationEnvelope(
        application=serialize_detail(application, db, user, opening_id)
    )


@router.delete("/{application_id}/shortlist", response_model=ApplicationEnvelope)
def remove_from_shortlist(
    application_id: int,
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ApplicationEnvelope:
    """Remove an applicant from the committee's shared shortlist, idempotently."""
    opening_id = resolve_visible_opening_id(db, opening_id)
    application = _get_mutable_application_or_404(db, opening_id, application_id)
    db.execute(
        delete(ApplicationShortlist).where(
            ApplicationShortlist.opening_id == opening_id,
            ApplicationShortlist.application_id == application_id
        )
    )
    db.commit()
    return ApplicationEnvelope(
        application=serialize_detail(application, db, user, opening_id)
    )
