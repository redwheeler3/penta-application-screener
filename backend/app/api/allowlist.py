"""Admin-only management of the access allowlist (who may sign in, with what role).

The first genuinely admin-only surface (M15), so every route here is gated by
``require_admin``. Guarded against locking the committee out: the last admin entry
can neither be removed nor demoted to member.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.api.problems import Problem
from app.db.models import User, UserRole
from app.db.session import get_db
from app.schemas.allowlist import AllowlistEntryOut, AllowlistResponse, AllowlistUpsert
from app.services import allowlist

router = APIRouter(prefix="/allowlist", tags=["allowlist"])


def _response(db: Session) -> AllowlistResponse:
    return AllowlistResponse(
        entries=[
            AllowlistEntryOut(email=e.email, role=e.role.value)
            for e in allowlist.list_entries(db)
        ]
    )


def _admin_count(db: Session) -> int:
    return sum(1 for e in allowlist.list_entries(db) if e.role == UserRole.ADMIN)


@router.get("", response_model=AllowlistResponse)
def read_allowlist(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AllowlistResponse:
    return _response(db)


@router.put("", response_model=AllowlistResponse)
def upsert_allowlist_entry(
    body: AllowlistUpsert,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AllowlistResponse:
    """Add an allowed email or change its role. Adding an ``admin`` entry grants
    admin — the allowlist is the role-management surface."""
    existing = allowlist.get_entry(db, str(body.email))
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
    allowlist.upsert_entry(db, email=str(body.email), role=body.role)
    return _response(db)


@router.delete("/{email}", response_model=AllowlistResponse)
def remove_allowlist_entry(
    email: str,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AllowlistResponse:
    """Remove an email from the allowlist. Its existing session stays valid until it
    expires or they log out; they cannot sign in again once removed."""
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
