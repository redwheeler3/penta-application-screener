"""Member feedback: persistence for the from-any-page feedback channel.

A member submits free text; the caller stamps identity, app version, and the context
the member was in (route/tab/analysis). Reads are admin-only (enforced at the router).
Resolved items are retained, not deleted, so the friction history survives for mining.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import Application, Feedback


def create_feedback(
    db: Session,
    *,
    user_id: int,
    body: str,
    app_version: str,
    route: str | None,
    active_tab: str | None,
    analysis_id: int | None,
    applicant_id: int | None,
) -> Feedback:
    """Persist one feedback item. Identity, version, and context come from the router
    (identity/version stamped server-side; context is what the client reported)."""
    feedback = Feedback(
        user_id=user_id,
        body=body,
        app_version=app_version,
        route=route,
        active_tab=active_tab,
        analysis_id=analysis_id,
        applicant_id=applicant_id,
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


def applicant_names_for(db: Session, items: list[Feedback]) -> dict[int, str]:
    """Current applicant names for the items that carry an ``applicant_id``, batch-loaded
    in one query — ``{applicant_id: name}``. An id whose applicant was since removed is
    simply absent (the caller reads it as "no name"). Off the N+1 path for the list view."""
    ids = {f.applicant_id for f in items if f.applicant_id is not None}
    if not ids:
        return {}
    rows = db.execute(
        select(Application.id, Application.applicant_name).where(Application.id.in_(ids))
    )
    return {app_id: name for app_id, name in rows if name is not None}


def resolve_feedback(db: Session, feedback_id: int) -> Feedback | None:
    """Mark an item handled (idempotent — re-resolving keeps the original timestamp).
    Returns None if the id doesn't exist so the router can 404."""
    feedback = db.get(Feedback, feedback_id)
    if feedback is None:
        return None
    if feedback.resolved_at is None:
        feedback.resolved_at = func.now()
        db.commit()
        db.refresh(feedback)
    return feedback


def reopen_feedback(db: Session, feedback_id: int) -> Feedback | None:
    """Clear an item's resolved stamp, moving it back to the open list. Returns None if
    the id doesn't exist."""
    feedback = db.get(Feedback, feedback_id)
    if feedback is None:
        return None
    if feedback.resolved_at is not None:
        feedback.resolved_at = None
        db.commit()
        db.refresh(feedback)
    return feedback
