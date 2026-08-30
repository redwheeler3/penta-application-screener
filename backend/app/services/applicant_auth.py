"""Resolve an applicant browser credential to its current, accessible application."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models import Application, BrowserSession, PasswordlessIdentityKind
from app.services.passwordless_auth import authenticate_browser_session
from app.services.selected_application import application_is_selected


@dataclass(frozen=True)
class AuthenticatedApplicant:
    application: Application
    browser_session: BrowserSession


def authenticate_applicant(
    db: Session,
    token: str,
    *,
    now: datetime | None = None,
) -> AuthenticatedApplicant | None:
    now = now or datetime.now(UTC)
    browser_session = authenticate_browser_session(
        db,
        token,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        now=now,
    )
    if browser_session is None or browser_session.application_id is None:
        db.commit()
        return None
    application = db.get(Application, browser_session.application_id)
    if (
        application is None
        or application.withdrawn_at is not None
        or application_is_selected(db, application.id)
    ):
        browser_session.revoked_at = now
        db.commit()
        return None
    db.commit()
    return AuthenticatedApplicant(
        application=application,
        browser_session=browser_session,
    )
