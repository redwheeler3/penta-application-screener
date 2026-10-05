"""Recheck administrative authority inside the transaction that commits shared changes."""

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.problems import Problem
from app.db.models import AccessAllowlistEntry, User, UserRole


def require_admin_write(db: Session, actor_id: int) -> User:
    """Hold SQLite's writer and reload authority before mutation or side-effect staging.

    Admission checks remain useful, but an actor may be demoted while waiting to write.
    The caller retains this transaction through commit; no provider I/O belongs here.
    """
    with db.no_autoflush:
        db.execute(update(AccessAllowlistEntry).where(AccessAllowlistEntry.role == UserRole.ADMIN)
            .values(role=AccessAllowlistEntry.role, updated_at=AccessAllowlistEntry.updated_at)
            .execution_options(synchronize_session=False))
        actor = db.get(User, actor_id, populate_existing=True)
    if actor is None or not actor.is_active or actor.role != UserRole.ADMIN:
        raise Problem("forbidden", detail="Your admin access changed. Please sign in again.")
    return actor
