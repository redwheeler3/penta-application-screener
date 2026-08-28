"""Single-use email credentials and revocable browser sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.text import normalize_email
from app.core.time import as_utc
from app.db.models import (
    BrowserSession,
    EmailDelivery,
    EmailDeliveryState,
    MagicLinkPurpose,
    MagicLinkToken,
    PasswordlessIdentityKind,
)
from app.services.token_credentials import new_token, token_hash


@dataclass(frozen=True)
class IssuedMagicLink:
    token: str
    record: MagicLinkToken


@dataclass(frozen=True)
class IssuedBrowserSession:
    token: str
    record: BrowserSession


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


def _magic_link_identity_values(
    identity_kind: PasswordlessIdentityKind,
    *,
    application_id: int | None,
    applicant_draft_id: int | None,
    user_id: int | None,
) -> dict[str, int | None]:
    if identity_kind == PasswordlessIdentityKind.APPLICANT:
        if user_id is not None or (application_id is None) == (applicant_draft_id is None):
            raise ValueError("applicant links require exactly one application or pending draft")
    elif user_id is None or application_id is not None or applicant_draft_id is not None:
        raise ValueError("committee links require only user_id")
    return {
        "application_id": application_id,
        "applicant_draft_id": applicant_draft_id,
        "user_id": user_id,
    }


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
    applicant_draft_id: int | None = None,
    user_id: int | None = None,
    now: datetime | None = None,
    lifetime: timedelta | None = None,
    remember_device: bool = False,
    initiating_session_id: int | None = None,
) -> IssuedMagicLink:
    """Create one credential and revoke older unused links for the same purpose."""
    now = now or datetime.now(UTC)
    settings = get_settings()
    if lifetime is None:
        lifetime = timedelta(hours=settings.magic_link_lifetime_hours)
    identity_values = _magic_link_identity_values(
        identity_kind,
        application_id=application_id,
        applicant_draft_id=applicant_draft_id,
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
            MagicLinkToken.applicant_draft_id == identity_values["applicant_draft_id"],
            MagicLinkToken.user_id == identity_values["user_id"],
            MagicLinkToken.consumed_at.is_(None),
            MagicLinkToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )

    raw_token = new_token()
    record = MagicLinkToken(
        identity_kind=identity_kind,
        email=email,
        purpose=purpose,
        token_hash=token_hash(raw_token),
        created_at=now,
        expires_at=now + lifetime,
        remember_device=remember_device,
        initiating_session_id=initiating_session_id,
        **identity_values,
    )
    db.add(record)
    db.flush()
    return IssuedMagicLink(token=raw_token, record=record)


def magic_link_request_allowed(
    db: Session,
    *,
    identity_kind: PasswordlessIdentityKind,
    purpose: MagicLinkPurpose,
    application_id: int | None = None,
    applicant_draft_id: int | None = None,
    user_id: int | None = None,
    email: str | None = None,
    now: datetime | None = None,
    request_limit: int | None = None,
    rate_window: timedelta | None = None,
    coalesce_window: timedelta | None = None,
) -> bool:
    """Whether another email may be sent without flooding one identity's mailbox."""
    now = now or datetime.now(UTC)
    settings = get_settings()
    request_limit = request_limit or settings.magic_link_request_limit
    rate_window = rate_window or timedelta(minutes=settings.magic_link_rate_window_minutes)
    coalesce_window = coalesce_window or timedelta(
        seconds=settings.magic_link_coalesce_seconds
    )
    identity_values = _magic_link_identity_values(
        identity_kind,
        application_id=application_id,
        applicant_draft_id=applicant_draft_id,
        user_id=user_id,
    )
    _validate_purpose(identity_kind, purpose)
    identity_filters = (
        MagicLinkToken.identity_kind == identity_kind,
        MagicLinkToken.purpose == purpose,
        MagicLinkToken.application_id == identity_values["application_id"],
        MagicLinkToken.applicant_draft_id == identity_values["applicant_draft_id"],
        MagicLinkToken.user_id == identity_values["user_id"],
    )
    delivered_or_unrecorded = ~exists(
        select(EmailDelivery.id).where(
            EmailDelivery.magic_link_token_id == MagicLinkToken.id,
            EmailDelivery.state == EmailDeliveryState.FAILED,
        )
    )
    coalesce_filters = identity_filters
    if email is not None:
        coalesce_filters = (*identity_filters, MagicLinkToken.email == normalize_email(email))
    latest = db.scalar(
        select(func.max(MagicLinkToken.created_at)).where(
            *coalesce_filters,
            delivered_or_unrecorded,
            MagicLinkToken.consumed_at.is_(None),
            MagicLinkToken.revoked_at.is_(None),
        )
    )
    if latest is not None and as_utc(latest) > now - coalesce_window:
        return False
    requests_in_window = db.scalar(
        select(func.count())
        .select_from(MagicLinkToken)
        .where(
            *identity_filters,
            delivered_or_unrecorded,
            MagicLinkToken.created_at > now - rate_window,
        )
    )
    return int(requests_in_window or 0) < request_limit


