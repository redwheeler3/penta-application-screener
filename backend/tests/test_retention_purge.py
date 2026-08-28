from datetime import UTC, date, datetime

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    ApplicantDraft,
    ApplicantDraftIntent,
    Application,
    ApplicationAIResult,
    Base,
    Feedback,
    RetentionDeletion,
    User,
    UserRole,
)
from app.services.retention_purge import purge_due_applicant_data


def _db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


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
        retention_due_on=date(2026, 8, 26),
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
    assert deletion.retention_rule == "one_year"
