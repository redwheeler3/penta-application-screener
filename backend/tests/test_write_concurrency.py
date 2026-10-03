"""Two request sessions must not overwrite a shared revision or permanent decision."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api.applicant.application import save_applicant_application
from app.core.problems import Problem
from app.core.time import pacific_today
from app.db.models import (
    Application,
    ApplicationParticipation,
    Opening,
    OpeningOutcome,
    User,
    UserRole,
)
from app.schemas.applicant.contracts import SaveApplicationRequest
from app.services.openings.selection import (
    confirm_no_household_selected,
    confirm_opening_selection,
)
from tests.applicant.support import sample_answers
from tests.db_support import memory_engine


def request_sessions(*, closed: bool, engine=None):
    factory = sessionmaker(bind=engine or memory_engine(foreign_keys=True), autoflush=False)
    now = datetime.now(UTC)
    today = pacific_today()
    with factory() as db:
        opening = Opening(
            unit_size_bedrooms=2, housing_charge_cents=100_000,
            application_open_date=today - timedelta(days=5),
            application_close_date=today + timedelta(days=-1 if closed else 5),
            move_in_date=today + timedelta(days=30), published_at=now,
        )
        admin = User(email="admin@example.com", display_name="Synthetic admin", role=UserRole.ADMIN)
        applications = [
            Application(
                primary_email=f"a{i}@example.com", applicant_name=f"Synthetic {i}",
                raw_row={}, raw_row_hash=f"synthetic-{i}", normalized={},
                working_revision=1, submitted_at=now if closed else None,
            )
            for i in (1, 2)
        ]
        db.add_all([opening, admin, *applications])
        db.flush()
        if closed:
            for application in applications:
                db.add(ApplicationParticipation(
                    application_id=application.id, opening_id=opening.id, applied_at=now,
                ))
        db.commit()
        return factory, opening.id, admin.id, [application.id for application in applications]


def test_overlapping_loaded_applicant_saves_cannot_accept_the_same_revision() -> None:
    factory, opening_id, _admin_id, ids = request_sessions(closed=False)
    with factory() as first, factory() as second:
        applications = [first.get(Application, ids[0]), second.get(Application, ids[0])]
        assert all(application.working_revision == 1 for application in applications)
        bodies = []
        for introduction in ("First browser", "Second browser"):
            answers = sample_answers(introduction=introduction)
            answers["applicant"]["email"] = "a1@example.com"
            bodies.append(SaveApplicationRequest.model_validate({
                "answers": answers, "openingIds": [opening_id], "baseRevision": 1,
            }))
        saved = save_applicant_application(bodies[0], db=first, application=applications[0])
        assert saved.working_revision == 2
        with pytest.raises(Problem) as rejected:
            save_applicant_application(bodies[1], db=second, application=applications[1])
        assert rejected.value.code == "stale_application"
        second.rollback()
    with factory() as db:
        application = db.get(Application, ids[0])
        assert application.working_revision == 2
        assert application.working_answers["essays"]["household_introduction"] == "First browser"


@pytest.mark.parametrize(("first_choice", "second_choice"), [(0, None), (None, 0), (0, 1)])
def test_overlapping_loaded_opening_decisions_preserve_the_first_choice(
    first_choice: int | None, second_choice: int | None
) -> None:
    factory, opening_id, admin_id, ids = request_sessions(closed=True)
    with factory() as first, factory() as second:
        openings = [first.get(Opening, opening_id), second.get(Opening, opening_id)]
        assert all(opening.decided_at is None for opening in openings)

        def decide(db, opening, choice):
            admin = db.get(User, admin_id)
            if choice is None:
                confirm_no_household_selected(db, opening, decided_by=admin)
            else:
                confirm_opening_selection(db, opening, ids[choice], decided_by=admin)

        decide(first, openings[0], first_choice)
        with pytest.raises(Problem, match="permanent"):
            decide(second, openings[1], second_choice)
        second.rollback()
    with factory() as db:
        assert db.get(Opening, opening_id).no_household_selected == (first_choice is None)
        selected = db.scalar(select(ApplicationParticipation.application_id).where(
            ApplicationParticipation.outcome == OpeningOutcome.SELECTED,
        ))
        assert selected == (ids[first_choice] if first_choice is not None else None)


@pytest.mark.parametrize("choice", [None, 0])
def test_repeating_the_same_loaded_opening_decision_is_idempotent(choice: int | None) -> None:
    factory, opening_id, admin_id, ids = request_sessions(closed=True)
    with factory() as first, factory() as second:
        openings = [first.get(Opening, opening_id), second.get(Opening, opening_id)]
        for db, opening in zip((first, second), openings, strict=True):
            admin = db.get(User, admin_id)
            if choice is None:
                confirm_no_household_selected(db, opening, decided_by=admin)
            else:
                confirm_opening_selection(db, opening, ids[choice], decided_by=admin)
            assert not db.in_transaction()
