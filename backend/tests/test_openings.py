from datetime import UTC, date, datetime

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import require_current_user, require_recent_admin
from app.db.models import (
    Application,
    ApplicationParticipation,
    Base,
    Opening,
    User,
    UserRole,
)
from app.db.session import get_db
from app.main import create_app
from app.services.openings import opening_phase


def _app_and_db(role: UserRole) -> tuple:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    user = User(email="admin@example.com", display_name="Admin", role=role, is_active=True)
    db.add(user)
    db.commit()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_current_user] = lambda: user
    if role == UserRole.ADMIN:
        app.dependency_overrides[require_recent_admin] = lambda: user
    return app, db


def _opening_payload(**overrides) -> dict:
    payload = {
        "unitSizeBedrooms": 2,
        "housingChargeCents": 125_000,
        "applicationOpenDate": "2026-09-01",
        "applicationCloseDate": "2026-09-15",
        "moveInDate": "2026-10-01",
    }
    payload.update(overrides)
    return payload


@pytest.mark.anyio
async def test_opening_routes_are_admin_only() -> None:
    app, _ = _app_and_db(UserRole.MEMBER)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/openings")).status_code == 403
        assert (await client.post("/openings", json=_opening_payload())).status_code == 403


@pytest.mark.anyio
async def test_admin_creates_edits_and_publishes_an_opening() -> None:
    app, db = _app_and_db(UserRole.ADMIN)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        created = await client.post("/openings", json=_opening_payload())
        opening = created.json()["openings"][0]
        opening_id = opening["id"]

        assert created.status_code == 200
        assert opening["phase"] == "draft"
        assert opening["applicationOpenDate"] == "2026-09-01"
        assert opening["applicationCloseDate"] == "2026-09-15"
        assert opening["publishedAt"] is None
        assert opening["submissionCount"] == 0

        edited = await client.put(
            f"/openings/{opening_id}",
            json=_opening_payload(housingChargeCents=130_000),
        )
        published = await client.post(f"/openings/{opening_id}/publish")

    assert edited.json()["openings"][0]["housingChargeCents"] == 130_000
    assert published.json()["openings"][0]["publishedAt"] is not None
    assert db.get(Opening, opening_id).housing_charge_cents == 130_000


@pytest.mark.anyio
async def test_opening_dates_must_be_chronological() -> None:
    app, _ = _app_and_db(UserRole.ADMIN)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        close_before_open = await client.post(
            "/openings",
            json=_opening_payload(applicationCloseDate="2026-08-31"),
        )
        move_in_before_close = await client.post(
            "/openings",
            json=_opening_payload(moveInDate="2026-09-14"),
        )
        move_in_on_close = await client.post(
            "/openings",
            json=_opening_payload(moveInDate="2026-09-15"),
        )
        all_dates_equal = await client.post(
            "/openings",
            json=_opening_payload(
                applicationOpenDate="2026-09-15",
                applicationCloseDate="2026-09-15",
                moveInDate="2026-09-15",
            ),
        )

    assert close_before_open.status_code == 422
    assert move_in_before_close.status_code == 422
    assert move_in_on_close.status_code == 200
    assert all_dates_equal.status_code == 200


def test_phase_is_derived_from_pacific_calendar_dates() -> None:
    opening = Opening(
        unit_size_bedrooms=2,
        housing_charge_cents=125_000,
        application_open_date=date(2026, 9, 1),
        application_close_date=date(2026, 9, 15),
        move_in_date=date(2026, 10, 1),
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    assert opening_phase(opening, today=date(2026, 8, 31)).value == "upcoming"
    assert opening_phase(opening, today=date(2026, 9, 1)).value == "open"
    assert opening_phase(opening, today=date(2026, 9, 15)).value == "open"
    assert opening_phase(opening, today=date(2026, 9, 16)).value == "closed"
    assert opening_phase(opening, today=date(2026, 10, 1)).value == "archived"


def test_move_in_date_archives_when_it_equals_the_close_date() -> None:
    opening = Opening(
        unit_size_bedrooms=2,
        housing_charge_cents=125_000,
        application_open_date=date(2026, 9, 1),
        application_close_date=date(2026, 9, 15),
        move_in_date=date(2026, 9, 15),
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    assert opening_phase(opening, today=date(2026, 9, 14)).value == "open"
    assert opening_phase(opening, today=date(2026, 9, 15)).value == "archived"


@pytest.mark.anyio
async def test_admin_can_edit_an_archived_opening() -> None:
    app, db = _app_and_db(UserRole.ADMIN)
    opening = Opening(
        unit_size_bedrooms=2,
        housing_charge_cents=125_000,
        application_open_date=date(2020, 1, 1),
        application_close_date=date(2020, 1, 15),
        move_in_date=date(2020, 2, 1),
        published_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    db.add(opening)
    db.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            f"/openings/{opening.id}",
            json=_opening_payload(
                housingChargeCents=130_000,
                applicationOpenDate="2020-01-01",
                applicationCloseDate="2020-01-15",
                moveInDate="2020-02-01",
            ),
        )

    assert response.status_code == 200
    assert response.json()["openings"][0]["phase"] == "archived"
    assert response.json()["openings"][0]["housingChargeCents"] == 130_000


@pytest.mark.anyio
async def test_changing_move_in_date_updates_participant_retention() -> None:
    app, db = _app_and_db(UserRole.ADMIN)
    application = Application(
        primary_email="applicant@example.com",
        raw_row={},
        raw_row_hash="synthetic",
        normalized={},
        submitted_at=datetime.now(UTC),
        retention_due_on=date(2027, 10, 1),
    )
    opening = Opening(
        unit_size_bedrooms=2,
        housing_charge_cents=125_000,
        application_open_date=date(2026, 9, 1),
        application_close_date=date(2026, 9, 15),
        move_in_date=date(2026, 10, 1),
        published_at=datetime.now(UTC),
    )
    db.add_all([application, opening])
    db.flush()
    db.add(
        ApplicationParticipation(
            application_id=application.id,
            opening_id=opening.id,
            applied_at=datetime.now(UTC),
        )
    )
    db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            f"/openings/{opening.id}",
            json=_opening_payload(moveInDate="2026-11-01"),
        )

    assert response.status_code == 200
    assert application.retention_due_on == date(2027, 11, 1)
