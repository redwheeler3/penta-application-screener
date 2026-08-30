from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.problems import Problem
from app.db.models import (
    Application,
    ApplicationParticipation,
    Base,
    Opening,
    OpeningOutcome,
)
from app.services.opening_participation import (
    applicant_opening_states,
    application_is_editable,
    apply_opening_selection,
    validate_opening_selection,
)

TODAY = date(2026, 8, 24)
NOW = datetime(2026, 8, 24, 18, tzinfo=UTC)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _opening(
    db: Session,
    *,
    open_date: date,
    close_date: date,
    move_in_date: date,
) -> Opening:
    opening = Opening(
        unit_size_bedrooms=2,
        housing_charge_cents=100_000,
        application_open_date=open_date,
        application_close_date=close_date,
        move_in_date=move_in_date,
        published_at=NOW,
    )
    db.add(opening)
    db.flush()
    return opening


def _application(db: Session) -> Application:
    application = Application(
        primary_email="applicant@example.com",
        raw_row={},
        raw_row_hash="synthetic",
        normalized={},
    )
    db.add(application)
    db.flush()
    return application


def test_open_closed_and_archived_openings_have_distinct_selection_permissions() -> None:
    db = _session()
    application = _application(db)
    open_offering = _opening(
        db,
        open_date=date(2026, 8, 1),
        close_date=date(2026, 9, 1),
        move_in_date=date(2026, 10, 1),
    )
    closed_offering = _opening(
        db,
        open_date=date(2026, 7, 1),
        close_date=date(2026, 8, 1),
        move_in_date=date(2026, 9, 1),
    )
    archived_offering = _opening(
        db,
        open_date=date(2026, 5, 1),
        close_date=date(2026, 6, 1),
        move_in_date=date(2026, 8, 1),
    )
    db.add_all(
        ApplicationParticipation(
            application_id=application.id,
            opening_id=opening.id,
            applied_at=NOW,
        )
        for opening in (closed_offering, archived_offering)
    )
    db.commit()

    states = {
        state.opening.id: state
        for state in applicant_opening_states(db, application, today=TODAY)
    }

    assert states[open_offering.id].can_select is True
    assert states[closed_offering.id].can_select is True
    assert states[closed_offering.id].can_withdraw is True
    assert states[archived_offering.id].can_withdraw is False


def test_closed_participant_can_restore_an_unsubmitted_withdrawal() -> None:
    db = _session()
    application = _application(db)
    closed_offering = _opening(
        db,
        open_date=date(2026, 7, 1),
        close_date=date(2026, 8, 1),
        move_in_date=date(2026, 9, 1),
    )
    db.add(
        ApplicationParticipation(
            application_id=application.id,
            opening_id=closed_offering.id,
            applied_at=NOW,
        )
    )
    application.working_opening_ids = []
    db.commit()

    state = applicant_opening_states(
        db,
        application,
        today=TODAY,
        use_working_copy=True,
    )[0]

    assert state.selected is False
    assert state.participating is True
    assert state.can_select is True
    assert application_is_editable(db, application, [state]) is True


def test_selected_application_stays_locked_when_another_opening_is_open() -> None:
    db = _session()
    application = _application(db)
    selected_opening = _opening(
        db,
        open_date=date(2026, 7, 1),
        close_date=date(2026, 8, 1),
        move_in_date=date(2026, 9, 1),
    )
    _opening(
        db,
        open_date=date(2026, 8, 1),
        close_date=date(2026, 9, 1),
        move_in_date=date(2026, 10, 1),
    )
    db.add(
        ApplicationParticipation(
            application_id=application.id,
            opening_id=selected_opening.id,
            applied_at=NOW,
            outcome=OpeningOutcome.SELECTED,
        )
    )
    db.commit()

    states = applicant_opening_states(db, application, today=TODAY)

    assert any(state.phase.value == "open" for state in states)
    assert application_is_editable(db, application, states) is False


def test_submitting_can_withdraw_from_the_only_current_opening() -> None:
    db = _session()
    application = _application(db)
    closed_offering = _opening(
        db,
        open_date=date(2026, 7, 1),
        close_date=date(2026, 8, 1),
        move_in_date=date(2026, 9, 1),
    )
    db.add(
        ApplicationParticipation(
            application_id=application.id,
            opening_id=closed_offering.id,
            applied_at=NOW,
        )
    )
    db.commit()

    assert validate_opening_selection(db, application, [], now=NOW) == []


def test_archived_history_does_not_satisfy_current_selection_requirement() -> None:
    db = _session()
    application = _application(db)
    archived_offering = _opening(
        db,
        open_date=date(2026, 5, 1),
        close_date=date(2026, 6, 1),
        move_in_date=date(2026, 8, 1),
    )
    _opening(
        db,
        open_date=date(2026, 8, 1),
        close_date=date(2026, 9, 1),
        move_in_date=date(2026, 10, 1),
    )
    db.add(
        ApplicationParticipation(
            application_id=application.id,
            opening_id=archived_offering.id,
            applied_at=NOW,
        )
    )
    db.commit()

    with pytest.raises(Problem, match="Choose at least one opening"):
        validate_opening_selection(db, application, [archived_offering.id], now=NOW)


def test_archiving_discards_an_unsubmitted_private_withdrawal() -> None:
    db = _session()
    application = _application(db)
    archived_offering = _opening(
        db,
        open_date=date(2026, 5, 1),
        close_date=date(2026, 6, 1),
        move_in_date=date(2026, 8, 1),
    )
    application.working_opening_ids = []
    db.add(
        ApplicationParticipation(
            application_id=application.id,
            opening_id=archived_offering.id,
            applied_at=NOW,
        )
    )
    db.commit()

    states = applicant_opening_states(db, application, today=TODAY, use_working_copy=True)

    assert len(states) == 1
    assert states[0].phase.value == "archived"
    assert states[0].selected is True
    assert states[0].participating is True


def test_closed_opening_allows_withdrawal_but_archived_opening_does_not() -> None:
    db = _session()
    application = _application(db)
    closed_offering = _opening(
        db,
        open_date=date(2026, 7, 1),
        close_date=date(2026, 8, 1),
        move_in_date=date(2026, 9, 1),
    )
    archived_offering = _opening(
        db,
        open_date=date(2026, 5, 1),
        close_date=date(2026, 6, 1),
        move_in_date=date(2026, 8, 1),
    )
    db.add_all(
        ApplicationParticipation(
            application_id=application.id,
            opening_id=opening.id,
            applied_at=NOW,
        )
        for opening in (closed_offering, archived_offering)
    )
    db.commit()

    with pytest.raises(Problem, match="move-in date"):
        validate_opening_selection(db, application, [closed_offering.id], now=NOW)

    selected = validate_opening_selection(db, application, [archived_offering.id], now=NOW)
    apply_opening_selection(db, application, selected, submitted_at=NOW)
    db.commit()

    closed_participation = db.query(ApplicationParticipation).filter_by(
        opening_id=closed_offering.id
    ).one()
    assert closed_participation.withdrawn_at is not None
    closed_state = next(
        state
        for state in applicant_opening_states(db, application, today=TODAY)
        if state.opening.id == closed_offering.id
    )
    assert closed_state.participating is False
    assert closed_state.has_participated is True
    assert application.retention_due_on == date(2027, 9, 1)
