"""Keep cached output only while a producer or selected consumer may retain it."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.db.models import Application, ApplicationAIResult, ApplicationAISelection
from app.services.applications.retention import current_retention_clause


def application_result_ids(db: Session, application_id: int) -> list[int]:
    """Capture results affected by deleting an application before its references cascade."""
    consumed = select(ApplicationAISelection.result_id).where(ApplicationAISelection.application_id == application_id)
    return list(db.scalars(select(ApplicationAIResult.id).where(or_(
        ApplicationAIResult.producer_application_id == application_id,
        ApplicationAIResult.id.in_(consumed),
    ))))


def prune_unowned_results(db: Session, result_ids: Sequence[int] | None = None, *, now: datetime | None = None) -> None:
    """Delete unentitled output in the caller's transaction; bound routine work to affected IDs.

    A complete sweep is reserved for preparing an isolated restored snapshot.
    Last-consumed findings remain entitled even after a consumer resubmits.
    """
    if result_ids is not None and not result_ids:
        return
    producer = select(Application.id).where(
        Application.id == ApplicationAIResult.producer_application_id, current_retention_clause(now=now),
    ).exists()
    consumer = select(ApplicationAISelection.result_id).join(Application).where(
        ApplicationAISelection.result_id == ApplicationAIResult.id, current_retention_clause(now=now),
    ).exists()
    statement = delete(ApplicationAIResult).where(~producer, ~consumer)
    if result_ids is not None:
        statement = statement.where(ApplicationAIResult.id.in_(result_ids))
    db.execute(statement.execution_options(synchronize_session=False))
