from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.text import normalize_email
from app.db.models import User, UserRole

ACTIVITY_WRITE_INTERVAL = timedelta(minutes=5)


class GoogleIdentityConflict(ValueError):
    """The Google account and committee user point at different identities."""


def upsert_google_user(
    db: Session,
    *,
    google_subject: str,
    email: str,
    display_name: str,
    avatar_url: str | None,
    role: UserRole,
) -> User:
    """Attach one stable Google identity to an allowlisted committee user."""
    normalized_email = normalize_email(email)
    subject_user = db.scalar(select(User).where(User.google_subject == google_subject))
    email_user = db.scalar(select(User).where(User.email == normalized_email))

    if subject_user is not None and subject_user.email != normalized_email:
        raise GoogleIdentityConflict("Google account email does not match its committee user")
    if (
        email_user is not None
        and email_user.google_subject is not None
        and email_user.google_subject != google_subject
    ):
        raise GoogleIdentityConflict("Committee user is linked to another Google account")

    user = subject_user or email_user
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
        user.is_active = True

    db.commit()
    db.refresh(user)
    return user


def upsert_committee_user(
    db: Session,
    *,
    email: str,
    role: UserRole,
) -> User:
    """Create or reactivate the committee user represented by an allowlist entry."""
    normalized_email = normalize_email(email)
    user = db.scalar(select(User).where(User.email == normalized_email))
    if user is None:
        user = User(
            email=normalized_email,
            display_name=normalized_email,
            role=role,
            is_active=True,
        )
        db.add(user)
    else:
        user.role = role
        user.is_active = True
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
