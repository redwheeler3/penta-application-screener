"""Short application write locks for lifecycle checks and their mutations."""

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db.models import Application


def lock_application(db: Session, application_id: int) -> Application | None:
    """Hold the application write lock and reload its lifecycle before checking policy."""
    locked = db.execute(
        update(Application)
        .where(Application.id == application_id)
        .values(working_revision=Application.working_revision, updated_at=Application.updated_at)
        .execution_options(synchronize_session=False)
    )
    if locked.rowcount != 1:
        return None
    return db.get(Application, application_id, populate_existing=True)
