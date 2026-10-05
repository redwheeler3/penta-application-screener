"""Persist references to the results actually consumed, without copying cached output."""

from collections.abc import Sequence

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.db.models import ApplicationAISelection
from app.services.applications.result_retention import prune_unowned_results


def select_results(db: Session, references: Sequence[tuple[int, str, int]]) -> None:
    """Batch (consumer application, kind, result ID) references in the caller's transaction."""
    if not references:
        return
    previous = list(db.scalars(select(ApplicationAISelection.result_id).where(
        tuple_(ApplicationAISelection.application_id, ApplicationAISelection.kind).in_(
            [(application_id, kind) for application_id, kind, _ in references]
        )
    )))
    table = ApplicationAISelection.__table__
    statement = insert(table)
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.application_id, table.c.kind],
        set_={"result_id": statement.excluded.result_id},
        where=table.c.result_id != statement.excluded.result_id,
    )
    db.execute(statement, [
        {"application_id": application_id, "kind": kind, "result_id": result_id}
        for application_id, kind, result_id in references
    ])
    selected_ids = {result_id for _, _, result_id in references}
    prune_unowned_results(db, [result_id for result_id in previous if result_id not in selected_ids])
