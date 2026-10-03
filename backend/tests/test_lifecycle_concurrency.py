"""Selection and withdrawal cannot both succeed for the same application."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, local

import pytest
from fastapi import Response
from sqlalchemy import create_engine, event, select

from app.api.applicant import application as applicant_routes
from app.api.applications import routes as committee_routes
from app.core.problems import Problem
from app.db.models import (
    Application,
    ApplicationNote,
    ApplicationParticipation,
    ApplicationStar,
    Base,
    Opening,
    OpeningOutcome,
    User,
)
from app.schemas.applications import PrivateNoteUpdate
from app.services.applications.locking import lock_application
from app.services.openings import selection
from tests.test_write_concurrency import request_sessions


@pytest.fixture
def request_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'lifecycle.db'}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def pragmas(connection, _record):
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")

    Base.metadata.create_all(engine)
    yield request_sessions(closed=True, engine=engine)
    engine.dispose()


@pytest.mark.parametrize("first", ["selection", "withdrawal"])
def test_selection_and_withdrawal_share_a_write_boundary(request_database, monkeypatch, first) -> None:
    factory, opening_id, admin_id, ids = request_database
    held, release, competing = Event(), Event(), Event()
    request = local()

    def paused_lock(db, application_id):
        application = lock_application(db, application_id)
        if request.kind == first:
            held.set()
            assert release.wait(5), "First transaction was not released"
        return application

    monkeypatch.setattr(selection, "lock_application", paused_lock)
    monkeypatch.setattr(applicant_routes, "lock_application", paused_lock)

    def perform(kind):
        request.kind = kind
        with factory() as db:
            application = db.get(Application, ids[0])
            if kind != first:
                competing.set()
            try:
                if kind == "selection":
                    selection.confirm_opening_selection(
                        db, db.get(Opening, opening_id), ids[0], decided_by=db.get(User, admin_id),
                    )
                else:
                    applicant_routes.withdraw_applicant_application(Response(), application, db)
                return "saved"
            except Problem as error:
                db.rollback()
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_result = pool.submit(perform, first)
        try:
            assert held.wait(5)
            other_kind = "withdrawal" if first == "selection" else "selection"
            other_result = pool.submit(perform, other_kind)
            assert competing.wait(5)
            assert not other_result.done()
        finally:
            release.set()
        assert first_result.result(timeout=5) == "saved"
        assert other_result.result(timeout=5) != "saved"
    with factory() as db:
        application = db.get(Application, ids[0])
        participation = db.scalar(select(ApplicationParticipation).where(
            ApplicationParticipation.application_id == ids[0],
        ))
        assert (participation.outcome == OpeningOutcome.SELECTED) == (first == "selection")
        assert (application.withdrawn_at is not None) == (first == "withdrawal")


@pytest.mark.parametrize("field", ["note", "star"])
def test_overlapping_first_member_writes_share_one_row(request_database, monkeypatch, field) -> None:
    factory, opening_id, admin_id, ids = request_database
    held, release, competing = Event(), Event(), Event()
    request = local()

    def paused_lock(db, application_id):
        application = lock_application(db, application_id)
        if request.first:
            held.set()
            assert release.wait(5)
        return application

    monkeypatch.setattr(committee_routes, "lock_application", paused_lock)

    def save(first):
        request.first = first
        with factory() as db:
            user = db.get(User, admin_id)
            if not first:
                competing.set()
            if field == "note":
                return committee_routes.save_private_note(
                    ids[0], PrivateNoteUpdate(note="First" if first else "Second"),
                    opening_id=opening_id, user=user, db=db,
                )
            return committee_routes.add_star(ids[0], opening_id=opening_id, user=user, db=db)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(save, True)
        try:
            assert held.wait(5)
            second = pool.submit(save, False)
            assert competing.wait(5)
            assert not second.done()
        finally:
            release.set()
        first.result(timeout=5)
        second.result(timeout=5)
    with factory() as db:
        model = ApplicationNote if field == "note" else ApplicationStar
        rows = db.scalars(select(model).where(model.application_id == ids[0])).all()
        assert len(rows) == 1
        if field == "note":
            assert rows[0].note == "Second"
