"""Short-lived audit data for Google accounts denied by the access allowlist."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.text import normalize_email
from app.db.models import DeniedSignInAttempt

DENIED_SIGN_IN_RETENTION = timedelta(days=365)


def record_denied_sign_in(
    db: Session,
    *,
    google_subject: str,
    email: str,
    display_name: str,
) -> None:
    """Record an unallowlisted Google login after discarding expired attempts."""
    _prune_expired(db)
    db.add(
        DeniedSignInAttempt(
            google_subject=google_subject,
            email=normalize_email(email),
            display_name=display_name,
        )
    )
    db.commit()


def list_denied_sign_ins(db: Session) -> list[DeniedSignInAttempt]:
    """Return retained attempts, newest first, after enforcing the one-year limit."""
    if _prune_expired(db):
        db.commit()
    return list(
        db.scalars(
            select(DeniedSignInAttempt).order_by(DeniedSignInAttempt.created_at.desc())
        ).all()
    )


def _prune_expired(db: Session) -> bool:
    cutoff = datetime.now(UTC) - DENIED_SIGN_IN_RETENTION
    result = db.execute(
        delete(DeniedSignInAttempt).where(DeniedSignInAttempt.created_at < cutoff)
    )
    return bool(result.rowcount)
