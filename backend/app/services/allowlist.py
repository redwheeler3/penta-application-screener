"""The access allowlist: who may sign in, and with what role.

An OAuth login is admitted only if its email matches an entry here; the resulting
``User`` takes the entry's role (see ``services/users``). The list is also role
management — an ``admin`` entry grants admin, a ``member`` entry grants member.
Initial admins are seeded from a config file at startup; after that admins manage
the list in-app.
"""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings, resolve_backend_path
from app.db.models import AccessAllowlistEntry, UserRole


def normalize_email(email: str) -> str:
    return email.strip().lower()


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


def upsert_entry(db: Session, *, email: str, role: UserRole) -> AccessAllowlistEntry:
    """Add an allowed email or update its role. Idempotent on email."""
    entry = get_entry(db, email)
    if entry is None:
        entry = AccessAllowlistEntry(email=normalize_email(email), role=role)
        db.add(entry)
    else:
        entry.role = role
    db.commit()
    db.refresh(entry)
    return entry


def remove_entry(db: Session, email: str) -> bool:
    """Remove an email from the allowlist. Returns whether a row was removed."""
    entry = get_entry(db, email)
    if entry is None:
        return False
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
    """Ensure every email in the bootstrap file is an admin entry. Idempotent and
    additive — it promotes a listed email to admin but never removes anyone, so it is
    safe to run on every startup and survives a DB reset. Bootstrap-only: it does not
    revoke (removing an email from the file has no effect once seeded)."""
    for email in _read_bootstrap_emails():
        upsert_entry(db, email=email, role=UserRole.ADMIN)
