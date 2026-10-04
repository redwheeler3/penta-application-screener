"""Browsing coalesces activity writes while every request validates the credential."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Update

from app.core.time import as_utc
from app.db.models import Application, BrowserSession, PasswordlessIdentityKind
from app.services.auth.passwordless import (
    SESSION_ACTIVITY_WRITE_INTERVAL,
    authenticate_browser_session,
    create_browser_session,
    revoke_browser_session,
)
from tests.db_support import memory_session

NOW = datetime(2026, 10, 3, tzinfo=UTC)
KIND = PasswordlessIdentityKind.APPLICANT


def issue(db, **kwargs):
    application = Application(primary_email="synthetic@example.com", raw_row={}, raw_row_hash="synthetic")
    db.add(application)
    db.flush()
    issued = create_browser_session(db, identity_kind=KIND, application_id=application.id, now=NOW, **kwargs)
    db.commit()
    return issued


def test_twenty_reads_do_not_write_until_the_activity_interval() -> None:
    with memory_session() as db:
        issued = issue(db)
        updates = []

        def record(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.startswith("UPDATE browser_sessions"):
                updates.append(statement)

        event.listen(db.bind, "before_cursor_execute", record)
        try:
            for seconds in range(1, 21):
                assert authenticate_browser_session(db, issued.token, identity_kind=KIND, now=NOW + timedelta(seconds=seconds)) is not None
                db.commit()
            assert updates == []
            active = authenticate_browser_session(db, issued.token, identity_kind=KIND, now=NOW + SESSION_ACTIVITY_WRITE_INTERVAL)
            assert active is not None
            assert as_utc(active.last_activity_at) == NOW + SESSION_ACTIVITY_WRITE_INTERVAL
            assert len(updates) == 1
        finally:
            event.remove(db.bind, "before_cursor_execute", record)


def test_revocation_is_visible_even_with_a_loaded_session_inside_the_interval() -> None:
    with memory_session() as db:
        issued = issue(db)
        with Session(db.bind) as other:
            assert revoke_browser_session(other, issued.token, now=NOW + timedelta(seconds=1))
            other.commit()
        assert authenticate_browser_session(db, issued.token, identity_kind=KIND, now=NOW + timedelta(seconds=2)) is None


def test_short_idle_lifetimes_still_slide_and_expire_at_the_hard_limit() -> None:
    with memory_session() as db:
        issued = issue(db, idle_lifetime=timedelta(minutes=1), absolute_lifetime=timedelta(minutes=2))
        for seconds in (40, 80):
            active = authenticate_browser_session(db, issued.token, identity_kind=KIND,
                now=NOW + timedelta(seconds=seconds), idle_lifetime=timedelta(minutes=1))
            assert active is not None
            assert as_utc(active.idle_expires_at) == NOW + timedelta(seconds=min(seconds + 60, 120))
            db.commit()
        assert authenticate_browser_session(db, issued.token, identity_kind=KIND,
            now=NOW + timedelta(minutes=2), idle_lifetime=timedelta(minutes=1)) is None


@pytest.mark.parametrize("change", ["touch", "revoke"])
def test_a_touch_cannot_overwrite_a_newer_touch_or_revocation(monkeypatch, change) -> None:
    with memory_session() as db:
        issued = issue(db)
        session_id = issued.record.id
        scalar = db.scalar

        def competing_update(statement, *args, **kwargs):
            if isinstance(statement, Update) and statement.table.name == "browser_sessions":
                with Session(db.bind) as other:
                    if change == "revoke":
                        revoke_browser_session(other, issued.token, now=NOW + timedelta(minutes=11))
                    else:
                        other.execute(update(BrowserSession).where(BrowserSession.id == session_id).values(
                            last_activity_at=NOW + timedelta(minutes=11), idle_expires_at=NOW + timedelta(days=7, minutes=11)))
                    other.commit()
            return scalar(statement, *args, **kwargs)

        monkeypatch.setattr(db, "scalar", competing_update)
        active = authenticate_browser_session(db, issued.token, identity_kind=KIND, now=NOW + timedelta(minutes=10))
        if change == "revoke":
            assert active is None
        else:
            assert as_utc(active.last_activity_at) == NOW + timedelta(minutes=11)
            assert as_utc(active.idle_expires_at) == NOW + timedelta(days=7, minutes=11)
