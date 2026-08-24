"""Resolve a passwordless browser credential to an actively allowlisted committee user."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import BrowserSession, PasswordlessIdentityKind, User
from app.services.allowlist import get_entry
from app.services.passwordless_auth import (
    authenticate_browser_session,
    revoke_identity_magic_links,
    revoke_identity_sessions,
)
from app.services.users import record_user_activity


@dataclass(frozen=True)
class AuthenticatedCommittee:
    user: User
    browser_session: BrowserSession


def authenticate_committee_user(
    db: Session,
    token: str,
    *,
    now: datetime | None = None,
) -> AuthenticatedCommittee | None:
    browser_session = authenticate_browser_session(
        db,
        token,
        identity_kind=PasswordlessIdentityKind.COMMITTEE,
        now=now,
    )
    if (
        browser_session is None
        or browser_session.identity_kind != PasswordlessIdentityKind.COMMITTEE
        or browser_session.user_id is None
    ):
        db.commit()
        return None

    user = db.get(User, browser_session.user_id)
    entry = get_entry(db, user.email) if user is not None else None
    if (
        user is None
        or not user.is_active
        or entry is None
        or entry.role != user.role
    ):
        revoke_identity_sessions(
            db,
            identity_kind=PasswordlessIdentityKind.COMMITTEE,
            user_id=browser_session.user_id,
            now=now,
        )
        revoke_identity_magic_links(
            db,
            identity_kind=PasswordlessIdentityKind.COMMITTEE,
            user_id=browser_session.user_id,
            now=now,
        )
        db.commit()
        return None

    record_user_activity(db, user=user, now=now)
    db.commit()
    return AuthenticatedCommittee(user=user, browser_session=browser_session)
