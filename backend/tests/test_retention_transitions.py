from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.time import pacific_today
from app.db.models import (
    ApplicantDraft,
    ApplicantDraftIntent,
    Application,
    ApplicationParticipation,
    DailyMaintenanceRun,
    EmailDelivery,
    Opening,
    User,
    UserRole,
)
from app.schemas.applicant.answers import WorkingApplicationAnswers
from app.schemas.openings import OpeningCreate, OpeningUpdate
from app.services import maintenance
from app.services.applications.drafts import draft_is_available, save_pending_draft
from app.services.applications.intake import create_application, save_working_copy
from app.services.applications.purge import purge_due_applicant_data
from app.services.applications.retention import (
    one_year_after,
    refresh_application_retention,
    refresh_draft_retention_for_opening,
    retention_is_current,
)
from app.services.email.sender import EmailConfigurationError
from app.services.openings.catalog import create_opening, update_opening
from app.services.openings.selection import (
    confirm_no_household_selected,
    confirm_opening_selection,
)
from tests.applicant.support import sample_answers
from tests.db_support import memory_session


def opening(db, days):
    today = pacific_today()
    row = Opening(unit_size_bedrooms=2, housing_charge_cents=100000,
        application_open_date=today-timedelta(days=30), application_close_date=today+timedelta(days=days),
        move_in_date=today+timedelta(days=days+40), published_at=datetime.now(UTC))
    db.add(row)
    db.flush()
    return row


@pytest.mark.parametrize('decision', ['selected', 'none'])
@pytest.mark.parametrize('withdrawal', ['opening', 'profile'])
def test_final_decision_starts_retention_for_withdrawn_history(decision, withdrawal):
    db = memory_session(foreign_keys=True)
    now = datetime.now(UTC)
    op = opening(db, -1)
    households = []
    for email in ['withdrawn@example.com', 'winner@example.com']:
        row = Application(primary_email=email, raw_row={}, raw_row_hash=email, normalized={}, submitted_at=now)
        db.add(row)
        db.flush()
        part = ApplicationParticipation(application_id=row.id, opening_id=op.id, applied_at=now)
        db.add(part)
        households.append((row, part))
    withdrawn, participation = households[0]
    participation.withdrawn_at = now
    if withdrawal == 'profile':
        withdrawn.withdrawn_at = now
    db.flush()
    refresh_application_retention(db, withdrawn)
    admin = User(email='admin@example.com', display_name='Admin', role=UserRole.ADMIN, is_active=True)
    db.add(admin)
    db.commit()
    if decision == 'selected':
        confirm_opening_selection(db, op, households[1][0].id, decided_by=admin)
    else:
        confirm_no_household_selected(db, op, decided_by=admin)
    assert withdrawn.retention_due_on == one_year_after(pacific_today())
    assert db.scalar(select(EmailDelivery).where(EmailDelivery.application_id == withdrawn.id)) is None
    identity = withdrawn.id
    purge_due_applicant_data(db, now=now+timedelta(days=367))
    assert db.get(Application, identity) is None


@pytest.mark.parametrize('empty', [False, True])
def test_private_selection_changes_update_expiry_without_changing_submitted_deadlines(empty):
    db = memory_session()
    now = datetime.now(UTC)
    early, later = opening(db, 1), opening(db, 20)
    answers = WorkingApplicationAnswers.model_validate(sample_answers())
    app = create_application(db, 'avery@example.com', answers, saved_at=now,
        opening_ids=[] if empty else [early.id])
    assert app.retention_due_on == (later if empty else early).application_close_date+timedelta(days=1)
    save_working_copy(db, app, answers, saved_at=now, opening_ids=[later.id])
    assert app.retention_due_on == later.application_close_date+timedelta(days=1)
    save_working_copy(db, app, answers, saved_at=now, opening_ids=[early.id])
    assert app.retention_due_on == early.application_close_date+timedelta(days=1)
    app.submitted_at = now
    deadline = app.retention_due_on
    save_working_copy(db, app, answers, saved_at=now, opening_ids=[later.id])
    assert app.retention_due_on == deadline


def test_empty_selection_draft_follows_extended_fallback_opening():
    db = memory_session()
    op = opening(db, 1)
    app = create_application(db, 'avery@example.com', WorkingApplicationAnswers.model_validate(sample_answers()),
        saved_at=datetime.now(UTC), opening_ids=[])
    op.application_close_date += timedelta(days=10)
    db.flush()
    refresh_draft_retention_for_opening(db, op.id)
    assert app.retention_due_on == op.application_close_date+timedelta(days=1)


def test_sender_configuration_failure_does_not_block_purge_or_failure_receipt(monkeypatch):
    db = memory_session()
    app = Application(primary_email='due@example.com', raw_row={}, raw_row_hash='due', normalized={},
        retention_due_on=pacific_today()-timedelta(days=1))
    db.add(app)
    db.commit()
    identity = app.id
    monkeypatch.setattr(maintenance, 'SessionLocal', lambda: db)
    def unavailable():
        raise EmailConfigurationError('Synthetic missing configuration')
    monkeypatch.setattr(maintenance, 'get_email_sender', unavailable)
    maintenance.run_due_maintenance()
    assert db.get(Application, identity) is None
    attempt = db.scalar(select(DailyMaintenanceRun))
    assert attempt.status == 'failed'
    assert attempt.last_error_code == 'EmailConfigurationError'


