"""Per-member applicant stars (favourites).

A star is a personal working aid — a bookmark plus a "show only favourites" list
filter — private to the member, with no effect on ranking, eligibility, or reports.
The row's existence is the state (starred when present), so these are presence
reads; the write path (add/remove) lives in the applications router.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ApplicationStar


def is_starred(db: Session, application_id: int, user_id: int) -> bool:
    return (
        db.scalar(
            select(ApplicationStar.id).where(
                ApplicationStar.application_id == application_id,
                ApplicationStar.user_id == user_id,
            )
        )
        is not None
    )


def starred_ids(db: Session, user_id: int, application_ids: list[int]) -> set[int]:
    """The subset of `application_ids` the member has starred. Batch-fetched for a
    page of rows, mirroring `_latest_flags` — one query, not one per row."""
    if not application_ids:
        return set()
    return set(
        db.scalars(
            select(ApplicationStar.application_id).where(
                ApplicationStar.user_id == user_id,
                ApplicationStar.application_id.in_(application_ids),
            )
        ).all()
    )
