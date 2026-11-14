from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.time import pacific_today
from app.db.models import (
    Application,
    ApplicationParticipation,
    OpeningRetentionProtection,
)
from app.schemas.openings import OpeningCreate
from app.services.applications.purge import purge_due_applicant_data
from app.services.applications.retention import (
    current_retention_clause,
    retention_is_current,
)
from app.services.openings.catalog import (
    create_opening,
    opening_phase,
    published_openings,
)
from tests.db_support import memory_session


def applicant(db, due):
    row = Application(primary_email=f"synthetic-{due}@example.test", raw_row={}, raw_row_hash=str(due),
        normalized={}, submitted_at=datetime.now(UTC), retention_due_on=due)
    db.add(row)
    db.flush()
    return row


def prepare(db, deadline, *, now=None):
    return create_opening(db, OpeningCreate(unitSizeBedrooms=2, housingChargeCents=100000,
        applicationCloseDate=deadline, moveInDate=deadline+timedelta(days=30)), now=now)


def test_preparation_protects_through_deadline_without_enrolling_or_publishing():
    db = memory_session(foreign_keys=True)
    now = datetime.now(UTC)
    today = pacific_today(now=now)
    row = applicant(db, today+timedelta(days=2))
    identity = row.id
    opening = prepare(db, today+timedelta(days=37), now=now)
    db.commit()
    assert opening_phase(opening).value == "preparing"
    assert published_openings(db) == []
    assert db.scalar(select(ApplicationParticipation)) is None
    assert row.retention_due_on == today+timedelta(days=2)
    for offset in (2, 36, 37):
        clock = now+timedelta(days=offset)
        assert retention_is_current(row, now=clock)
        assert db.scalar(select(Application.id).where(current_retention_clause(now=clock))) == identity
        assert purge_due_applicant_data(db, now=clock).applications_purged == 0
    assert purge_due_applicant_data(db, now=now+timedelta(days=38)).applications_purged == 1
    assert db.scalar(select(OpeningRetentionProtection)) is None


def test_overlapping_protection_ends_when_last_opening_ends_or_shortens():
    db = memory_session(foreign_keys=True)
    now = datetime.now(UTC)
    today = pacific_today(now=now)
    row = applicant(db, today+timedelta(days=1))
    first = prepare(db, today+timedelta(days=10))
    second = prepare(db, today+timedelta(days=20))
    db.commit()
    clock = now+timedelta(days=5)
    first.decided_at = clock
    db.flush()
    assert retention_is_current(row, now=clock)
    second.application_close_date = today+timedelta(days=3)
    db.flush()
    assert not retention_is_current(row, now=clock)
    assert purge_due_applicant_data(db, now=clock).applications_purged == 1


def test_preparation_never_revives_expired_records_or_captures_private_drafts():
    db = memory_session(foreign_keys=True)
    today = pacific_today()
    expired = applicant(db, today)
    draft = applicant(db, today+timedelta(days=1))
    draft.submitted_at = None
    withdrawn = applicant(db, today+timedelta(days=2))
    withdrawn.withdrawn_at = datetime.now(UTC)
    prepare(db, today+timedelta(days=30))
    db.commit()
    assert db.scalar(select(OpeningRetentionProtection)) is None
    assert not retention_is_current(expired)


def test_extending_an_elapsed_deadline_does_not_revive_expired_protected_records():
    from app.schemas.openings import OpeningUpdate
    from app.services.openings.catalog import update_opening
    db = memory_session(foreign_keys=True)
    now = datetime.now(UTC)
    today = pacific_today(now=now)
    row = applicant(db, today)
    opening = prepare(db, today-timedelta(days=1), now=now-timedelta(days=5))
    db.commit()
    assert db.scalar(select(OpeningRetentionProtection)) is not None
    assert not retention_is_current(row)
    original = {"unitSizeBedrooms": opening.unit_size_bedrooms, "housingChargeCents": opening.housing_charge_cents,
        "applicationOpenDate": None, "applicationCloseDate": opening.application_close_date, "moveInDate": opening.move_in_date}
    update_opening(db, opening, OpeningUpdate(original=original,
        changes={**original, "applicationCloseDate": today+timedelta(days=10)}))
    assert not retention_is_current(row)
    assert db.scalar(select(OpeningRetentionProtection)) is None


def test_submission_replaces_temporary_protection_with_decision_based_retention():
    from app.services.applications.retention import (
        one_year_after,
        refresh_application_retention,
    )
    from app.services.openings.participation import apply_opening_selection
    db = memory_session(foreign_keys=True)
    now = datetime.now(UTC)
    today = pacific_today(now=now)
    row = applicant(db, today+timedelta(days=1))
    opening = prepare(db, today+timedelta(days=10))
    apply_opening_selection(db, row, [opening], submitted_at=now)
    db.commit()
    assert row.retention_due_on is None
    assert retention_is_current(row, now=now+timedelta(days=40))
    opening.decided_at = now+timedelta(days=40)
    db.flush()
    refresh_application_retention(db, row)
    assert row.retention_due_on == one_year_after(today+timedelta(days=40))


def test_protection_granted_after_sweep_discovery_is_rechecked_under_writer_lock(monkeypatch):
    from app.services.applications import purge
    from app.services.applications.locking import lock_application
    from tests.test_write_concurrency import request_sessions
    factory, _, _, _ = request_sessions(closed=True)
    now = datetime.now(UTC)
    today = pacific_today(now=now)
    with factory() as db:
        row = applicant(db, today+timedelta(days=1))
        identity = row.id
        db.commit()

    def protect_before_lock(db, application_id):
        if application_id == identity:
            with factory() as writer:
                prepare(writer, today+timedelta(days=10), now=now)
                writer.commit()
        return lock_application(db, application_id)

    monkeypatch.setattr(purge, "lock_application", protect_before_lock)
    with factory() as db:
        purge_due_applicant_data(db, now=now+timedelta(days=1))
    with factory() as db:
        assert db.get(Application, identity) is not None
