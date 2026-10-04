"""Access guards and mutations share the writer boundary across request sessions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.api.allowlist import remove_allowlist_entry, upsert_allowlist_entry
from app.core.problems import Problem
from app.db.models import AccessAllowlistEntry, Base, User, UserRole
from app.schemas.allowlist import AllowlistUpsert
from app.services.email.sender import CapturedEmailSender


@pytest.mark.parametrize("operations", [("remove", "remove"), ("demote", "demote"), ("remove", "demote"), ("demote", "remove")])
def test_cross_changes_cannot_remove_the_last_admin(tmp_path, operations) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'allowlist-race.db').as_posix()}",
        connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def configure(connection, _record):
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")

    Base.metadata.create_all(engine)
    with Session(engine) as db:
        for name in ("a", "b"):
            email = f"{name}@example.com"
            db.add_all([User(email=email, display_name="Synthetic", role=UserRole.ADMIN),
                AccessAllowlistEntry(email=email, role=UserRole.ADMIN, is_seed_admin=False)])
        db.commit()
    ready = Barrier(2)

    def change(actor_email, target_email, operation):
        with Session(engine) as db:
            actor = db.scalar(select(User).where(User.email == actor_email))
            # Both requests have already authenticated and loaded their old list.
            db.scalars(select(AccessAllowlistEntry)).all()
            ready.wait(timeout=3)
            try:
                if operation == "remove":
                    remove_allowlist_entry(target_email, _admin=actor, db=db)
                else:
                    upsert_allowlist_entry(AllowlistUpsert(email=target_email, role=UserRole.MEMBER), BackgroundTasks(),
                        _admin=actor, db=db, sender=CapturedEmailSender(), outbox_runner=lambda _sender: None)
                return "accepted"
            except Problem as error:
                db.rollback()
                return error.code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(change, "a@example.com", "b@example.com", operations[0]),
                pool.submit(change, "b@example.com", "a@example.com", operations[1])]
            assert sorted(future.result() for future in results) == ["accepted", "forbidden"]
        with Session(engine) as db:
            assert len(db.scalars(select(AccessAllowlistEntry).where(AccessAllowlistEntry.role == UserRole.ADMIN)).all()) == 1
            assert len(db.scalars(select(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True))).all()) == 1
    finally:
        engine.dispose()
