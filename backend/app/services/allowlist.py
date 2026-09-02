"""The committee access allowlist: who may sign in, and with what role.

Google and email-link sign-ins both require a matching verified address. The
resulting ``User`` takes the entry's role (see ``services/users``), so an ``admin``
entry grants admin and a ``member`` entry grants member. Seed admins are persisted
as permanent administrators and cannot be demoted or removed in-app.
"""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings, resolve_backend_path
from app.core.text import normalize_email
from app.db.models import (
    AccessAllowlistEntry,
    PasswordlessIdentityKind,
    User,
    UserRole,
)
from app.services.passwordless_auth import (
    revoke_identity_magic_links,
    revoke_identity_sessions,
)


class SeedAdminProtectedError(ValueError):
    """Raised when code tries to demote or remove a permanent seed admin."""


def get_entry(db: Session, email: str) -> AccessAllowlistEntry | None:
    return db.scalar(
        select(AccessAllowlistEntry).where(
            AccessAllowlistEntry.email == normalize_email(email)
        )
    )


def list_entries(db: Session) -> list[AccessAllowlistEntry]:
    return list(
        db.scalars(select(AccessAllowlistEntry).order_by(AccessAllowlistEntry.email)).all()
    )


def upsert_entry(
    db: Session,
    *,
    email: str,
    role: UserRole,
    is_seed_admin: bool = False,
) -> AccessAllowlistEntry:
    """Add an allowed email or update its role. Idempotent on email."""
    email = normalize_email(email)
    entry = get_entry(db, email)
    if entry is not None and entry.is_seed_admin and role != UserRole.ADMIN:
        raise SeedAdminProtectedError
    role_changed = entry is not None and entry.role != role
    if entry is None:
        entry = AccessAllowlistEntry(
            email=email,
            role=role,
            is_seed_admin=is_seed_admin,
        )
        db.add(entry)
    else:
        entry.role = role
        if is_seed_admin:
            entry.is_seed_admin = True
    user = db.scalar(select(User).where(User.email == email))
    if user is not None:
        if role_changed:
            revoke_identity_sessions(
                db,
                identity_kind=PasswordlessIdentityKind.COMMITTEE,
                user_id=user.id,
            )
            revoke_identity_magic_links(
                db,
                identity_kind=PasswordlessIdentityKind.COMMITTEE,
                user_id=user.id,
            )
        user.role = role
        user.is_active = True
    db.commit()
    db.refresh(entry)
    return entry


def remove_entry(db: Session, email: str) -> bool:
    """Remove an email from the allowlist. Returns whether a row was removed."""
    entry = get_entry(db, email)
    if entry is None:
        return False
    if entry.is_seed_admin:
        raise SeedAdminProtectedError
    user = db.scalar(select(User).where(User.email == entry.email))
    if user is not None:
        user.is_active = False
        revoke_identity_sessions(
            db,
            identity_kind=PasswordlessIdentityKind.COMMITTEE,
            user_id=user.id,
        )
        revoke_identity_magic_links(
            db,
            identity_kind=PasswordlessIdentityKind.COMMITTEE,
            user_id=user.id,
        )
    db.delete(entry)
    db.commit()
    return True


def _read_bootstrap_emails() -> list[str]:
    """Emails from the initial-admins config file (one per line, '#' comments).
    Missing file is fine — a deployment may manage the list entirely in-app."""
    path: Path = resolve_backend_path(get_settings().initial_admins_file)
    if not path.exists():
        return []
    emails: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            emails.append(normalize_email(line))
    return emails


def seed_initial_admins(db: Session) -> None:
    """Persist every email in the seed file as a permanent admin entry.

    Idempotent and additive: removing an email from the file does not remove its
    protection after it has been seeded.
    """
    for email in _read_bootstrap_emails():
        upsert_entry(db, email=email, role=UserRole.ADMIN, is_seed_admin=True)
