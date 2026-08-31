"""Committee-shared shortlist membership."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ApplicationShortlist


def is_shortlisted(db: Session, opening_id: int, application_id: int) -> bool:
    return (
        db.scalar(
            select(ApplicationShortlist.id).where(
                ApplicationShortlist.application_id == application_id
                , ApplicationShortlist.opening_id == opening_id
            )
        )
        is not None
    )


def shortlisted_ids(
    db: Session, opening_id: int, application_ids: list[int]
) -> set[int]:
    if not application_ids:
        return set()
    return set(
        db.scalars(
            select(ApplicationShortlist.application_id).where(
                ApplicationShortlist.opening_id == opening_id,
                ApplicationShortlist.application_id.in_(application_ids)
            )
        ).all()
    )
