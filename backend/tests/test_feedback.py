from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from alembic.config import Config
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from alembic import command
from app.api.dependencies import require_current_user
from app.core.time import pacific_today
from app.db.models import (
    Analysis,
    Application,
    ApplicationParticipation,
    Base,
    Feedback,
    Opening,
    User,
    UserRole,
)
from app.db.session import get_db
from app.services.feedback import reopen_feedback, resolve_feedback
from tests.app_support import shared_test_app


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
    app = shared_test_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_current_user] = lambda: user
    return app, db, user


def test_reopen_applies_even_when_the_session_loaded_an_older_open_item() -> None:
    _app, db, user = setup_app(UserRole.ADMIN)
    item = Feedback(user_id=user.id, body="Synthetic feedback", app_version="test")
    db.add(item)
    db.commit()
    item_id = item.id
    factory = sessionmaker(bind=db.get_bind(), autoflush=False)
    with factory() as stale:
        original = stale.get(Feedback, item_id)
        assert original.resolved_at is None
        resolve_feedback(db, item_id)
        reopened = reopen_feedback(stale, item_id)
        assert reopened.resolved_at is None
    db.refresh(item)
    assert item.resolved_at is None


def test_repeated_resolution_keeps_the_current_database_timestamp() -> None:
    _app, db, user = setup_app(UserRole.ADMIN)
    item = Feedback(user_id=user.id, body="Synthetic feedback", app_version="test")
    db.add(item)
    db.commit()
    item_id = item.id
    factory = sessionmaker(bind=db.get_bind(), autoflush=False)
    with factory() as stale:
        old = stale.get(Feedback, item_id)
        assert old.resolved_at is None
        item.resolved_at = datetime(2026, 1, 1)
        db.commit()
        assert resolve_feedback(stale, item_id).resolved_at == datetime(2026, 1, 1)


def reviewable_context(db):
    applicant = Application(primary_email="a@x.com", applicant_name="Synthetic Applicant",
        raw_row={}, raw_row_hash="h1", normalized={}, submitted_at=datetime.now(UTC))
    opening = Opening(unit_size_bedrooms=2, housing_charge_cents=100000,
        application_open_date=date(2026, 1, 1), application_close_date=date(2026, 2, 1),
        move_in_date=date(2026, 3, 1), published_at=datetime.now(UTC))
    db.add_all([applicant, opening])
    db.flush()
    db.add(ApplicationParticipation(application_id=applicant.id, opening_id=opening.id,
        applied_at=datetime.now(UTC)))
    analysis = Analysis(opening_id=opening.id)
    db.add(analysis)
    db.commit()
    return applicant, opening, analysis


@pytest.mark.anyio
async def test_member_can_submit_feedback_with_context() -> None:
    app, db, user = setup_app(UserRole.MEMBER)
    applicant, opening, analysis = reviewable_context(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        resp = await client.post("/feedback", json={"body": "Synthetic issue", "route": "/",
            "activeTab": "ranking", "analysisId": analysis.id, "applicantId": applicant.id,
            "openingId": opening.id})
    assert resp.status_code == 201
    stored = db.query(Feedback).one()
    assert resp.json() == {"id": stored.id}
    assert (stored.user_id, stored.body, stored.opening_id, stored.analysis_id, stored.applicant_id) == (
        user.id, "Synthetic issue", opening.id, analysis.id, applicant.id)
    assert stored.app_version


@pytest.mark.anyio
@pytest.mark.parametrize("role", [UserRole.MEMBER, UserRole.ADMIN])
@pytest.mark.parametrize("retained", [False, True])
async def test_private_draft_context_never_enriches_submission_or_admin_list(role, retained) -> None:
    app, db, user = setup_app(role)
    draft = Application(primary_email="private@example.com", applicant_name="Private Draft",
        raw_row={}, raw_row_hash="h", normalized={})
    db.add(draft)
    db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/feedback", json={"body": "Keep this report",
            "applicantId": draft.id, "openingId": 999, "analysisId": 999, "retainedReview": retained})
        assert response.status_code == 201
        stored = db.query(Feedback).one()
        assert response.json() == {"id": stored.id}
        assert stored.body == "Keep this report"
        assert (stored.applicant_id, stored.opening_id, stored.analysis_id) == (None, None, None)
        # Also protect older stored contexts at read time.
        stored.applicant_id = draft.id
        user.role = UserRole.ADMIN
        db.commit()
        item = (await client.get("/feedback")).json()["items"][0]
        assert item["applicantId"] is None
        assert item["applicantName"] is None


