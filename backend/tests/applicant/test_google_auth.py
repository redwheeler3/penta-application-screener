from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import func, select
from starlette.responses import RedirectResponse

from app.api.session_cookie import SESSION_COOKIE_NAMES
from app.db.models import Application, BrowserSession, Opening, PasswordlessIdentityKind
from app.services.passwordless_auth import create_browser_session
from tests.applicant.support import app_and_db, sample_answers, save_draft


class FakeGoogleOAuthClient:
    def __init__(self, user_info: dict | None = None) -> None:
        self.user_info = user_info or {}
        self.redirect_uri: str | None = None
        self.redirect_kwargs: dict | None = None

    async def authorize_redirect(self, _request, redirect_uri: str, **kwargs):
        self.redirect_uri = redirect_uri
        self.redirect_kwargs = kwargs
        return RedirectResponse(redirect_uri)

    async def authorize_access_token(self, _request) -> dict:
        return {"userinfo": self.user_info}


def google_identity(**overrides) -> dict:
    return {
        "sub": "applicant-google-subject",
        "email": "avery@example.com",
        "email_verified": True,
        **overrides,
    }


@pytest.mark.anyio
async def test_google_login_uses_the_applicant_callback(monkeypatch) -> None:
    app, _, _ = app_and_db()
    google = FakeGoogleOAuthClient()
    monkeypatch.setattr(
        "app.api.applicant.google.get_oauth",
        lambda: SimpleNamespace(google=google),
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/applicant/auth/google/login?remember_device=true")

    assert response.status_code == 307
    assert google.redirect_uri == "http://localhost:8000/applicant/auth/google/callback"
    assert google.redirect_kwargs == {}


@pytest.mark.anyio
async def test_new_google_identity_opens_a_private_application(monkeypatch) -> None:
    app, db, _ = app_and_db()
    google = FakeGoogleOAuthClient(google_identity())
    monkeypatch.setattr(
        "app.api.applicant.google.get_oauth",
        lambda: SimpleNamespace(google=google),
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/applicant/auth/google/callback")
        application_response = await client.get("/applicant/application")

    application = db.scalar(select(Application))
    assert response.status_code == 307
    assert response.headers["location"] == "http://localhost:5173/?applicant"
    assert application_response.status_code == 200
    assert application_response.json()["primaryEmail"] == "avery@example.com"
    assert application_response.json()["answers"]["applicant"]["email"] == "avery@example.com"
    assert application is not None
    assert application.google_subject == "applicant-google-subject"
    assert application.submitted_at is None
    assert SESSION_COOKIE_NAMES[PasswordlessIdentityKind.APPLICANT] in response.cookies


@pytest.mark.anyio
async def test_google_claims_an_email_saved_draft(monkeypatch) -> None:
    app, db, _ = app_and_db()
    google = FakeGoogleOAuthClient(google_identity())
    monkeypatch.setattr(
        "app.api.applicant.google.get_oauth",
        lambda: SimpleNamespace(google=google),
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        saved = await save_draft(client)
        response = await client.get("/applicant/auth/google/callback")
        application_response = await client.get("/applicant/application")

    assert saved.status_code == 202
    assert response.status_code == 307
    assert application_response.json()["answers"] == sample_answers()
    application = db.scalar(select(Application))
    assert application is not None
    assert application.google_subject == "applicant-google-subject"


@pytest.mark.anyio
async def test_google_refuses_a_different_subject_for_the_same_email(monkeypatch) -> None:
    app, db, _ = app_and_db()
    db.add(
        Application(
            google_subject="existing-subject",
            primary_email="avery@example.com",
            raw_row={},
            raw_row_hash="synthetic",
            normalized={},
        )
    )
    db.commit()
    google = FakeGoogleOAuthClient(google_identity(sub="different-subject"))
    monkeypatch.setattr(
        "app.api.applicant.google.get_oauth",
        lambda: SimpleNamespace(google=google),
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/applicant/auth/google/callback")

    assert response.status_code == 307
    assert "google_access=identity_conflict" in response.headers["location"]
    assert db.scalar(select(func.count()).select_from(BrowserSession)) == 0


@pytest.mark.anyio
async def test_google_requires_a_verified_email(monkeypatch) -> None:
    app, db, _ = app_and_db()
    google = FakeGoogleOAuthClient(google_identity(email_verified=False))
    monkeypatch.setattr(
        "app.api.applicant.google.get_oauth",
        lambda: SimpleNamespace(google=google),
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/applicant/auth/google/callback")

    assert response.status_code == 307
    assert "google_access=denied" in response.headers["location"]
    assert db.scalar(select(func.count()).select_from(Application)) == 0


@pytest.mark.anyio
async def test_google_does_not_create_an_application_after_the_deadline(monkeypatch) -> None:
    app, db, _ = app_and_db()
    opening = db.scalar(select(Opening))
    assert opening is not None
    opening.application_close_date = date.today() - timedelta(days=1)
    db.commit()
    google = FakeGoogleOAuthClient(google_identity())
    monkeypatch.setattr(
        "app.api.applicant.google.get_oauth",
        lambda: SimpleNamespace(google=google),
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/applicant/auth/google/callback")

    assert response.status_code == 307
    assert "google_access=applications_closed" in response.headers["location"]
    assert db.scalar(select(func.count()).select_from(Application)) == 0


@pytest.mark.anyio
async def test_google_does_not_replace_a_different_active_applicant_session(monkeypatch) -> None:
    app, db, _ = app_and_db()
    current = Application(
        primary_email="current@example.com",
        raw_row={},
        raw_row_hash="current",
        normalized={},
    )
    target = Application(
        primary_email="target@example.com",
        raw_row={},
        raw_row_hash="target",
        normalized={},
    )
    db.add_all([current, target])
    db.flush()
    issued = create_browser_session(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=current.id,
    )
    db.commit()
    google = FakeGoogleOAuthClient(
        google_identity(email="target@example.com", sub="target-subject")
    )
    monkeypatch.setattr(
        "app.api.applicant.google.get_oauth",
        lambda: SimpleNamespace(google=google),
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(
            SESSION_COOKIE_NAMES[PasswordlessIdentityKind.APPLICANT],
            issued.token,
        )
        response = await client.get("/applicant/auth/google/callback")
        still_current = await client.get("/applicant/application")

    db.refresh(target)
    assert "google_access=session_conflict" in response.headers["location"]
    assert still_current.json()["primaryEmail"] == "current@example.com"
    assert target.google_subject is None
