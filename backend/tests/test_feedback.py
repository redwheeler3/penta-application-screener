import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import require_current_user
from app.db.models import Base, Feedback, User, UserRole
from app.db.session import get_db
from app.main import create_app


def setup_app(role: UserRole) -> tuple:
    """App wired to a shared in-memory DB, authed as a user of the given role.
    Returns (app, session, user)."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    user = User(email="me@x.com", display_name="Me", role=role, is_active=True)
    db.add(user)
    db.commit()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_current_user] = lambda: user
    return app, db, user


@pytest.mark.anyio
async def test_member_can_submit_feedback_with_context() -> None:
    """Any member can POST; identity + app version are stamped server-side, and the
    context the client reports (route/tab/analysis) is preserved."""
    app, db, user = setup_app(UserRole.MEMBER)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/feedback",
            json={
                "body": "The Rank button confused me.",
                "route": "/",
                "activeTab": "ranking",
                "analysisId": 42,
            },
        )
        assert resp.status_code == 201
        payload = resp.json()
        assert payload["body"] == "The Rank button confused me."
        assert payload["activeTab"] == "ranking"
        assert payload["analysisId"] == 42
        # Server-stamped, not taken from the body.
        assert payload["userEmail"] == "me@x.com"
        assert payload["userName"] == "Me"
        assert payload["appVersion"]  # non-empty (from pyproject)
        assert payload["resolvedAt"] is None

    # Persisted with the real user id.
    stored = db.query(Feedback).one()
    assert stored.user_id == user.id


@pytest.mark.anyio
async def test_body_is_required() -> None:
    """An empty body is rejected (422) — there's nothing to act on."""
    app, _, _ = setup_app(UserRole.MEMBER)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.post("/feedback", json={"body": ""})).status_code == 422


@pytest.mark.anyio
async def test_context_is_optional() -> None:
    """Feedback from a page with no tab/ranking still submits (context all nullable)."""
    app, _, _ = setup_app(UserRole.MEMBER)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post("/feedback", json={"body": "General note."})
        assert resp.status_code == 201
        payload = resp.json()
        assert payload["route"] is None
        assert payload["activeTab"] is None
        assert payload["analysisId"] is None


@pytest.mark.anyio
async def test_member_cannot_read_or_resolve() -> None:
    """Reads + resolve are admin-only (the free text is potentially sensitive)."""
    app, _, _ = setup_app(UserRole.MEMBER)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/feedback")).status_code == 403
        assert (await client.post("/feedback/1/resolve")).status_code == 403


@pytest.mark.anyio
async def test_admin_lists_newest_first_and_resolve_hides_by_default() -> None:
    """Admin sees open items newest-first; resolving one drops it from the default list
    but keeps it (retained history), visible via includeResolved."""
    app, _, _ = setup_app(UserRole.ADMIN)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = (await client.post("/feedback", json={"body": "first"})).json()
        second = (await client.post("/feedback", json={"body": "second"})).json()

        listing = (await client.get("/feedback")).json()["items"]
        assert [i["body"] for i in listing] == ["second", "first"]  # newest first

        # Resolve the first -> gone from the default (open) list, still there with the flag.
        resolved = await client.post(f"/feedback/{first['id']}/resolve")
        assert resolved.status_code == 200
        assert resolved.json()["resolvedAt"] is not None

        open_only = (await client.get("/feedback")).json()["items"]
        assert [i["id"] for i in open_only] == [second["id"]]

        with_resolved = (await client.get("/feedback?includeResolved=true")).json()["items"]
        assert {i["id"] for i in with_resolved} == {first["id"], second["id"]}


@pytest.mark.anyio
async def test_resolve_is_idempotent_and_reopen_restores() -> None:
    app, _, _ = setup_app(UserRole.ADMIN)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        item = (await client.post("/feedback", json={"body": "x"})).json()

        r1 = (await client.post(f"/feedback/{item['id']}/resolve")).json()
        r2 = (await client.post(f"/feedback/{item['id']}/resolve")).json()
        assert r1["resolvedAt"] == r2["resolvedAt"]  # idempotent: original stamp kept

        reopened = await client.post(f"/feedback/{item['id']}/reopen")
        assert reopened.status_code == 200
        assert reopened.json()["resolvedAt"] is None


@pytest.mark.anyio
async def test_resolve_missing_is_404() -> None:
    app, _, _ = setup_app(UserRole.ADMIN)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.post("/feedback/999/resolve")).status_code == 404
