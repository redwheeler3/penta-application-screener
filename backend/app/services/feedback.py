"""Member feedback: persistence for the from-any-page feedback channel.

A member submits free text; the caller stamps identity, app version, and the context
the member was in (route/tab/analysis). Reads are admin-only (enforced at the router).
Resolved items are retained, not deleted, so the friction history survives for mining.
"""

from __future__ import annotations

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session, joinedload

from app.db.models import Analysis, Application, Feedback, User, UserRole
from app.services.applications.retained_review import retained_review_applications_query
from app.services.applications.scope import (
    opening_applications_query,
    visible_committee_openings,
)


def create_feedback(
    db: Session,
    *,
    user: User,
    body: str,
    app_version: str,
    route: str | None,
    active_tab: str | None,
    analysis_id: int | None,
    applicant_id: int | None,
    opening_id: int | None,
    retained_review: bool,
) -> Feedback:
    """Persist one feedback item. Identity, version, and context come from the router
    (identity/version stamped server-side; context is what the client reported)."""
    opening_id, analysis_id, applicant_id, retained_review = normalize_context(
        db, user, opening_id, analysis_id, applicant_id, retained_review,
    )
    feedback = Feedback(
        user_id=user.id,
        body=body,
        app_version=app_version,
        route=route,
        active_tab=active_tab,
        analysis_id=analysis_id,
        applicant_id=applicant_id,
        opening_id=opening_id,
        retained_review=retained_review,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback


def list_feedback(db: Session, *, include_resolved: bool) -> list[Feedback]:
    """All feedback, newest first, with the submitting user eager-loaded (the admin list
    shows who sent it). Open-only by default; ``include_resolved`` widens to everything."""
    query = select(Feedback).options(joinedload(Feedback.user)).order_by(Feedback.id.desc())
    if not include_resolved:
        query = query.where(Feedback.resolved_at.is_(None))
    return list(db.scalars(query).all())


def normalize_context(
    db: Session, user: User, opening_id: int | None, analysis_id: int | None,
    applicant_id: int | None, retained_review: bool,
) -> tuple[int | None, int | None, int | None, bool]:
    """Discard unusable references without rejecting the member's feedback text."""
    visible_ids = {opening.id for opening in visible_committee_openings(db)}
    submitted_opening = opening_id
    opening_id = opening_id if opening_id in visible_ids else None
    if analysis_id is not None and (opening_id is None or db.scalar(
        select(Analysis.id).where(Analysis.id == analysis_id, Analysis.opening_id == opening_id)
    ) is None):
        analysis_id = None
    if applicant_id is not None:
        if retained_review or submitted_opening is None:
            allowed = user.role == UserRole.ADMIN and db.scalar(
                retained_review_applications_query().with_only_columns(Application.id)
                .where(Application.id == applicant_id)
            ) is not None
            retained_review = bool(allowed)
        else:
            allowed = opening_id is not None and db.scalar(
                opening_applications_query(opening_id).with_only_columns(Application.id)
                .where(Application.id == applicant_id)
            ) is not None
        if not allowed:
            applicant_id = None
    if applicant_id is None:
        retained_review = False
    if retained_review:
        opening_id, analysis_id = None, None
    return opening_id, analysis_id, applicant_id, retained_review


def applicant_names_for(db: Session, items: list[Feedback]) -> dict[int, str | None]:
    """Batch-project currently reviewable targets, keyed by feedback context identity.

    Membership in the mapping authorizes a link even when a visible applicant has no
    name. A missing target never reveals a private, expired, or withdrawn name.
    """
    if not items:
        return {}
    visible_ids = [opening.id for opening in visible_committee_openings(db)]
    ordinary = opening_applications_query(Feedback.opening_id).with_only_columns(Application.id)
    # The nested pool must correlate to the feedback row, not to the outer applicant.
    ordinary = ordinary.correlate(Feedback)
    retained = retained_review_applications_query().with_only_columns(Application.id)
    rows = db.execute(select(Feedback.id, Application.applicant_name)
        .join(Application, Application.id == Feedback.applicant_id)
        .where(Feedback.id.in_([item.id for item in items]), or_(
            and_(Feedback.retained_review.is_(False), Feedback.opening_id.in_(visible_ids),
                 Application.id.in_(ordinary)),
            and_(or_(Feedback.retained_review.is_(True), Feedback.opening_id.is_(None)),
                 Application.id.in_(retained)),
        )))
    return dict(rows.all())


def resolve_feedback(db: Session, feedback_id: int) -> Feedback | None:
    """Mark an item handled (idempotent — re-resolving keeps the original timestamp).
    Returns None if the id doesn't exist so the router can 404."""
    db.execute(update(Feedback).where(Feedback.id == feedback_id, Feedback.resolved_at.is_(None))
        .values(resolved_at=func.now()).execution_options(synchronize_session=False))
    db.commit()
    return db.get(Feedback, feedback_id, populate_existing=True)


def reopen_feedback(db: Session, feedback_id: int) -> Feedback | None:
    """Clear an item's resolved stamp, moving it back to the open list. Returns None if
    the id doesn't exist."""
    db.execute(update(Feedback).where(Feedback.id == feedback_id).values(resolved_at=None)
        .execution_options(synchronize_session=False))
    db.commit()
    return db.get(Feedback, feedback_id, populate_existing=True)
