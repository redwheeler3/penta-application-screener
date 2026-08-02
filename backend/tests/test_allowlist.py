from datetime import UTC, datetime, timedelta

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import require_current_user
from app.db.models import (
    AccessAllowlistEntry,
    Base,
    DeniedSignInAttempt,
    User,
    UserRole,
)
from app.db.session import get_db
from app.main import create_app
from app.services import allowlist
from app.services.denied_sign_ins import list_denied_sign_ins, record_denied_sign_in
from app.services.users import record_user_activity, upsert_google_user


def setup_app(role: UserRole | None) -> tuple:
    """App wired to a shared in-memory DB, optionally authed as a user of the given
    role. Returns (app, session)."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()

    user = None
    if role is not None:
        user = User(email="me@x.com", display_name="Me", role=role, is_active=True)
        db.add(user)
        db.commit()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    if user is not None:
        app.dependency_overrides[require_current_user] = lambda: user
    return app, db


# --- The gate: allowlist decides admission + role -----------------------------


def test_upsert_google_user_takes_role_from_caller() -> None:
    _, db = setup_app(role=None)
    user = upsert_google_user(
        db,
        google_subject="sub-1",
        email="New@X.com",
        display_name="New",
        avatar_url=None,
        role=UserRole.ADMIN,
    )
    assert user.email == "new@x.com"  # normalized
    assert user.role == UserRole.ADMIN


def test_upsert_google_user_resyncs_role_on_return_login() -> None:
    # An admin flipping someone's allowlist role takes effect on their next sign-in.
    _, db = setup_app(role=None)
    upsert_google_user(
        db, google_subject="s", email="u@x.com", display_name="U", avatar_url=None,
        role=UserRole.MEMBER,
    )
    again = upsert_google_user(
        db, google_subject="s", email="u@x.com", display_name="U", avatar_url=None,
        role=UserRole.ADMIN,
    )
    assert again.role == UserRole.ADMIN
    assert db.scalar(select(User).where(User.email == "u@x.com")).role == UserRole.ADMIN


def test_user_activity_keeps_only_first_and_latest_timestamps() -> None:
    _, db = setup_app(role=None)
    user = upsert_google_user(
        db, google_subject="s", email="u@x.com", display_name="U", avatar_url=None,
        role=UserRole.MEMBER,
    )

    first_activity = datetime(2026, 8, 2, 12, tzinfo=UTC)
    assert record_user_activity(db, user=user, now=first_activity)
    assert not record_user_activity(db, user=user, now=first_activity + timedelta(minutes=4))
    assert record_user_activity(db, user=user, now=first_activity + timedelta(minutes=5))
    db.refresh(user)

    assert user.first_active_at == first_activity.replace(tzinfo=None)
    assert user.last_active_at == (first_activity + timedelta(minutes=5)).replace(tzinfo=None)


def test_seed_initial_admins_is_idempotent_and_additive(monkeypatch) -> None:
    _, db = setup_app(role=None)
    monkeypatch.setattr(allowlist, "_read_bootstrap_emails", lambda: ["boss@x.com"])
    allowlist.seed_initial_admins(db)
    allowlist.seed_initial_admins(db)  # second run must not duplicate
    rows = db.scalars(
        select(AccessAllowlistEntry).where(AccessAllowlistEntry.email == "boss@x.com")
    ).all()
    assert len(rows) == 1
    assert rows[0].role == UserRole.ADMIN


# --- Admin-only CRUD + lock-out guards ----------------------------------------


@pytest.mark.anyio
async def test_allowlist_routes_require_admin() -> None:
    app, _ = setup_app(role=UserRole.MEMBER)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/allowlist")).status_code == 403
        denied = await client.put("/allowlist", json={"email": "x@x.com", "role": "member"})
        assert denied.status_code == 403


@pytest.mark.anyio
async def test_admin_can_add_and_remove_entries() -> None:
    app, db = setup_app(role=UserRole.ADMIN)
    # A second admin so lock-out guards don't block the member operations under test.
    allowlist.upsert_entry(db, email="me@x.com", role=UserRole.ADMIN)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        added = await client.put("/allowlist", json={"email": "Bob@x.com", "role": "member"})
        assert added.status_code == 200
        emails = {e["email"] for e in added.json()["entries"]}
        assert "bob@x.com" in emails

        promoted = await client.put("/allowlist", json={"email": "bob@x.com", "role": "admin"})
        assert promoted.status_code == 200
        bob = next(entry for entry in promoted.json()["entries"] if entry["email"] == "bob@x.com")
        assert bob["role"] == "admin"

        removed = await client.delete("/allowlist/bob@x.com")
        assert removed.status_code == 200
        assert "bob@x.com" not in {e["email"] for e in removed.json()["entries"]}


@pytest.mark.anyio
async def test_allowlist_includes_a_members_activity_summary() -> None:
    app, db = setup_app(role=UserRole.ADMIN)
    admin = db.scalar(select(User).where(User.email == "me@x.com"))
    assert admin is not None
    allowlist.upsert_entry(db, email="me@x.com", role=UserRole.ADMIN)
    record_user_activity(db, user=admin)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/allowlist")

    assert response.status_code == 200
    entry = response.json()["entries"][0]
    assert entry["displayName"] == "Me"
    assert entry["firstActiveAt"] is not None
    assert entry["lastActiveAt"] is not None


@pytest.mark.anyio
async def test_admin_can_read_aggregated_denied_sign_in_attempts() -> None:
    app, db = setup_app(role=UserRole.ADMIN)
    record_denied_sign_in(
        db, google_subject="denied-sub", email="visitor@example.com", display_name="Visitor"
    )
    record_denied_sign_in(
        db, google_subject="denied-sub", email="visitor@example.com", display_name="Visitor"
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/allowlist/denied-attempts")

    assert response.status_code == 200
    attempt = response.json()["attempts"][0]
    assert attempt["displayName"] == "Visitor"
    assert attempt["email"] == "visitor@example.com"
    assert attempt["count"] == 2
    assert attempt["firstDeniedAt"] is not None
    assert attempt["lastDeniedAt"] is not None


def test_denied_sign_in_list_discards_attempts_older_than_one_year() -> None:
    _, db = setup_app(role=None)
    db.add(
        DeniedSignInAttempt(
            google_subject="expired-sub",
            email="expired@example.com",
            display_name="Expired",
            created_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
    )
    db.commit()

    assert list_denied_sign_ins(db) == []


@pytest.mark.anyio
async def test_cannot_remove_or_demote_the_last_admin() -> None:
    app, db = setup_app(role=UserRole.ADMIN)
    allowlist.upsert_entry(db, email="me@x.com", role=UserRole.ADMIN)  # the only admin
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        demote = await client.put("/allowlist", json={"email": "me@x.com", "role": "member"})
        assert demote.status_code == 422
        remove = await client.delete("/allowlist/me@x.com")
        assert remove.status_code == 422
        # Still an admin after both blocked attempts.
        assert allowlist.get_entry(db, "me@x.com").role == UserRole.ADMIN