@pytest.mark.anyio
async def test_admin_projection_keeps_exact_opening_and_removes_expired_or_purged_links() -> None:
    app, db, _ = setup_app(UserRole.ADMIN)
    applicant, opening, analysis = reviewable_context(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await client.post("/feedback", json={"body": "x", "applicantId": applicant.id,
            "openingId": opening.id, "analysisId": analysis.id})
        item = (await client.get("/feedback")).json()["items"][0]
        assert (item["applicantId"], item["applicantName"], item["openingId"], item["retainedReview"]) == (
            applicant.id, "Synthetic Applicant", opening.id, False)
        applicant.retention_due_on = pacific_today()
        db.commit()
        item = (await client.get("/feedback")).json()["items"][0]
        assert item["applicantId"] is None
        assert item["applicantName"] is None
        db.delete(applicant)
        db.commit()
        item = (await client.get("/feedback")).json()["items"][0]
        assert item["applicantId"] is None
        assert item["body"] == "x"


@pytest.mark.anyio
async def test_contextless_links_use_only_retained_scope_and_members_cannot_forge_it() -> None:
    app, db, user = setup_app(UserRole.ADMIN)
    applicant, opening, _ = reviewable_context(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Ordinary undecided records are not retained-review targets.
        await client.post("/feedback", json={"body": "ordinary", "applicantId": applicant.id})
        assert db.query(Feedback).one().applicant_id is None
        applicant.retention_due_on = pacific_today() + timedelta(days=30)
        db.commit()
        await client.post("/feedback", json={"body": "retained", "applicantId": applicant.id})
        item = (await client.get("/feedback")).json()["items"][0]
        assert item["applicantId"] == applicant.id
        assert item["retainedReview"] is True
        assert item["openingId"] is None
        user.role = UserRole.MEMBER
        db.commit()
        await client.post("/feedback", json={"body": "forged", "applicantId": applicant.id,
            "openingId": opening.id, "retainedReview": True})
        assert db.query(Feedback).filter_by(body="forged").one().applicant_id is None


@pytest.mark.anyio
async def test_mismatched_and_withdrawn_context_is_discarded_without_losing_feedback() -> None:
    app, db, _ = setup_app(UserRole.ADMIN)
    applicant, _opening, analysis = reviewable_context(db)
    other = Opening(unit_size_bedrooms=1, housing_charge_cents=100000,
        move_in_date=date(2026, 3, 1), published_at=datetime.now(UTC))
    db.add(other)
    db.flush()
    # Same applicant can be in both scopes, while each analysis still has one owner.
    db.add(ApplicationParticipation(application_id=applicant.id, opening_id=other.id, applied_at=datetime.now(UTC)))
    db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await client.post("/feedback", json={"body": "wrong analysis", "applicantId": applicant.id,
            "openingId": other.id, "analysisId": analysis.id})
        stored = db.query(Feedback).one()
        assert stored.applicant_id == applicant.id
        assert stored.opening_id == other.id
        assert stored.analysis_id is None
        applicant.withdrawn_at = datetime.now(UTC)
        db.commit()
        item = (await client.get("/feedback")).json()["items"][0]
        assert item["applicantId"] is None
        assert item["applicantName"] is None


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
        assert set(resp.json()) == {"id"}


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


def test_feedback_context_migration_preserves_existing_feedback_in_memory():
    backend = Path(__file__).parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "e81c9a53f647")
        connection.exec_driver_sql("INSERT INTO users (id, email, display_name, role, is_active) VALUES (1, 'synthetic@example.test', 'Synthetic', 'member', 1)")
        connection.exec_driver_sql("INSERT INTO feedback (user_id, body, app_version, applicant_id) VALUES (1, 'Preserve report', 'test', 7)")
        command.upgrade(config, "f92d0b64a758")
        assert connection.exec_driver_sql("SELECT body, applicant_id, opening_id, retained_review FROM feedback").one() == (
            "Preserve report", 7, None, 0)
    engine.dispose()
