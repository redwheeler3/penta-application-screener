from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.text import normalize_email
from app.db.models import User, UserRole

ACTIVITY_WRITE_INTERVAL = timedelta(minutes=5)


def upsert_google_user(
    db: Session,
    *,
    google_subject: str,
    email: str,
    display_name: str,
    avatar_url: str | None,
    role: UserRole,
) -> User:
    """Create or update the User for a signed-in Google account. ``role`` comes from
    the caller's allowlist lookup (the allowlist is the source of truth for who may
    sign in and with what role), so an existing user's role is re-synced on each login
    — an admin flipping someone's allowlist role takes effect on their next sign-in."""
    normalized_email = normalize_email(email)
    user = db.scalar(select(User).where(User.email == normalized_email))

    if user is None:
        user = User(
            google_subject=google_subject,
            email=normalized_email,
            display_name=display_name,
            avatar_url=avatar_url,
            role=role,
        )
        db.add(user)
    else:
        user.google_subject = google_subject
        user.display_name = display_name
        user.avatar_url = avatar_url
        user.role = role

    db.commit()
    db.refresh(user)
    return user


def record_user_activity(
    db: Session, *, user: User, now: datetime | None = None
) -> bool:
    """Persist a user's first and latest app use, throttled to one write per five minutes.

    Activity stays intentionally coarse: this writes only two timestamps per user,
    never an event history or request details.
    """
    observed_at = now or datetime.now(UTC)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)

    previous_activity = user.last_active_at
    if previous_activity is not None and previous_activity.tzinfo is None:
        previous_activity = previous_activity.replace(tzinfo=UTC)

    if previous_activity is not None and observed_at - previous_activity < ACTIVITY_WRITE_INTERVAL:
        return False

    if user.first_active_at is None:
        user.first_active_at = observed_at
    user.last_active_at = observed_at
    db.commit()
    return True
