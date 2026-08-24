from types import SimpleNamespace

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import RedirectResponse

from app.api.session_cookie import SESSION_COOKIE_NAMES
from app.core.config import Settings, get_settings
from app.db.models import (
    AccessAllowlistEntry,
    Base,
    BrowserSession,
    GoogleCredential,
    PasswordlessIdentityKind,
    User,
    UserRole,
)
from app.db.session import get_db
from app.main import create_app


class FakeGoogleOAuthClient:
    def __init__(self, user_info: dict | None = None) -> None:
        self.user_info = user_info or {}
        self.redirect_kwargs: dict | None = None

    async def authorize_redirect(self, _request, redirect_uri: str, **kwargs):
        self.redirect_kwargs = kwargs
        return RedirectResponse(redirect_uri)

    async def authorize_access_token(self, _request) -> dict:
        return {"userinfo": self.user_info}


def _app_and_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = test_session()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    return app, db


def _google_identity(**overrides) -> dict:
    return {
        "sub": "google-subject",
        "email": "member@example.test",
        "email_verified": True,
        "name": "Synthetic Member",
        "picture": "https://example.test/avatar.png",
        **overrides,
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("delivery_mode", "email_sign_in_enabled"),
    [("capture", False), ("development", True), ("production", True)],
)
async def test_me_reports_email_sign_in_capability(
    delivery_mode: str,
    email_sign_in_enabled: bool,
) -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        email_delivery_mode=delivery_mode,
        _env_file=None,
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "user": None,
        "emailSignInEnabled": email_sign_in_enabled,
    }


@pytest.mark.anyio
async def test_google_login_does_not_request_offline_access_or_force_consent(monkeypatch) -> None:
    app, _ = _app_and_db()
    google = FakeGoogleOAuthClient()
    monkeypatch.setattr("app.api.auth.get_oauth", lambda: SimpleNamespace(google=google))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/auth/google/login")

    assert response.status_code == 307
    assert google.redirect_kwargs == {}


@pytest.mark.anyio
async def test_google_login_issues_shared_session_and_preserves_sheet_token(monkeypatch) -> None:
    app, db = _app_and_db()
    user = User(
        email="member@example.test",
        display_name="Member",
        role=UserRole.ADMIN,
    )
    db.add_all(
        [
            user,
            AccessAllowlistEntry(email=user.email, role=UserRole.ADMIN),
        ]
    )
    db.commit()
    sheet_token = {
        "access_token": "sheet-access",
        "refresh_token": "sheet-refresh",
        "scope": "openid https://www.googleapis.com/auth/drive.file",
    }
    db.add(GoogleCredential(user_id=user.id, token=sheet_token))
    db.commit()
    google = FakeGoogleOAuthClient(_google_identity())
    monkeypatch.setattr("app.api.auth.get_oauth", lambda: SimpleNamespace(google=google))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/auth/google/callback")
        me = await client.get("/auth/me")
        sensitive_action = await client.put(
            "/allowlist",
            json={"email": "new-member@example.com", "role": "member"},
        )

    cookie_name = SESSION_COOKIE_NAMES[PasswordlessIdentityKind.COMMITTEE]
    assert response.status_code == 307
    assert cookie_name in response.cookies
    assert me.json()["user"]["email"] == user.email
    assert sensitive_action.status_code == 200, sensitive_action.text
    db.refresh(user)
    assert user.google_subject == "google-subject"
    assert db.scalar(select(func.count()).select_from(BrowserSession)) == 1
    credential = db.scalar(select(GoogleCredential).where(GoogleCredential.user_id == user.id))
    assert credential is not None
    assert credential.token == sheet_token


@pytest.mark.anyio
async def test_google_login_rejects_an_unverified_email(monkeypatch) -> None:
    app, db = _app_and_db()
    db.add(
        AccessAllowlistEntry(email="member@example.test", role=UserRole.MEMBER)
    )
    db.commit()
    google = FakeGoogleOAuthClient(_google_identity(email_verified=False))
    monkeypatch.setattr("app.api.auth.get_oauth", lambda: SimpleNamespace(google=google))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/auth/google/callback")

    assert response.status_code == 307
    assert response.headers["location"].endswith("?access=denied")
    assert db.scalar(select(func.count()).select_from(User)) == 0
    assert db.scalar(select(func.count()).select_from(BrowserSession)) == 0

