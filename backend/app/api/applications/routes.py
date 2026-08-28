
from fastapi import APIRouter, Depends
from sqlalchemy import select
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
from app.services.application_scope import committee_application, committee_applications
from app.services.direct_openings import available_previous_applicant
from app.services.eligibility import (
    active_flags,
    machine_flags_by_app,
    overrides_by_app,
    pet_facts_by_app,
)
from app.services.opening_participation import opening_ids_by_application
from app.services.openings import published_openings
from app.services.rules import (
    hard_filter_reasons_for,
    rules_config_for,
)
from app.services.stars import is_starred, starred_ids
from app.services.status_resolution import (
    findings_fingerprint,
)

router = APIRouter(prefix="/applications", tags=["applications"])


def _get_application_or_404(db: Session, application_id: int) -> Application:
    application = committee_application(db, application_id)
    if application is None:
        raise Problem("not_found", detail="Application not found.")
    return application


@router.get("", response_model=ApplicationListResponse)
def list_applications(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ApplicationListResponse:
    """Every application, unpaginated. A co-op pool is a few hundred rows at most, so
    the client holds the whole list and owns filtering, sorting, facet counts, and the
    favourites view — no server-side paging to keep consistent."""
    applications = committee_applications(db)
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
    overrides = overrides_by_app(db, user.id, ids)
    opening_ids = opening_ids_by_application(db, ids)
    # This member's rules are one ruleset, so resolve once and evaluate the hard filters
    # once per application — the reasons are computed on read (no stored column).
    rules_config = rules_config_for(db, user.id)
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
                opening_ids=opening_ids[app.id],
            )
            for app in applications
        ],
        openings=[committee_opening(opening) for opening in published_openings(db)],
    )


@router.get("/{application_id}", response_model=ApplicationEnvelope)
def get_application(
    application_id: int,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ApplicationEnvelope:
    application = _get_application_or_404(db, application_id)
    return ApplicationEnvelope(application=serialize_detail(application, db, user))


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
    return ApplicationEnvelope(application=serialize_detail(application, db, admin))


class StatusOverride(RequestModel):
    status: ApplicationStatus


@router.patch("/{application_id}/status", response_model=ApplicationEnvelope)
def override_status(
    application_id: int,
    body: StatusOverride,
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
    application = _get_application_or_404(db, application_id)
    rules_config = rules_config_for(db, user.id)
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
        )
    )
    if override is None:
        override = MemberEligibility(
            application_id=application_id,
            user_id=user.id,
            status=body.status,
            reviewed_fingerprint=fingerprint,
        )
        db.add(override)
    else:
        override.status = body.status
        override.reviewed_fingerprint = fingerprint
    db.commit()

    return ApplicationEnvelope(application=serialize_detail(application, db, user))


@router.delete("/{application_id}/status", response_model=ApplicationEnvelope)
def clear_status_override(
    application_id: int,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ApplicationEnvelope:
    """Remove this member's override, reverting their view to the machine verdict.

    The machine verdict is recomputed on read from the *current* findings (rules then
    AI), so the result can differ from the overridden value — which is the point of
    reverting to automatic. No-op if this member has no override.
    """
    application = _get_application_or_404(db, application_id)
    override = db.scalar(
        select(MemberEligibility).where(
            MemberEligibility.application_id == application_id,
            MemberEligibility.user_id == user.id,
        )
    )
    if override is not None:
        db.delete(override)
        db.commit()

    return ApplicationEnvelope(application=serialize_detail(application, db, user))


@router.put("/{application_id}/note", response_model=ApplicationEnvelope)
def save_private_note(
    application_id: int,
    body: PrivateNoteUpdate,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ApplicationEnvelope:
    """Create or replace the current member's private application note."""
    application = _get_application_or_404(db, application_id)
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

    return ApplicationEnvelope(application=serialize_detail(application, db, user))


@router.put("/{application_id}/star", response_model=ApplicationEnvelope)
def add_star(
    application_id: int,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ApplicationEnvelope:
    """Star (favourite) this applicant for the current member. Idempotent: the row's
    existence is the state, so re-starring is a no-op guarded by the unique
    constraint. A personal working aid — no effect on ranking, eligibility, or reports."""
    application = _get_application_or_404(db, application_id)
    if not is_starred(db, application_id, user.id):
        db.add(ApplicationStar(application_id=application_id, user_id=user.id))
        db.commit()

    return ApplicationEnvelope(application=serialize_detail(application, db, user))


@router.delete("/{application_id}/star", response_model=ApplicationEnvelope)
def remove_star(
    application_id: int,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ApplicationEnvelope:
    """Unstar this applicant for the current member. No-op if not starred."""
    application = _get_application_or_404(db, application_id)
    star = db.scalar(
        select(ApplicationStar).where(
            ApplicationStar.application_id == application_id,
            ApplicationStar.user_id == user.id,
        )
    )
    if star is not None:
        db.delete(star)
        db.commit()

    return ApplicationEnvelope(application=serialize_detail(application, db, user))
