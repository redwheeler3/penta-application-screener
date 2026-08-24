"""Admin-only management of the access allowlist (who may sign in, with what role).

Every route is admin-gated. Mutations also require a recently authenticated browser.
The last admin entry can neither be removed nor demoted to member.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin, require_recent_admin
from app.api.problems import Problem
from app.core.text import normalize_email
from app.db.models import User, UserRole
from app.db.session import get_db
from app.schemas.allowlist import (
    AllowlistEntryOut,
    AllowlistResponse,
    AllowlistUpsert,
    DeniedSignInAttemptOut,
    DeniedSignInAttemptsResponse,
)
from app.services import allowlist
from app.services.denied_sign_ins import list_denied_sign_ins

router = APIRouter(prefix="/allowlist", tags=["allowlist"])


def _as_utc(timestamp: datetime | None) -> datetime | None:
    """Give SQLite's timezone-naive UTC timestamps an unambiguous API offset."""
    if timestamp is None:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _response(db: Session) -> AllowlistResponse:
    entries = allowlist.list_entries(db)
    emails = [entry.email for entry in entries]
    users_by_email = {
        user.email: user
        for user in db.scalars(select(User).where(User.email.in_(emails))).all()
    } if emails else {}
    response_entries: list[AllowlistEntryOut] = []
    for entry in entries:
        user = users_by_email.get(entry.email)
        response_entries.append(
            AllowlistEntryOut(
                email=entry.email,
                role=entry.role.value,
                display_name=user.display_name if user else None,
                first_active_at=_as_utc(user.first_active_at) if user else None,
                last_active_at=_as_utc(user.last_active_at) if user else None,
            )
        )
    return AllowlistResponse(entries=response_entries)


def _admin_count(db: Session) -> int:
    return sum(1 for e in allowlist.list_entries(db) if e.role == UserRole.ADMIN)


@router.get("/denied-attempts", response_model=DeniedSignInAttemptsResponse)
def read_denied_sign_in_attempts(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DeniedSignInAttemptsResponse:
    attempts_by_subject: dict[str, DeniedSignInAttemptOut] = {}
    for attempt in list_denied_sign_ins(db):
        summary = attempts_by_subject.get(attempt.google_subject)
        if summary is None:
            attempts_by_subject[attempt.google_subject] = DeniedSignInAttemptOut(
                display_name=attempt.display_name,
                email=attempt.email,
                first_denied_at=_as_utc(attempt.created_at),
                last_denied_at=_as_utc(attempt.created_at),
                count=1,
            )
            continue
        first_denied_at = _as_utc(attempt.created_at)
        summary.first_denied_at = min(summary.first_denied_at, first_denied_at)
        summary.count += 1

    return DeniedSignInAttemptsResponse(attempts=list(attempts_by_subject.values()))


@router.get("", response_model=AllowlistResponse)
def read_allowlist(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AllowlistResponse:
    return _response(db)


@router.put("", response_model=AllowlistResponse)
def upsert_allowlist_entry(
    body: AllowlistUpsert,
    _admin: User = Depends(require_recent_admin),
    db: Session = Depends(get_db),
) -> AllowlistResponse:
    """Add an allowed email or change its role. Adding an ``admin`` entry grants
    admin — the allowlist is the role-management surface."""
    target_email = normalize_email(body.email)
    existing = allowlist.get_entry(db, target_email)
    demoting_current_admin = (
        target_email == _admin.email
        and existing is not None
        and existing.role == UserRole.ADMIN
        and body.role != UserRole.ADMIN
    )
    if demoting_current_admin:
        raise Problem(
            "invalid_settings",
            detail="You cannot demote your own admin account.",
        )
    # Guard the lock-out: demoting the sole remaining admin to member would leave the
    # committee with no one able to manage access.
    demoting_last_admin = (
        existing is not None
        and existing.role == UserRole.ADMIN
        and body.role != UserRole.ADMIN
        and _admin_count(db) <= 1
    )
    if demoting_last_admin:
        raise Problem(
            "invalid_settings",
            detail="Cannot demote the last admin; promote another admin first.",
        )
    allowlist.upsert_entry(db, email=target_email, role=body.role)
    return _response(db)


@router.delete("/{email}", response_model=AllowlistResponse)
def remove_allowlist_entry(
    email: str,
    _admin: User = Depends(require_recent_admin),
    db: Session = Depends(get_db),
) -> AllowlistResponse:
    """Remove committee access and revoke the account's sessions and unused links."""
    existing = allowlist.get_entry(db, email)
    removing_last_admin = (
        existing is not None
        and existing.role == UserRole.ADMIN
        and _admin_count(db) <= 1
    )
    if removing_last_admin:
        raise Problem(
            "invalid_settings",
            detail="Cannot remove the last admin; add another admin first.",
        )
    allowlist.remove_entry(db, email)
    return _response(db)
