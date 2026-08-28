import re
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.session_cookie import SESSION_COOKIE_NAMES, set_session_cookie
from app.core.config import Settings
from app.db.models import (
    AccessAllowlistEntry,
    Application,
    Base,
    BrowserSession,
    EmailDelivery,
    EmailDeliveryState,
    MagicLinkPurpose,
    Opening,
    PasswordlessIdentityKind,
    User,
    UserRole,
)
from app.db.session import get_db
from app.main import create_app
from app.services.auth_email import magic_link_email
from app.services.email_sender import CapturedEmailSender, get_email_sender
from app.services.passwordless_auth import issue_magic_link


def _app_and_db() -> tuple:
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


def _application(db: Session, *, withdrawn: bool = False) -> Application:
    today = date.today()
    db.add(
        Opening(
            unit_size_bedrooms=2,
            housing_charge_cents=100_000,
            application_open_date=today - timedelta(days=1),
            application_close_date=today + timedelta(days=10),
            move_in_date=today + timedelta(days=30),
            published_at=datetime.now(UTC),
        )
    )
    application = Application(
        primary_email="applicant@example.test",
        applicant_name="Synthetic Applicant",
        raw_row={},
        raw_row_hash="synthetic",
        normalized={},
        withdrawn_at=datetime(2026, 8, 23, tzinfo=UTC) if withdrawn else None,
    )
    db.add(application)
    db.commit()
    return application


def _committee_user(db: Session) -> User:
    user = User(
        email="member@example.test",
        display_name="Synthetic Member",
        role=UserRole.MEMBER,
    )
    db.add_all(
        [
            user,
            AccessAllowlistEntry(email=user.email, role=UserRole.MEMBER),
        ]
    )
    db.commit()
    return user


class FailingEmailSender:
    def send(self, _message) -> str:
        raise TimeoutError("synthetic provider timeout")


@pytest.mark.anyio
async def test_committee_magic_link_creates_hashed_session_and_cannot_be_reused() -> None:
    app, db = _app_and_db()
    user = _committee_user(db)
    issued = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.COMMITTEE,
        user_id=user.id,
        email=user.email,
        purpose=MagicLinkPurpose.COMMITTEE_ACCESS,
    )
    db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/auth/magic-link/consume",
            json={"token": issued.token},
        )
        me = await client.get("/auth/me")
        logout = await client.post("/auth/logout")
        after_logout = await client.get("/auth/me")
        reused = await client.post(
            "/auth/magic-link/consume",
            json={"token": issued.token},
        )

    assert response.status_code == 200
    assert response.json()["user"]["email"] == user.email
    assert me.json()["user"]["email"] == user.email
    assert logout.status_code == 200
    assert after_logout.json()["user"] is None
    cookie_name = SESSION_COOKIE_NAMES[PasswordlessIdentityKind.COMMITTEE]
    assert cookie_name in response.cookies
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    assert reused.status_code == 401
    stored = db.scalar(select(BrowserSession))
    assert stored is not None
    assert stored.token_hash != response.cookies[cookie_name]
    assert stored.revoked_at is not None


@pytest.mark.anyio
async def test_used_committee_link_recognizes_its_active_browser_session() -> None:
    app, db = _app_and_db()
    user = _committee_user(db)
    issued = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.COMMITTEE,
        user_id=user.id,
        email=user.email,
        purpose=MagicLinkPurpose.COMMITTEE_ACCESS,
    )
    db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (
            await client.post("/auth/magic-link/consume", json={"token": issued.token})
        ).status_code == 200
        inspected = await client.post(
            "/auth/magic-link/inspect", json={"token": issued.token}
        )

    assert inspected.status_code == 200
    assert inspected.json() == {
        "state": "used",
        "currentUser": {
            "id": user.id,
            "email": user.email,
            "displayName": user.display_name,
            "avatarUrl": None,
            "role": "member",
        },
        "linkEmail": user.email,
        "switchRequired": False,
    }