def test_shortening_last_fallback_opening_keeps_a_finite_private_deadline():
    db = memory_session()
    op = opening(db, 10)
    app = create_application(db, 'avery@example.com', WorkingApplicationAnswers.model_validate(sample_answers()),
        saved_at=datetime.now(UTC), opening_ids=[])
    db.commit()
    original = {'unitSizeBedrooms': op.unit_size_bedrooms, 'housingChargeCents': op.housing_charge_cents,
        'applicationOpenDate': op.application_open_date, 'applicationCloseDate': op.application_close_date,
        'moveInDate': op.move_in_date}
    close = pacific_today()-timedelta(days=1)
    update_opening(db, op, OpeningUpdate(original=original, changes={**original, 'applicationCloseDate': close}))
    assert app.retention_due_on == close+timedelta(days=1)


def publish_opening(db, *, now, close):
    return create_opening(db, OpeningCreate(unitSizeBedrooms=2, housingChargeCents=100000,
        applicationCloseDate=close, moveInDate=close+timedelta(days=30)), now=now)


def private_copies(db, *, now, opening_ids, email):
    answers = WorkingApplicationAnswers.model_validate(sample_answers())
    answers.applicant.email = email
    application = create_application(db, email, answers, saved_at=now, opening_ids=opening_ids)
    pending = save_pending_draft(db, answers=answers, opening_ids=opening_ids,
        intent=ApplicantDraftIntent.SAVE, now=now).record
    db.commit()
    return application, pending


@pytest.mark.parametrize("days_expired", [0, 1])
@pytest.mark.parametrize("change", ["rent", "close"])
@pytest.mark.parametrize("explicit", [False, True])
def test_opening_edit_does_not_revive_expired_private_copies(days_expired, change, explicit):
    db = memory_session()
    now = datetime.now(UTC)
    today = pacific_today(now=now)
    past = now-timedelta(days=4)
    prior = publish_opening(db, now=past, close=today-timedelta(days=days_expired+1))
    application, pending = private_copies(db, now=past, opening_ids=[prior.id] if explicit else [],
        email="expired@example.test")
    deadline = today-timedelta(days=days_expired)
    assert application.retention_due_on == pending.expires_on == deadline
    assert not retention_is_current(application, now=now)
    assert not draft_is_available(pending, now=now)

    latest = publish_opening(db, now=now, close=today+timedelta(days=20))
    edited = latest if change == "rent" else prior
    original = {"unitSizeBedrooms": edited.unit_size_bedrooms, "housingChargeCents": edited.housing_charge_cents,
        "applicationOpenDate": edited.application_open_date, "applicationCloseDate": edited.application_close_date,
        "moveInDate": edited.move_in_date}
    changes = {**original, **({"housingChargeCents": 110000} if change == "rent"
        else {"applicationCloseDate": today+timedelta(days=5)})}
    update_opening(db, edited, OpeningUpdate(original=original, changes=changes))

    assert application.retention_due_on == pending.expires_on == deadline
    assert not retention_is_current(application, now=now)
    assert not draft_is_available(pending, now=now)


def test_publication_updates_current_fallback_copies_but_not_explicit_or_expired_copies():
    db = memory_session()
    now = datetime.now(UTC)
    today = pacific_today(now=now)
    past = now-timedelta(days=3)
    publish_opening(db, now=past, close=today-timedelta(days=1))
    expired, expired_pending = private_copies(db, now=past, opening_ids=[], email="elapsed@example.test")
    first = publish_opening(db, now=now, close=today+timedelta(days=1))
    fallback, fallback_pending = private_copies(db, now=now, opening_ids=[], email="fallback@example.test")
    explicit, explicit_pending = private_copies(db, now=now, opening_ids=[first.id], email="explicit@example.test")
    first_deadline = first.application_close_date+timedelta(days=1)
    assert fallback.retention_due_on == fallback_pending.expires_on == first_deadline

    later = publish_opening(db, now=now, close=today+timedelta(days=20))
    db.commit()
    assert fallback.retention_due_on == fallback_pending.expires_on == later.application_close_date+timedelta(days=1)
    assert explicit.retention_due_on == explicit_pending.expires_on == first_deadline
    assert expired.retention_due_on == expired_pending.expires_on == today

    fallback_id, pending_id = fallback.id, fallback_pending.id
    explicit_id, explicit_pending_id = explicit.id, explicit_pending.id
    purge_due_applicant_data(db, now=now+timedelta(days=2))
    assert db.get(Application, fallback_id) is not None
    assert db.get(ApplicantDraft, pending_id) is not None
    assert db.get(Application, explicit_id) is None
    assert db.get(ApplicantDraft, explicit_pending_id) is None
