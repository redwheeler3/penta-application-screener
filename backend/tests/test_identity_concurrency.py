"""Identity creation and access claims recheck facts after acquiring SQLite's writer."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest
from fastapi import BackgroundTasks, Response
from sqlalchemy import create_engine, event, select

from app.api.applicant.application import save_applicant_application
from app.api.applicant.guest import delete_applicant_draft, submit_guest_application
from app.api.passwordless_auth import request_committee_magic_link
from app.core.problems import Problem
from app.db.models import (
    AccessAllowlistEntry,
    AdminSetting,
    ApplicantDraft,
    ApplicantDraftIntent,
    Application,
    Base,
    BrowserSession,
    EmailDelivery,
    EmailDeliveryState,
    MagicLinkPurpose,
    MagicLinkToken,
    Opening,
    PasswordlessIdentityKind,
    RetentionDeletion,
    User,
    UserRole,
)
from app.schemas.applicant.answers import WorkingApplicationAnswers
from app.schemas.applicant.contracts import (
    AccessLinkRequest,
    GuestSubmitApplicationRequest,
    SaveApplicationRequest,
)
from app.schemas.passwordless_auth import MagicLinkRequest
from app.schemas.settings import AppSettings
from app.services.applications.access import claim_link_target, link_target
from app.services.applications.drafts import save_collision_copy, save_pending_draft
from app.services.auth.allowlist import get_entry, remove_entry, upsert_entry
from app.services.auth.applicant_google import claim_or_create_google_application
from app.services.auth.passwordless import consume_magic_link, issue_magic_link
from app.services.email.sender import CapturedEmailSender
from app.services.settings import save_app_settings
from tests.applicant.support import sample_answers
from tests.test_write_concurrency import request_sessions


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'identity.db'}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def pragmas(connection, _record):
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")

    Base.metadata.create_all(engine)
    yield request_sessions(closed=False, engine=engine)
    engine.dispose()


@pytest.mark.parametrize("other", ["google", "guest"])
def test_simultaneous_first_identity_claims_create_one_application(database, other):
    factory, opening_id, _admin, _ids = database
    ready = Barrier(2)

    def claim(kind):
        with factory() as db:
            assert db.scalar(select(Application).where(Application.primary_email == "new@example.com")) is None
            ready.wait(timeout=5)
            if kind == "google":
                application = claim_or_create_google_application(db, google_subject="synthetic-subject", email="new@example.com")
                db.commit()
                return application.id
            body = GuestSubmitApplicationRequest.model_validate({"answers": sample_answers("new@example.com"),
                "openingIds": [opening_id], "declarationAccepted": True})
            rejected = None
            try:
                submit_guest_application(body, BackgroundTasks(), db, CapturedEmailSender(), lambda _sender: None)
            except Problem as error:
                rejected = error.code
            assert rejected in {None, "application_already_exists"}
            return db.scalar(select(Application.id).where(Application.primary_email == "new@example.com"))

    with ThreadPoolExecutor(max_workers=2) as workers:
        first, second = workers.submit(claim, "google"), workers.submit(claim, other)
        assert first.result(timeout=6) == second.result(timeout=6)
    with factory() as db:
        applications = db.scalars(select(Application).where(Application.primary_email == "new@example.com")).all()
        assert len(applications) == 1
        assert applications[0].google_subject == "synthetic-subject"


def test_loaded_opening_cannot_permit_a_save_after_finalization(database):
    factory, opening_id, _admin, ids = database
    with factory() as first, factory() as other:
        application = first.get(Application, ids[0])
        opening = first.get(Opening, opening_id)
        finalized = other.get(Opening, opening_id)
        finalized.decided_at = datetime.now(UTC)
        other.commit()
        assert opening.decided_at is None
        body = SaveApplicationRequest.model_validate({"answers": sample_answers("a1@example.com"),
            "openingIds": [opening_id], "baseRevision": 1})
        with pytest.raises(Problem) as rejected:
            save_applicant_application(body, first, application)
        assert rejected.value.code == "applications_locked"
        first.rollback()
        assert first.get(Application, ids[0]).working_revision == 1


def test_collision_copy_cannot_attach_an_old_email_after_identity_changes(database):
    factory, opening_id, _admin, ids = database
    with factory() as first, factory() as other:
        application = first.get(Application, ids[0])
        changed = other.get(Application, ids[0])
        changed.primary_email = "changed@example.com"
        other.commit()
        with pytest.raises(Problem) as rejected:
            save_collision_copy(first, application=application,
                answers=WorkingApplicationAnswers.model_validate(sample_answers("a1@example.com")), opening_ids=[opening_id])
        assert rejected.value.code == "stale_application"
        first.rollback()
        assert first.scalar(select(ApplicantDraft)) is None


def test_concurrent_first_settings_saves_upsert_one_record(database):
    factory, _opening, _admin, _ids = database
    ready = Barrier(2)

    def save(workers):
        with factory() as db:
            assert db.scalar(select(AdminSetting)) is None
            ready.wait(timeout=5)
            settings = AppSettings()
            settings.ai.max_workers = workers
            return save_app_settings(db, settings).ai.max_workers

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(save, 11), pool.submit(save, 12)
        assert first.result(timeout=6) == 11
        assert second.result(timeout=6) == 12
    with factory() as db:
        assert len(db.scalars(select(AdminSetting)).all()) == 1


@pytest.mark.parametrize("change", ["remove", "demote"])
def test_sign_in_cannot_restore_preloaded_access_after_a_change(database, change):
    factory, _opening, admin_id, _ids = database
    with factory() as seed:
        seed.add(AccessAllowlistEntry(email="admin@example.com", role=UserRole.ADMIN))
        seed.commit()
    with factory() as first, factory() as other:
        user = first.get(User, admin_id)
        entry = get_entry(first, user.email)
        assert entry.role == UserRole.ADMIN
        if change == "remove":
            remove_entry(other, user.email)
        else:
            upsert_entry(other, email=user.email, role=UserRole.MEMBER)
        request_committee_magic_link(MagicLinkRequest(email=user.email), first, CapturedEmailSender())
    with factory() as db:
        current = db.get(User, admin_id)
        assert current.is_active == (change == "demote")
        if change == "demote":
            assert current.role == UserRole.MEMBER


def test_preloaded_draft_cannot_be_claimed_after_revocation(database):
    factory, opening_id, _admin, _ids = database
    with factory() as seed:
        draft = save_pending_draft(seed, answers=WorkingApplicationAnswers.model_validate(sample_answers("new@example.com")),
            opening_ids=[opening_id], intent=ApplicantDraftIntent.SAVE)
        issued = issue_magic_link(seed, identity_kind=PasswordlessIdentityKind.APPLICANT,
            purpose=MagicLinkPurpose.APPLICANT_ACCESS, email="new@example.com", applicant_draft_id=draft.record.id)
        seed.commit()
        token, draft_id = issued.token, draft.record.id
    with factory() as first, factory() as other:
        from app.services.applications.access import applicant_link

        link = applicant_link(first, token)
        assert link_target(first, link).id == draft_id
        revoked = other.get(ApplicantDraft, draft_id)
        revoked.revoked_at = datetime.now(UTC)
        other.commit()
        consumed = consume_magic_link(first, token, identity_kind=PasswordlessIdentityKind.APPLICANT,
            purpose=MagicLinkPurpose.APPLICANT_ACCESS)
        result = claim_link_target(first, consumed)
        assert result.application is None
        assert result.state == "abandoned"
        first.commit()
        assert first.scalar(select(Application).where(Application.primary_email == "new@example.com")) is None


def test_clearing_a_guest_copy_removes_its_data_without_ending_application_auth(database):
    from datetime import timedelta

    factory, opening_id, _admin, ids = database
    now = datetime.now(UTC)
    with factory() as db:
        saved = save_pending_draft(db, answers=WorkingApplicationAnswers.model_validate(sample_answers("a1@example.com")),
            opening_ids=[opening_id], intent=ApplicantDraftIntent.SAVE)
        issued = issue_magic_link(db, identity_kind=PasswordlessIdentityKind.APPLICANT,
            purpose=MagicLinkPurpose.APPLICANT_ACCESS, email="a1@example.com", applicant_draft_id=saved.record.id)
        session = BrowserSession(identity_kind=PasswordlessIdentityKind.APPLICANT, application_id=ids[0],
            reconciliation_draft_id=saved.record.id, token_hash="synthetic-session", created_at=now, last_activity_at=now,
            idle_expires_at=now + timedelta(days=1), absolute_expires_at=now + timedelta(days=2))
        db.add_all([session, EmailDelivery(recipient_kind=PasswordlessIdentityKind.APPLICANT, message_kind="applicant_magic_link",
            applicant_draft_id=saved.record.id, magic_link_token_id=issued.record.id, state=EmailDeliveryState.QUEUED)])
        db.commit()
        draft_id, session_id = saved.record.id, session.id
        delete_applicant_draft(AccessLinkRequest(token=saved.token), db)
        assert db.get(ApplicantDraft, draft_id) is None
        assert db.scalar(select(EmailDelivery)) is None
        assert db.get(BrowserSession, session_id, populate_existing=True).reconciliation_draft_id is None
        fact = db.scalar(select(RetentionDeletion))
        assert fact.record_kind == "applicant_draft"
        assert fact.record_id == draft_id


def test_explicit_draft_profile_deletion_has_a_restore_deletion_fact(database):
    from app.api.applicant.application import withdraw_applicant_application

    factory, _opening, _admin, ids = database
    with factory() as db:
        withdraw_applicant_application(Response(), db.get(Application, ids[0]), db)
        assert db.get(Application, ids[0]) is None
        fact = db.scalar(select(RetentionDeletion).where(RetentionDeletion.record_kind == "application"))
        assert fact.record_id == ids[0]
        assert fact.retention_rule == "explicit_application_delete"


def test_late_email_failure_cannot_revoke_a_new_credential_after_copy_deletion(database):
    from app.core.config import get_settings
    from app.services.email.delivery import (
        attempt_reserved_delivery,
        claim_delivery_attempt,
    )
    from app.services.email.sender import EmailRetryableError
    from app.services.email.templates import magic_link_email

    factory, opening_id, _admin, _ids = database
    with factory() as db:
        saved = save_pending_draft(db, answers=WorkingApplicationAnswers.model_validate(sample_answers("new@example.com")),
            opening_ids=[opening_id], intent=ApplicantDraftIntent.SAVE)
        issued = issue_magic_link(db, identity_kind=PasswordlessIdentityKind.APPLICANT,
            purpose=MagicLinkPurpose.APPLICANT_ACCESS, email="new@example.com", applicant_draft_id=saved.record.id)
        old_token_id = issued.record.id
        delivery = EmailDelivery(recipient_kind=PasswordlessIdentityKind.APPLICANT, message_kind="applicant_magic_link",
            applicant_draft_id=saved.record.id, magic_link_token_id=old_token_id, state=EmailDeliveryState.QUEUED,
            attempt_count=0, retry_intent={"type": "magic_link", "purpose": "applicant_access"})
        db.add(delivery)
        db.commit()
        attempt = claim_delivery_attempt(db, delivery.id, now=datetime.now(UTC))
        message = magic_link_email(identity_kind=PasswordlessIdentityKind.APPLICANT, purpose=MagicLinkPurpose.APPLICANT_ACCESS,
            recipient_id=saved.record.id, email="new@example.com", token=issued.token, settings=get_settings())
        new_token_ids = []

        class LaterFailure:
            def send(self, _message):
                with factory() as other:
                    delete_applicant_draft(AccessLinkRequest(token=saved.token), other)
                    replacement = save_pending_draft(other,
                        answers=WorkingApplicationAnswers.model_validate(sample_answers("replacement@example.com")),
                        opening_ids=[opening_id], intent=ApplicantDraftIntent.SAVE)
                    new = issue_magic_link(other, identity_kind=PasswordlessIdentityKind.APPLICANT,
                        purpose=MagicLinkPurpose.APPLICANT_ACCESS, email="replacement@example.com", applicant_draft_id=replacement.record.id)
                    other.commit()
                    new_token_ids.append(new.record.id)
                raise EmailRetryableError("Synthetic delayed provider failure")

        assert attempt_reserved_delivery(db, LaterFailure(), attempt, message) is False
        assert new_token_ids[0] > old_token_id
        assert db.get(MagicLinkToken, new_token_ids[0], populate_existing=True).revoked_at is None