@pytest.mark.anyio
async def test_committee_link_requires_confirmation_before_switching_active_user() -> None:
    app, db = _app_and_db()
    current = _committee_user(db)
    linked = User(
        email="other-member@example.test",
        display_name="Other Synthetic Member",
        role=UserRole.MEMBER,
    )
    db.add_all([linked, AccessAllowlistEntry(email=linked.email, role=UserRole.MEMBER)])
    db.commit()
    current_link = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.COMMITTEE,
        user_id=current.id,
        email=current.email,
        purpose=MagicLinkPurpose.COMMITTEE_ACCESS,
    )
    linked_link = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.COMMITTEE,
        user_id=linked.id,
        email=linked.email,
        purpose=MagicLinkPurpose.COMMITTEE_ACCESS,
    )
    db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (
            await client.post("/auth/magic-link/consume", json={"token": current_link.token})
        ).status_code == 200
        current_session = db.scalar(
            select(BrowserSession).where(BrowserSession.user_id == current.id)
        )
        inspected = await client.post(
            "/auth/magic-link/inspect", json={"token": linked_link.token}
        )
        refused = await client.post(
            "/auth/magic-link/consume", json={"token": linked_link.token}
        )
        switched = await client.post(
            "/auth/magic-link/consume",
            json={"token": linked_link.token, "switchCurrent": True},
        )

    assert current_session is not None
    assert inspected.json()["currentUser"]["email"] == current.email
    assert inspected.json()["linkEmail"] == linked.email
    assert inspected.json()["switchRequired"] is True
    assert refused.status_code == 409
    assert refused.json()["code"] == "session_switch_required"
    assert switched.status_code == 200
    assert switched.json()["user"]["email"] == linked.email
    db.refresh(current_session)
    assert current_session.revoked_at is not None


@pytest.mark.anyio
async def test_stale_committee_link_can_send_a_fresh_link_for_its_member() -> None:
    app, db = _app_and_db()
    user = _committee_user(db)
    sender = CapturedEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    issued = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.COMMITTEE,
        user_id=user.id,
        email=user.email,
        purpose=MagicLinkPurpose.COMMITTEE_ACCESS,
        now=datetime.now(UTC) - timedelta(days=2),
        lifetime=timedelta(hours=24),
    )
    db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        inspected = await client.post(
            "/auth/magic-link/inspect", json={"token": issued.token}
        )
        regenerated = await client.post(
            "/auth/magic-link/regenerate", json={"token": issued.token}
        )

    assert inspected.json()["state"] == "expired"
    assert regenerated.status_code == 202
    assert len(sender.messages) == 1
    assert sender.messages[0].to == (user.email,)


@pytest.mark.anyio
async def test_committee_remembered_device_choice_controls_cookie_persistence() -> None:
    app, db = _app_and_db()
    user = _committee_user(db)
    sender = CapturedEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        requested = await client.post(
            "/auth/magic-link",
            json={"email": user.email, "rememberDevice": True},
        )
        token = re.search(r"#magic-link=([^\s]+)", sender.messages[-1].text_body)
        assert token is not None
        consumed = await client.post(
            "/auth/magic-link/consume",
            json={"token": token.group(1)},
        )

    assert requested.status_code == 202
    assert "Max-Age=" in consumed.headers["set-cookie"]


@pytest.mark.anyio
async def test_wrong_host_exchange_does_not_consume_an_applicant_link() -> None:
    app, db = _app_and_db()
    application = _application(db)
    issued = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application.id,
        email=application.primary_email,
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
    )
    db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        wrong_host = await client.post(
            "/auth/magic-link/consume",
            json={"token": issued.token},
        )
        correct_host = await client.post(
            "/applicant/access-links/open",
            json={"token": issued.token, "switchCurrent": False},
        )

    assert wrong_host.status_code == 401
    assert correct_host.status_code == 200
    assert correct_host.json()["applicationId"] == application.id


