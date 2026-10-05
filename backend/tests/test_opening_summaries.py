"""Opening reads project retained household metadata with bounded queries."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event

from app.api.openings import _response, _selection_response
from app.core.time import pacific_today
from app.db.models import Application, ApplicationParticipation, Opening, OpeningOutcome
from tests.db_support import memory_session


def seed(db, count=1, *, due_on=None):
    today = pacific_today()
    openings = []
    for index in range(count):
        opening = Opening(unit_size_bedrooms=2, housing_charge_cents=100_000,
            application_open_date=today - timedelta(days=30), application_close_date=today - timedelta(days=10),
            move_in_date=today, published_at=datetime.now(UTC), decided_at=datetime.now(UTC))
        application = Application(primary_email=f"synthetic{index}@example.com", applicant_name=f"Synthetic {index}",
            raw_row={}, raw_row_hash=str(index), normalized={}, submitted_at=datetime.now(UTC), retention_due_on=due_on)
        db.add_all([opening, application])
        db.flush()
        db.add(ApplicationParticipation(opening_id=opening.id, application_id=application.id,
            applied_at=datetime.now(UTC), outcome=OpeningOutcome.SELECTED))
        openings.append(opening)
    db.commit()
    return openings


@pytest.mark.parametrize("days", [None, -1, 0, 1])
def test_selected_identity_is_unavailable_at_expiry_before_physical_purge(days):
    db = memory_session()
    due_on = None if days is None else pacific_today() + timedelta(days=days)
    opening = seed(db, due_on=due_on)[0]
    summary = _response(db).openings[0]
    detail = _selection_response(db, opening)
    retained = days is None or days > 0
    for response in (summary, detail):
        assert (response.selected_application_id is not None) == retained
        assert (response.selected_applicant_name is not None) == retained
        assert response.phase.value == "archived"
        assert not response.no_household_selected
    assert not summary.needs_decision
    if not retained:
        assert detail.candidates == []
        assert detail.active_participant_count == 0


def test_large_opening_archive_uses_two_queries_and_no_answer_blobs():
    db = memory_session()
    seed(db, count=100)
    statements = []
    def record(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
    event.listen(db.bind, "before_cursor_execute", record)
    try:
        response = _response(db)
    finally:
        event.remove(db.bind, "before_cursor_execute", record)
    assert len(response.openings) == 100
    assert len(statements) == 2
    assert all(opening.selected_applicant_name is not None for opening in response.openings)
    assert all("raw_row" not in statement and "normalized" not in statement for statement in statements)
