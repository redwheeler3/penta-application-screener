"""Identity changes and reconciliation must preserve accepted answer revisions."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Response
from starlette.requests import Request

from app.api.applicant import links
from app.api.applicant.application import (
    reconcile_pending_copy,
    save_applicant_application,
)
from app.core.problems import Problem
from app.db.models import (
    ApplicantDraft,
    ApplicantDraftIntent,
    Application,
    BrowserSession,
    MagicLinkPurpose,
    PasswordlessIdentityKind,
)
from app.schemas.applicant.answers import WorkingApplicationAnswers
from app.schemas.applicant.contracts import (
    OpenAccessLinkRequest,
    ReconcilePendingCopyRequest,
    SaveApplicationRequest,
)
from app.services.applications.intake import save_working_copy
from app.services.auth.passwordless import create_browser_session, issue_magic_link
from app.services.email.sender import CapturedEmailSender
from tests.applicant.support import sample_answers
from tests.test_write_concurrency import request_sessions


def answers(text):
    return WorkingApplicationAnswers.model_validate(sample_answers(email="a1@example.com", introduction=text))


def comparison_records():
    factory, opening_id, _, ids = request_sessions(closed=False)
    now = datetime.now(UTC)
    with factory() as db:
        application = db.get(Application, ids[0])
        save_working_copy(db, application, answers("Original"), saved_at=now, opening_ids=[opening_id])
        draft = ApplicantDraft(
            email=application.primary_email, intent=ApplicantDraftIntent.SAVE, application_id=application.id,
            draft_token_hash="synthetic", working_answers=answers("Guest copy").model_dump(mode="json"),
            working_opening_ids=[opening_id], created_at=now, saved_at=now,
            expires_on=now.date() + timedelta(days=7),
        )
        db.add(draft)
        db.flush()
        session = create_browser_session(
            db, identity_kind=PasswordlessIdentityKind.APPLICANT, application_id=application.id,
            reconciliation_draft_id=draft.id,
        ).record
        db.commit()
        return factory, opening_id, application.id, session.id


@pytest.mark.parametrize("choice", ["saved", "guest"])
def test_reconciliation_rejects_a_newer_accepted_application_save(choice) -> None:
    factory, opening_id, application_id, session_id = comparison_records()
    with factory() as stale, factory() as fresh:
        application = stale.get(Application, application_id)
        session = stale.get(BrowserSession, session_id)
        body = ReconcilePendingCopyRequest(
            choice=choice, baseRevision=application.working_revision, guestSavedAt=session.reconciliation_draft.saved_at,
        )
        current = fresh.get(Application, application_id)
        saved = save_applicant_application(SaveApplicationRequest(
            answers=answers("Newer accepted save"), openingIds=[opening_id], baseRevision=current.working_revision,
        ), db=fresh, application=current)
        accepted_revision = saved.working_revision
        request = Request({"type": "http", "headers": []})
        request.state.passwordless_session = session
        with pytest.raises(Problem) as error:
            reconcile_pending_copy(body, request, application, stale)
        assert error.value.code == "stale_application"
        stale.rollback()
    with factory() as db:
        application = db.get(Application, application_id)
        assert application.working_revision == accepted_revision
        assert application.working_answers["essays"]["household_introduction"] == "Newer accepted save"
        assert db.get(BrowserSession, session_id).reconciliation_draft.resolved_at is None


@pytest.mark.parametrize("choice", ["saved", "guest"])
def test_reconciliation_rejects_guest_answers_changed_after_comparison(choice) -> None:
    factory, _opening_id, application_id, session_id = comparison_records()
    with factory() as stale, factory() as fresh:
        application = stale.get(Application, application_id)
        session = stale.get(BrowserSession, session_id)
        draft = session.reconciliation_draft
        body = ReconcilePendingCopyRequest(
            choice=choice, baseRevision=application.working_revision, guestSavedAt=draft.saved_at,
        )
        latest = fresh.get(ApplicantDraft, draft.id)
        latest.saved_at += timedelta(seconds=1)
        latest.working_answers = answers("Newer guest copy").model_dump(mode="json")
        fresh.commit()
        request = Request({"type": "http", "headers": []})
        request.state.passwordless_session = session
        with pytest.raises(Problem) as error:
            reconcile_pending_copy(body, request, application, stale)
        assert error.value.code == "pending_copy_changed"
        assert error.value.status == 409
        stale.rollback()
    with factory() as db:
        assert db.get(BrowserSession, session_id).reconciliation_draft.resolved_at is None
        assert db.get(Application, application_id).working_answers["essays"]["household_introduction"] == "Original"


def test_email_confirmation_merges_with_a_save_after_link_inspection(monkeypatch) -> None:
    factory, opening_id, application_id, _session_id = comparison_records()
    with factory() as db:
        credential = issue_magic_link(
            db, identity_kind=PasswordlessIdentityKind.APPLICANT, purpose=MagicLinkPurpose.EMAIL_CHANGE,
            email="changed@example.com", application_id=application_id,
        ).token
        db.commit()
    consume = links.consume_magic_link
    revisions = []

    def overlapping_save(db, token, **kwargs):
        with factory() as other:
            application = other.get(Application, application_id)
            saved = save_applicant_application(SaveApplicationRequest(
                answers=answers("Newer accepted save"), openingIds=[opening_id], baseRevision=application.working_revision,
            ), db=other, application=application)
            revisions.append(saved.working_revision)
        return consume(db, token, **kwargs)

    monkeypatch.setattr(links, "consume_magic_link", overlapping_save)
    with factory() as db:
        result = links.open_applicant_access_link(
            OpenAccessLinkRequest(token=credential, switchCurrent=False, rememberDevice=False),
            Request({"type": "http", "headers": []}), Response(), current=None, db=db, sender=CapturedEmailSender(),
        )
        assert result.state == "valid"
    with factory() as db:
        application = db.get(Application, application_id)
        assert application.working_revision == revisions[0] + 1
        assert application.working_answers["essays"]["household_introduction"] == "Newer accepted save"
        assert application.primary_email == "changed@example.com"
        assert application.working_answers["applicant"]["email"] == "changed@example.com"