@pytest.mark.anyio
async def test_applicant_and_committee_sessions_coexist_on_localhost() -> None:
    app, db = _app_and_db()
    application = _application(db)
    user = User(
        email=application.primary_email,
        display_name="Applicant Committee Member",
        role=UserRole.MEMBER,
    )
    db.add_all(
        [
            user,
            AccessAllowlistEntry(email=user.email, role=UserRole.MEMBER),
        ]
    )
    db.commit()
    applicant_link = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application.id,
        email=application.primary_email,
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
    )
    committee_link = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.COMMITTEE,
        user_id=user.id,
        email=user.email,
        purpose=MagicLinkPurpose.COMMITTEE_ACCESS,
    )
    db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        assert (
            await client.post(
                "/applicant/access-links/open",
                json={"token": applicant_link.token, "switchCurrent": False},
            )
        ).status_code == 200
        assert (
            await client.post(
                "/auth/magic-link/consume",
                json={"token": committee_link.token},
            )
        ).status_code == 200

        applicant_me = await client.get("/applicant/auth/me")
        committee_me = await client.get("/auth/me")
        cookie_names_before_logout = set(client.cookies.keys())
        await client.post("/auth/logout")
        applicant_after_committee_logout = await client.get("/applicant/auth/me")

    assert cookie_names_before_logout == set(SESSION_COOKIE_NAMES.values())
    assert applicant_me.json() == {"applicationId": application.id}
    assert committee_me.json()["user"]["email"] == user.email
    assert applicant_after_committee_logout.json() == {"applicationId": application.id}


@pytest.mark.anyio
async def test_withdrawn_application_cannot_establish_a_session() -> None:
    app, db = _app_and_db()
    application = _application(db, withdrawn=True)
    issued = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application.id,
        email=application.primary_email,
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
    )
    db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/applicant/access-links/open",
            json={"token": issued.token, "switchCurrent": False},
        )

    assert response.status_code == 200
    assert response.json()["state"] == "abandoned"
    assert db.scalar(select(func.count()).select_from(BrowserSession)) == 0


@pytest.mark.anyio
async def test_magic_link_request_is_non_enumerating_and_coalesces_email() -> None:
    app, db = _app_and_db()
    user = _committee_user(db)
    sender = CapturedEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        known = await client.post("/auth/magic-link", json={"email": user.email})
        repeated = await client.post("/auth/magic-link", json={"email": user.email})
        unknown = await client.post(
            "/auth/magic-link", json={"email": "unknown@example.test"}
        )

    assert known.status_code == 202
    assert repeated.json() == known.json()
    assert unknown.json() == known.json()
    assert len(sender.messages) == 1
    assert sender.messages[0].to == (user.email,)
    assert "#magic-link=" in sender.messages[0].text_body
    delivery = db.scalar(select(EmailDelivery))
    assert delivery is not None
    assert delivery.state == EmailDeliveryState.ACCEPTED
    assert delivery.provider_message_id == "captured-1"
    assert delivery.user_id == user.id


@pytest.mark.anyio
async def test_remembered_session_can_change_committee_access() -> None:
    app, db = _app_and_db()
    user = User(
        email="admin@example.test",
        display_name="Synthetic Admin",
        role=UserRole.ADMIN,
    )
    db.add_all(
        [
            user,
            AccessAllowlistEntry(email=user.email, role=UserRole.ADMIN),
        ]
    )
    db.commit()
    issued = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.COMMITTEE,
        user_id=user.id,
        email=user.email,
        purpose=MagicLinkPurpose.COMMITTEE_ACCESS,
    )
    db.commit()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (
            await client.post(
                "/auth/magic-link/consume",
                json={"token": issued.token},
            )
        ).status_code == 200
        browser_session = db.scalar(select(BrowserSession))
        assert browser_session is not None
        browser_session.created_at = datetime.now(UTC) - timedelta(days=2)
        db.commit()

        response = await client.put(
            "/allowlist",
            json={"email": "new-member@example.com", "role": "member"},
        )

    assert response.status_code == 200
    assert db.scalar(
        select(AccessAllowlistEntry).where(
            AccessAllowlistEntry.email == "new-member@example.com"
        )
    ) is not None


