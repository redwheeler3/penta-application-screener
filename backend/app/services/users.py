from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User, UserRole


def upsert_google_user(
    db: Session,
    *,
    google_subject: str,
    email: str,
    display_name: str,
    avatar_url: str | None,
) -> User:
    normalized_email = email.strip().lower()
    user = db.scalar(select(User).where(User.email == normalized_email))

    if user is None:
        user_count = db.scalar(select(User.id).limit(1))
        role = UserRole.ADMIN if user_count is None else UserRole.MEMBER
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

    db.commit()
    db.refresh(user)
    return user