def consume_magic_link(
    db: Session,
    token: str,
    *,
    identity_kind: PasswordlessIdentityKind,
    purpose: MagicLinkPurpose,
    now: datetime | None = None,
) -> MagicLinkToken | None:
    """Atomically consume a valid link. Invalid, expired, and reused links look alike."""
    now = now or datetime.now(UTC)
    hashed_token = token_hash(token)
    result = db.execute(
        update(MagicLinkToken)
        .where(
            MagicLinkToken.token_hash == hashed_token,
            MagicLinkToken.identity_kind == identity_kind,
            MagicLinkToken.purpose == purpose,
            MagicLinkToken.consumed_at.is_(None),
            MagicLinkToken.revoked_at.is_(None),
            MagicLinkToken.expires_at > now,
        )
        .values(consumed_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        return None
    return db.scalar(select(MagicLinkToken).where(MagicLinkToken.token_hash == hashed_token))


def magic_link_for_token(
    db: Session,
    token: str,
    *,
    identity_kind: PasswordlessIdentityKind,
    purpose: MagicLinkPurpose,
) -> MagicLinkToken | None:
    """Resolve a recognizable link even after expiry or use, without authenticating it."""
    return db.scalar(
        select(MagicLinkToken).where(
            MagicLinkToken.token_hash == token_hash(token),
            MagicLinkToken.identity_kind == identity_kind,
            MagicLinkToken.purpose == purpose,
        )
    )


def create_browser_session(
    db: Session,
    *,
    identity_kind: PasswordlessIdentityKind,
    application_id: int | None = None,
    reconciliation_draft_id: int | None = None,
    user_id: int | None = None,
    now: datetime | None = None,
    idle_lifetime: timedelta | None = None,
    absolute_lifetime: timedelta | None = None,
) -> IssuedBrowserSession:
    """Create a server-side session; only its random credential leaves the server."""
    now = now or datetime.now(UTC)
    settings = get_settings()
    idle_lifetime = idle_lifetime or timedelta(days=settings.session_idle_days)
    absolute_lifetime = absolute_lifetime or timedelta(days=settings.session_absolute_days)
    identity_values = _identity_values(
        identity_kind,
        application_id=application_id,
        user_id=user_id,
    )
    if reconciliation_draft_id is not None and identity_kind != PasswordlessIdentityKind.APPLICANT:
        raise ValueError("only applicant sessions can reconcile a pending copy")
    if idle_lifetime > absolute_lifetime:
        raise ValueError("session idle lifetime cannot exceed absolute lifetime")

    raw_token = new_token()
    record = BrowserSession(
        identity_kind=identity_kind,
        token_hash=token_hash(raw_token),
        created_at=now,
        last_activity_at=now,
        idle_expires_at=now + idle_lifetime,
        absolute_expires_at=now + absolute_lifetime,
        reconciliation_draft_id=reconciliation_draft_id,
        **identity_values,
    )
    db.add(record)
    db.flush()
    return IssuedBrowserSession(token=raw_token, record=record)


def authenticate_browser_session(
    db: Session,
    token: str,
    *,
    identity_kind: PasswordlessIdentityKind,
    now: datetime | None = None,
    idle_lifetime: timedelta | None = None,
) -> BrowserSession | None:
    """Validate a session and extend its idle deadline without exceeding its hard limit."""
    now = now or datetime.now(UTC)
    settings = get_settings()
    idle_lifetime = idle_lifetime or timedelta(days=settings.session_idle_days)
    record = db.scalar(
        select(BrowserSession).where(
            BrowserSession.token_hash == token_hash(token),
            BrowserSession.identity_kind == identity_kind,
        )
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


def revoke_browser_session(db: Session, token: str, *, now: datetime | None = None) -> bool:
    """Revoke the current browser credential, if it exists and is still active."""
    now = now or datetime.now(UTC)
    result = db.execute(
        update(BrowserSession)
        .where(
            BrowserSession.token_hash == token_hash(token),
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
    except_session_id: int | None = None,
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
    filters = [identity_column == identity_id, BrowserSession.revoked_at.is_(None)]
    if except_session_id is not None:
        filters.append(BrowserSession.id != except_session_id)
    result = db.execute(
        update(BrowserSession).where(*filters).values(revoked_at=now)
    )
    return result.rowcount


def revoke_identity_magic_links(
    db: Session,
    *,
    identity_kind: PasswordlessIdentityKind,
    application_id: int | None = None,
    user_id: int | None = None,
    purpose: MagicLinkPurpose | None = None,
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
    filters = [
        identity_column == identity_id,
        MagicLinkToken.consumed_at.is_(None),
        MagicLinkToken.revoked_at.is_(None),
    ]
    if purpose is not None:
        filters.append(MagicLinkToken.purpose == purpose)
    result = db.execute(
        update(MagicLinkToken).where(*filters).values(revoked_at=now)
    )
    return result.rowcount
