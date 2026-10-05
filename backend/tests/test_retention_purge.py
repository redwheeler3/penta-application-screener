from datetime import UTC, date, datetime, timedelta

from sqlalchemy import event, select
from sqlalchemy.orm import sessionmaker

from app.core.time import pacific_today
from app.db.models import (
    ApplicantDraft,
    ApplicantDraftIntent,
    Application,
    ApplicationAIResult,
    Feedback,
    RetentionDeletion,
    User,
    UserRole,
)
from app.schemas.openings import DirectSelectionOpeningCreate
from app.services.applications import purge
from app.services.applications.locking import lock_application
from app.services.applications.purge import purge_due_applicant_data
from app.services.openings.direct_selection import create_direct_selection_opening
from tests.db_support import memory_session
from tests.test_write_concurrency import request_sessions


def _db():
    return memory_session(foreign_keys=True)


def _due_application(db) -> Application:
    application = Application(
        primary_email="applicant@example.com",
        applicant_name="Synthetic Applicant",
        raw_row={"synthetic": True},
        raw_row_hash="synthetic",
        normalized={},
        submitted_at=datetime(2025, 8, 26, tzinfo=UTC),
        retention_due_on=date(2026, 8, 26),
        synthetic_data=True,
    )
    user = User(
        email="admin@example.com",
        display_name="Synthetic Admin",
        role=UserRole.ADMIN,
    )
    db.add_all([application, user])
    db.flush()
    db.add_all(
        [
            ApplicationAIResult(
                application_id=application.id,
                kind="screening",
                cache_key="synthetic-cache-key",
                model_id="synthetic-model",
                prompt_version="synthetic",
                output={},
            ),
            Feedback(
                user_id=user.id,
                body="Synthetic feedback",
                applicant_id=application.id,
                app_version="test",
            ),
        ]
    )
    db.commit()
    return application


def test_due_application_is_completely_purged() -> None:
    db = _db()
    application = _due_application(db)
    application_id = application.id
    result = purge_due_applicant_data(db, now=datetime(2026, 8, 26, 18, tzinfo=UTC))

    assert result.applications_purged == 1
    assert db.get(Application, application_id) is None
    assert db.scalar(select(ApplicationAIResult)) is None
    feedback = db.scalar(select(Feedback))
    assert feedback is not None
    assert feedback.applicant_id is None
    deletion = db.scalar(select(RetentionDeletion))
    assert deletion is not None
    assert deletion.record_kind == "application"
    assert deletion.record_id == application_id
    assert deletion.retention_rule == "one_year"


def test_due_unclaimed_draft_is_completely_purged() -> None:
    db = _db()
    draft = ApplicantDraft(
        email="draft@example.com",
        intent=ApplicantDraftIntent.SAVE,
        draft_token_hash="synthetic-draft-token",
        created_at=datetime(2025, 8, 26, tzinfo=UTC),
        saved_at=datetime(2025, 8, 26, tzinfo=UTC),
        expires_on=date(2026, 8, 26),
    )
    db.add(draft)
    db.commit()
    draft_id = draft.id

    result = purge_due_applicant_data(db, now=datetime(2026, 8, 26, 18, tzinfo=UTC))

    assert result.drafts_purged == 1
    assert db.get(ApplicantDraft, draft_id) is None
    deletion = db.scalar(select(RetentionDeletion))
    assert deletion is not None
    assert deletion.record_kind == "applicant_draft"
    assert deletion.record_id == draft_id
    assert deletion.retention_rule == "draft_actionability"


def test_selection_after_sweep_read_preserves_new_retention(monkeypatch) -> None:
    factory, _opening_id, admin_id, ids = request_sessions(closed=True)
    now = datetime.now(UTC)
    today = pacific_today(now=now)
    with factory() as db:
        db.get(Application, ids[0]).retention_due_on = today + timedelta(days=1)
        db.commit()

    def select_before_lock(db, application_id):
        with factory() as other:
            create_direct_selection_opening(other, DirectSelectionOpeningCreate(
                applicationId=application_id, unitSizeBedrooms=2, housingChargeCents=100_000,
                moveInDate=today + timedelta(days=30),
            ), decided_by=other.get(User, admin_id), now=now)
        return lock_application(db, application_id)

    monkeypatch.setattr(purge, "lock_application", select_before_lock)
    with factory() as db:
        result = purge_due_applicant_data(db, now=now + timedelta(days=1))
    with factory() as db:
        assert result.applications_purged == 0
        assert db.get(Application, ids[0]).retention_due_on.year == today.year + 7
        assert db.scalar(select(RetentionDeletion)) is None


def test_draft_renewed_after_sweep_read_is_not_deleted() -> None:
    db = _db()
    now = datetime(2026, 8, 26, 18, tzinfo=UTC)
    draft = ApplicantDraft(
        email="draft@example.com", intent=ApplicantDraftIntent.SAVE, draft_token_hash="synthetic",
        created_at=now, saved_at=now, expires_on=date(2026, 8, 26),
    )
    db.add(draft)
    db.commit()
    draft_id = draft.id
    factory = sessionmaker(bind=db.get_bind(), autoflush=False)
    renewed = []

    def renew_before_delete(_connection, _cursor, statement, _parameters, _context, _many):
        if not renewed and "UPDATE applicant_drafts SET saved_at=applicant_drafts.saved_at" in statement:
            renewed.append(True)
            with factory() as other:
                other.get(ApplicantDraft, draft_id).expires_on = date(2026, 9, 1)
                other.commit()

    event.listen(db.get_bind(), "before_cursor_execute", renew_before_delete)
    try:
        result = purge_due_applicant_data(db, now=now)
        assert renewed == [True]
        assert result.drafts_purged == 0
        assert db.get(ApplicantDraft, draft_id).expires_on == date(2026, 9, 1)
        assert db.scalar(select(RetentionDeletion)) is None
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", renew_before_delete)


def test_retention_expiry_blocks_sessions_scope_and_direct_selection() -> None:
    from app.db.models import PasswordlessIdentityKind
    from app.services.applications.scope import opening_applications
    from app.services.auth.applicant import authenticate_applicant
    from app.services.auth.passwordless import create_browser_session
    from app.services.openings.direct_selection import available_previous_applicant

    factory, opening_id, _, ids = request_sessions(closed=True)
    now = datetime.now(UTC)
    with factory() as db:
        application = db.get(Application, ids[0])
        token = create_browser_session(db, identity_kind=PasswordlessIdentityKind.APPLICANT,
                                       application_id=application.id, now=now - timedelta(days=1))
        application.retention_due_on = pacific_today(now=now)
        db.commit()
        assert application.id not in {app.id for app in opening_applications(db, opening_id)}
        assert available_previous_applicant(db, application.id) is None
        assert authenticate_applicant(db, token.token, now=now) is None
