"""Single-use email credentials and revocable remembered browser sessions."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.text import normalize_email
from app.core.time import as_utc
from app.db.models import (
    BrowserSession,
    MagicLinkPurpose,
    MagicLinkToken,
    PasswordlessIdentityKind,
)

TOKEN_BYTES = 32


@dataclass(frozen=True)
class IssuedMagicLink:
    token: str
    record: MagicLinkToken


@dataclass(frozen=True)
class IssuedBrowserSession:
    token: str
    record: BrowserSession


def _new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _identity_values(
    identity_kind: PasswordlessIdentityKind,
    *,
    application_id: int | None,
    user_id: int | None,
) -> dict[str, int | None]:
    if identity_kind == PasswordlessIdentityKind.APPLICANT:
        if application_id is None or user_id is not None:
            raise ValueError("applicant credentials require only application_id")
    elif user_id is None or application_id is not None:
        raise ValueError("committee credentials require only user_id")
    return {"application_id": application_id, "user_id": user_id}


def _validate_purpose(
    identity_kind: PasswordlessIdentityKind,
    purpose: MagicLinkPurpose,
) -> None:
    if identity_kind == PasswordlessIdentityKind.APPLICANT:
        valid = {MagicLinkPurpose.APPLICANT_ACCESS, MagicLinkPurpose.EMAIL_CHANGE}
    else:
        valid = {MagicLinkPurpose.COMMITTEE_ACCESS}
    if purpose not in valid:
        raise ValueError(f"{purpose.value} is not valid for {identity_kind.value}")


def issue_magic_link(
    db: Session,
    *,
    identity_kind: PasswordlessIdentityKind,
    email: str,
    purpose: MagicLinkPurpose,
    application_id: int | None = None,
    user_id: int | None = None,
    now: datetime | None = None,
    lifetime: timedelta | None = None,
) -> IssuedMagicLink:
    """Create one credential and revoke older unused links for the same purpose."""
    now = now or datetime.now(UTC)
    settings = get_settings()
    lifetime = lifetime or timedelta(minutes=settings.magic_link_lifetime_minutes)
    identity_values = _identity_values(
        identity_kind,
        application_id=application_id,
        user_id=user_id,
    )
    _validate_purpose(identity_kind, purpose)
    email = normalize_email(email)
    if not email:
        raise ValueError("email is required")

    db.execute(
        update(MagicLinkToken)
        .where(
            MagicLinkToken.identity_kind == identity_kind,
            MagicLinkToken.purpose == purpose,
            MagicLinkToken.application_id == identity_values["application_id"],
            MagicLinkToken.user_id == identity_values["user_id"],
            MagicLinkToken.consumed_at.is_(None),
            MagicLinkToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )

    raw_token = _new_token()
    record = MagicLinkToken(
        identity_kind=identity_kind,
        email=email,
        purpose=purpose,
        token_hash=_token_hash(raw_token),
        created_at=now,
        expires_at=now + lifetime,
        **identity_values,
    )
    db.add(record)
    db.flush()
    return IssuedMagicLink(token=raw_token, record=record)


def consume_magic_link(
    db: Session,
    token: str,
    *,
    now: datetime | None = None,
) -> MagicLinkToken | None:
    """Atomically consume a valid link. Invalid, expired, and reused links look alike."""
    now = now or datetime.now(UTC)
    token_hash = _token_hash(token)
    result = db.execute(
        update(MagicLinkToken)
        .where(
            MagicLinkToken.token_hash == token_hash,
            MagicLinkToken.consumed_at.is_(None),
            MagicLinkToken.revoked_at.is_(None),
            MagicLinkToken.expires_at > now,
        )
        .values(consumed_at=now)
    )
    if result.rowcount != 1:
        return None
    return db.scalar(select(MagicLinkToken).where(MagicLinkToken.token_hash == token_hash))


def create_browser_session(
    db: Session,
    *,
    identity_kind: PasswordlessIdentityKind,
    application_id: int | None = None,
    user_id: int | None = None,
    now: datetime | None = None,
    idle_lifetime: timedelta | None = None,
    absolute_lifetime: timedelta | None = None,
) -> IssuedBrowserSession:
    """Create a remembered session; only its random credential leaves the server."""
    now = now or datetime.now(UTC)
    settings = get_settings()
    idle_lifetime = idle_lifetime or timedelta(days=settings.session_idle_days)
    absolute_lifetime = absolute_lifetime or timedelta(days=settings.session_absolute_days)
    identity_values = _identity_values(
        identity_kind,
        application_id=application_id,
        user_id=user_id,
    )
    if idle_lifetime > absolute_lifetime:
        raise ValueError("session idle lifetime cannot exceed absolute lifetime")

    raw_token = _new_token()
    record = BrowserSession(
        identity_kind=identity_kind,
        token_hash=_token_hash(raw_token),
        created_at=now,
        last_activity_at=now,
        idle_expires_at=now + idle_lifetime,
        absolute_expires_at=now + absolute_lifetime,
        recently_authenticated_at=now,
        **identity_values,
    )
    db.add(record)
    db.flush()
    return IssuedBrowserSession(token=raw_token, record=record)


def authenticate_browser_session(
    db: Session,
    token: str,
    *,
    now: datetime | None = None,
    idle_lifetime: timedelta | None = None,
) -> BrowserSession | None:
    """Validate a session and extend its idle deadline without exceeding its hard limit."""
    now = now or datetime.now(UTC)
    settings = get_settings()
    idle_lifetime = idle_lifetime or timedelta(days=settings.session_idle_days)
    record = db.scalar(
        select(BrowserSession).where(BrowserSession.token_hash == _token_hash(token))
    )
    if record is None or record.revoked_at is not None:
        return None
    if as_utc(record.idle_expires_at) <= now or as_utc(record.absolute_expires_at) <= now:
        record.revoked_at = now
        db.flush()
        return None

    record.last_activity_at = now
    record.idle_expires_at = min(now + idle_lifetime, as_utc(record.absolute_expires_at))
    db.flush()
    return record


def recently_authenticated(
    record: BrowserSession,
    *,
    now: datetime | None = None,
    maximum_age: timedelta | None = None,
) -> bool:
    now = now or datetime.now(UTC)
    settings = get_settings()
    maximum_age = maximum_age or timedelta(minutes=settings.recent_authentication_minutes)
    return as_utc(record.recently_authenticated_at) > now - maximum_age


def revoke_browser_session(db: Session, token: str, *, now: datetime | None = None) -> bool:
    """Revoke the current browser credential, if it exists and is still active."""
    now = now or datetime.now(UTC)
    result = db.execute(
        update(BrowserSession)
        .where(
            BrowserSession.token_hash == _token_hash(token),
            BrowserSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    return result.rowcount == 1


def revoke_identity_sessions(
    db: Session,
    *,
    identity_kind: PasswordlessIdentityKind,
    application_id: int | None = None,
    user_id: int | None = None,
    now: datetime | None = None,
) -> int:
    """Revoke every active browser session for one application or committee user."""
    now = now or datetime.now(UTC)
    identity_values = _identity_values(
        identity_kind,
        application_id=application_id,
        user_id=user_id,
    )
    identity_column = (
        BrowserSession.application_id
        if identity_kind == PasswordlessIdentityKind.APPLICANT
        else BrowserSession.user_id
    )
    identity_id = identity_values["application_id"] or identity_values["user_id"]
    result = db.execute(
        update(BrowserSession)
        .where(identity_column == identity_id, BrowserSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return result.rowcount


def revoke_identity_magic_links(
    db: Session,
    *,
    identity_kind: PasswordlessIdentityKind,
    application_id: int | None = None,
    user_id: int | None = None,
    now: datetime | None = None,
) -> int:
    """Revoke every unused email credential for one application or committee user."""
    now = now or datetime.now(UTC)
    identity_values = _identity_values(
        identity_kind,
        application_id=application_id,
        user_id=user_id,
    )
    identity_column = (
        MagicLinkToken.application_id
        if identity_kind == PasswordlessIdentityKind.APPLICANT
        else MagicLinkToken.user_id
    )
    identity_id = identity_values["application_id"] or identity_values["user_id"]
    result = db.execute(
        update(MagicLinkToken)
        .where(
            identity_column == identity_id,
            MagicLinkToken.consumed_at.is_(None),
            MagicLinkToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    return result.rowcount
