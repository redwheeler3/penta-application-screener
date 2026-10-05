"""A browser page's displayed identity owns its actions, not a substituted cookie."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Response
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select
from starlette.routing import Route

from app.api.session_cookie import SESSION_COOKIE_NAMES, set_session_cookie
from app.core.config import get_settings
from app.db.models import (
    AccessAllowlistEntry,
    Application,
    ApplicationNote,
    PasswordlessIdentityKind,
    User,
    UserRole,
)
from app.db.session import get_db
from app.main import create_app
from app.services.auth.passwordless import create_browser_session
from tests.application_support import activate_application, current_opening_id
from tests.db_support import memory_session


def identities(kind):
    db = memory_session()
    if kind == PasswordlessIdentityKind.COMMITTEE:
        actors = [User(email=f"member{i}@example.test", display_name="Synthetic", role=UserRole.MEMBER) for i in (1, 2)]
        db.add_all(actors)
        db.add_all([AccessAllowlistEntry(email=actor.email, role=actor.role) for actor in actors])
        db.commit()
    else:
        actors = [activate_application(db, Application(primary_email=f"app{i}@example.test", raw_row={},
                  raw_row_hash=f"h{i}", normalized={}, submitted_at=datetime.now(UTC))) for i in (1, 2)]
    sessions = [create_browser_session(db, identity_kind=kind,
        **({"user_id": actor.id} if kind == PasswordlessIdentityKind.COMMITTEE else {"application_id": actor.id}))
        for actor in actors]
    db.commit()
    app = create_app(maintenance_task=lambda: None)
    app.dependency_overrides[get_db] = lambda: db
    return app, db, actors, sessions


@pytest.mark.anyio
async def test_cookie_switch_cannot_attribute_a_note_or_logout_to_another_member():
    kind = PasswordlessIdentityKind.COMMITTEE
    app, db, actors, sessions = identities(kind)
    application = activate_application(db, Application(primary_email="candidate@example.test", raw_row={},
        raw_row_hash="h", normalized={}, submitted_at=datetime.now(UTC)))
    opening_id = current_opening_id(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        client.cookies.set(SESSION_COOKIE_NAMES[kind], sessions[1].token, domain="testserver.local", path="/")
        headers = {"X-Penta-Identity": f"committee:{actors[0].id}", "Sec-Fetch-Site": "same-origin"}
        response = await client.put(f"/applications/{application.id}/note?opening_id={opening_id}",
                                    json={"note": "Stale page draft"}, headers=headers)
        assert response.status_code == 409
        assert response.json()["code"] == "session_changed"
        assert db.scalar(select(ApplicationNote)) is None
        assert (await client.post("/auth/logout", headers=headers)).status_code == 409
        assert sessions[1].record.revoked_at is None
        # A browser cannot silently fall back to an unbound protected request.
        assert (await client.get("/applications", headers={"Sec-Fetch-Site": "same-origin"})).status_code == 409
        assert (await client.get("/applications", headers={"X-Penta-Identity": f"committee:{actors[1].id}"})).status_code == 200


@pytest.mark.anyio
async def test_cookie_switch_cannot_read_or_withdraw_another_application():
    kind = PasswordlessIdentityKind.APPLICANT
    app, _db, actors, sessions = identities(kind)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        client.cookies.set(SESSION_COOKIE_NAMES[kind], sessions[1].token, domain="testserver.local", path="/")
        headers = {"X-Penta-Identity": f"applicant:{actors[0].id}"}
        assert (await client.get("/applicant/application", headers=headers)).status_code == 409
        assert (await client.post("/applicant/application/withdraw", headers=headers)).status_code == 409
        assert actors[0].withdrawn_at is None
        assert actors[1].withdrawn_at is None
        assert sessions[1].record.revoked_at is None


@pytest.mark.anyio
@pytest.mark.parametrize("kind", list(PasswordlessIdentityKind))
@pytest.mark.parametrize("operation", ["expired_read", "logout"])
async def test_delayed_response_cannot_delete_a_newer_sign_in_cookie(kind, operation):
    app, db, actors, sessions = identities(kind)
    if operation == "expired_read":
        sessions[0].record.idle_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    ready, release = asyncio.Event(), asyncio.Event()
    path = "/auth/me" if kind == PasswordlessIdentityKind.COMMITTEE else "/applicant/auth/me"
    if operation == "logout":
        path = "/auth/logout" if kind == PasswordlessIdentityKind.COMMITTEE else "/applicant/auth/logout"
    @app.middleware("http")
    async def delay_old_response(request, call_next):
        response = await call_next(request)
        if request.url.path == path:
            ready.set()
            await release.wait()
        return response
    async def sign_in(_request):
        response = Response()
        set_session_cookie(response, sessions[1].token, identity_kind=kind, settings=get_settings())
        return response
    app.router.routes.insert(0, Route("/test-sign-in", sign_in, methods=["POST"]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        client.cookies.set(SESSION_COOKIE_NAMES[kind], sessions[0].token, domain="testserver.local", path="/")
        headers = {"X-Penta-Identity": f"{kind.value}:{actors[0].id}"} if operation == "logout" else {}
        delayed = asyncio.create_task(client.request("POST" if operation == "logout" else "GET", path, headers=headers))
        try:
            await asyncio.wait_for(ready.wait(), 3)
            assert (await client.post("/test-sign-in")).status_code == 200
        finally:
            release.set()
        response = await delayed
        assert response.status_code == 200
        assert "set-cookie" not in response.headers
        assert client.cookies.get(SESSION_COOKIE_NAMES[kind]) == sessions[1].token
        assert sessions[1].record.revoked_at is None


@pytest.mark.anyio
async def test_email_only_recovery_cannot_save_into_another_cookie_application():
    from app.services.email.sender import CapturedEmailSender, get_email_sender
    from tests.applicant.support import sample_answers

    kind = PasswordlessIdentityKind.APPLICANT
    app, db, actors, sessions = identities(kind)
    sender = CapturedEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    before = dict(actors[1].raw_row)
    revision = actors[1].working_revision
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        client.cookies.set(SESSION_COOKIE_NAMES[kind], sessions[1].token, domain="testserver.local", path="/")
        response = await client.post("/applicant/access-links/request", json={
            "answers": sample_answers(actors[0].primary_email), "openingIds": [current_opening_id(db)],
            "baseRevision": None})
    assert response.status_code == 202
    assert response.json()["currentAnswersSaved"] is False
    assert actors[1].working_revision == revision
    assert actors[1].raw_row == before
    assert sender.messages[-1].to == (actors[0].primary_email,)
