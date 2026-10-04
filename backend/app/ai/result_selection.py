"""Persist references to the results actually consumed, without copying cached output."""

from collections.abc import Sequence

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.db.models import ApplicationAISelection


def select_results(db: Session, references: Sequence[tuple[int, str, int]]) -> None:
    """Batch (consumer application, kind, result ID) references in the caller's transaction."""
    if not references:
        return
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
