from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.text import normalize_email
from app.db.models import User, UserRole, UserSignIn


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


def record_successful_sign_in(db: Session, *, user: User) -> None:
    """Record one completed, allowlisted Google login and its latest timestamp."""
    user.last_signed_in_at = func.now()
    db.add(UserSignIn(user_id=user.id))
    db.commit()