@pytest.mark.anyio
async def test_failed_delivery_is_observable_without_exposing_recipient_content() -> None:
    app, db = _app_and_db()
    user = _committee_user(db)
    app.dependency_overrides[get_email_sender] = lambda: FailingEmailSender()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/auth/magic-link", json={"email": user.email})

    assert response.status_code == 202
    delivery = db.scalar(select(EmailDelivery))
    assert delivery is not None
    assert delivery.state == EmailDeliveryState.FAILED
    assert delivery.last_error_code == "TimeoutError"
    assert delivery.provider_message_id is None
    assert not hasattr(delivery, "email")
    assert not hasattr(delivery, "body")
    assert delivery.magic_link_token.revoked_at is not None


def test_passwordless_cookie_is_host_only_secure_and_bounded() -> None:
    from fastapi import Response

    response = Response()
    settings = Settings(
        applicant_frontend_url="https://applications.pentacoop.com",
        session_absolute_days=30,
        _env_file=None,
    )

    set_session_cookie(
        response,
        "raw-session-token",
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        settings=settings,
        persistent=True,
    )

    cookie = response.headers["set-cookie"]
    assert "Max-Age=2592000" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" in cookie
    assert "Domain=" not in cookie


def test_magic_link_email_uses_fragment_and_common_unsubscribe_footer() -> None:
    settings = Settings(
        applicant_frontend_url="https://applications.pentacoop.com/",
        frontend_url="https://screener.pentacoop.com/",
        magic_link_lifetime_hours=24,
        _env_file=None,
    )

    applicant = magic_link_email(
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
        recipient_id=42,
        email="applicant@example.test",
        token="secret-token",
        settings=settings,
    )
    committee = magic_link_email(
        identity_kind=PasswordlessIdentityKind.COMMITTEE,
        purpose=MagicLinkPurpose.COMMITTEE_ACCESS,
        recipient_id=7,
        email="member@example.test",
        token="committee-token",
        settings=settings,
    )

    assert "#applicant-link=secret-token" in applicant.text_body
    assert applicant.subject == "Continue your Penta application"
    assert "Continue your application" in applicant.html_body
    assert "Review or update your Penta housing application." in applicant.html_body
    assert ">Open application<" in applicant.html_body
    assert "HsTracking" not in applicant.html_body
    assert "PENTA HOUSING CO-OP" in applicant.html_body
    assert 'src="https://www.pentacoop.com/email-house.png"' in applicant.html_body
    assert 'width="36" height="36" alt=""' in applicant.html_body
    assert "background-color:#16a34a" in applicant.html_body
    assert "expires in" not in applicant.text_body
    assert "expires in" not in applicant.html_body
    assert "application:42" == applicant.recipient_id
    assert "#magic-link=committee-token" in committee.text_body
    assert "HsTracking" not in committee.html_body
    assert "PENTA HOUSING CO-OP" in committee.html_body
    assert "expires in" not in committee.text_body
    assert "expires in" not in committee.html_body
    for message in (applicant, committee):
        assert "{{HsUnsubscribe}}" in message.text_body
        assert "This email address is not monitored." in message.text_body
        assert "1717 Wallace Street, Vancouver, BC V6R 4J7" in message.text_body
        assert "Privacy questions" not in message.html_body
        assert (
            'not monitored.</span><br><span style="display:inline-block;margin-top:8px;">'
            "Sent by" in message.html_body
        )
        assert (
            'V6R 4J7</span><br><strong style="display:inline-block;margin-top:8px;">'
            "<HsUnsubscribe>" in message.html_body
        )
        assert (
            "<HsUnsubscribe>Click here to permanently unsubscribe.</HsUnsubscribe>"
            "</strong> <span>Penta will no longer be able to email you"
            in message.html_body
        )
        assert "Penta will no longer be able to email you" in message.text_body
        assert "Penta Tech Support" not in message.text_body
        assert "techsupport@pentacoop.com" not in message.html_body
