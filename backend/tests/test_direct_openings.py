from datetime import UTC, datetime, timedelta

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import require_current_user
from app.core.time import pacific_today
from app.db.models import (
    Application,
    ApplicationParticipation,
    Base,
    EmailDelivery,
    Opening,
    OpeningIntakeMode,
    OpeningOutcome,
    User,
    UserRole,
    VacancyConsentReceipt,
    VacancySubscription,
)
from app.db.session import get_db
from app.services.application_scope import committee_applications
from app.services.email_sender import CapturedEmailSender, get_email_sender
from app.services.retention import one_year_after, years_after
from tests.app_support import shared_test_app


def _application(db, email: str, *, name: str, retention_due_on=None) -> Application:
    application = Application(
        primary_email=email,
        applicant_name=name,
        raw_row={},
        raw_row_hash=email,
        normalized={},
        submitted_at=datetime.now(UTC) - timedelta(days=60),
        retention_due_on=retention_due_on,
    )
    db.add(application)
    db.flush()
    return application


def _opening(db, *, move_in_offset: int) -> Opening:
    today = pacific_today()
    opening = Opening(
        intake_mode=OpeningIntakeMode.APPLICATIONS,
        unit_size_bedrooms=2,
        housing_charge_cents=125_000,
        application_open_date=today - timedelta(days=90),
        application_close_date=today - timedelta(days=60),
        move_in_date=today + timedelta(days=move_in_offset),
        published_at=datetime.now(UTC) - timedelta(days=90),
    )
    db.add(opening)
    db.flush()
    return opening


def _participate(
    db,
    application: Application,
    opening: Opening,
    *,
    outcome: OpeningOutcome | None = None,
) -> None:
    db.add(
        ApplicationParticipation(
            application_id=application.id,
            opening_id=opening.id,
            applied_at=application.submitted_at,
            outcome=outcome,
            outcome_decided_at=datetime.now(UTC) if outcome is not None else None,
        )
    )
    db.flush()


def _app_and_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    admin = User(
        email="admin@example.com",
        display_name="Admin",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(admin)
    db.commit()
    sender = CapturedEmailSender()
    app = shared_test_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_current_user] = lambda: admin
    app.dependency_overrides[get_email_sender] = lambda: sender
    return app, db, sender


@pytest.mark.anyio
async def test_admin_can_search_retained_previous_applicants_without_listing_them() -> None:
    app, db, _sender = _app_and_db()
    prior = _opening(db, move_in_offset=-30)
    available = _application(
        db,
        "alex.river@example.com",
        name="Alex River",
        retention_due_on=pacific_today() + timedelta(days=200),
    )
    _participate(db, available, prior, outcome=OpeningOutcome.UNSUCCESSFUL)
    expired = _application(
        db,
        "alex.old@example.com",
        name="Alex Old",
        retention_due_on=pacific_today() - timedelta(days=1),
    )
    _participate(db, expired, prior, outcome=OpeningOutcome.UNSUCCESSFUL)
    withdrawn = _application(
        db,
        "alex.withdrawn@example.com",
        name="Alex Withdrawn",
        retention_due_on=pacific_today() + timedelta(days=200),
    )
    withdrawn.withdrawn_at = datetime.now(UTC)
    _participate(db, withdrawn, prior, outcome=OpeningOutcome.UNSUCCESSFUL)
    db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/openings/previous-applicants/search",
            json={"query": "alex river"},
        )
        retained = await client.get(f"/applications/{available.id}/retained")
        ordinary = await client.get(f"/applications/{available.id}")
        too_short = await client.post(
            "/openings/previous-applicants/search",
            json={"query": "a"},
        )
        blank = await client.post(
            "/openings/previous-applicants/search",
            json={"query": "   "},
        )

    assert response.status_code == 200
    assert response.json()["candidates"] == [
        {
            "applicationId": available.id,
            "applicantName": "Alex River",
            "primaryEmail": "alex.river@example.com",
        }
    ]
    assert too_short.status_code == 422
    assert blank.status_code == 422
    assert retained.status_code == 200
    assert ordinary.status_code == 404


@pytest.mark.anyio
async def test_direct_selection_is_atomic_and_sends_no_email() -> None:
    app, db, sender = _app_and_db()
    today = pacific_today()
    prior = _opening(db, move_in_offset=-30)
    current = _opening(db, move_in_offset=45)
    candidate = _application(
        db,
        "candidate@example.com",
        name="Candidate Household",
        retention_due_on=one_year_after(current.move_in_date),
    )
    other = _application(
        db,
        "other@example.com",
        name="Other Household",
        retention_due_on=one_year_after(current.move_in_date),
    )
    for application in (candidate, other):
        _participate(db, application, prior, outcome=OpeningOutcome.UNSUCCESSFUL)
        _participate(db, application, current)
    subscription = VacancySubscription(
        email="subscriber@example.com",
        wants_one_bedroom=False,
        wants_two_bedroom=True,
        wants_three_bedroom=False,
        consented_at=datetime.now(UTC),
        source="test",
    )
    db.add(subscription)
    db.commit()
    assert {application.id for application in committee_applications(db)} == {
        candidate.id,
        other.id,
    }

    move_in_date = today + timedelta(days=90)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/openings/direct-selection",
            json={
                "unitSizeBedrooms": 3,
                "housingChargeCents": 145_000,
                "moveInDate": move_in_date.isoformat(),
                "applicationId": candidate.id,
            },
        )
        applicant_openings = await client.get("/applicant/openings")

    assert response.status_code == 200
    direct = next(
        opening for opening in response.json()["openings"]
        if opening["intakeMode"] == "direct_selection"
    )
    assert direct["phase"] == "closed"
    assert direct["applicationOpenDate"] is None
    assert direct["applicationCloseDate"] is None
    assert direct["publishedAt"] is None
    assert direct["selectedApplicationId"] == candidate.id
    assert direct["id"] not in {
        opening["id"] for opening in applicant_openings.json()["openings"]
    }
    assert db.scalar(
        select(func.count())
        .select_from(ApplicationParticipation)
        .where(ApplicationParticipation.opening_id == direct["id"])
    ) == 1
    participation = db.scalar(
        select(ApplicationParticipation).where(
            ApplicationParticipation.opening_id == direct["id"]
        )
    )
    assert participation is not None
    assert participation.application_id == candidate.id
    assert participation.outcome == OpeningOutcome.SELECTED
    assert candidate.retention_due_on == years_after(move_in_date, 7)
    assert [application.id for application in committee_applications(db)] == [other.id]
    assert db.scalar(select(func.count()).select_from(VacancySubscription)) == 1
    assert db.scalar(select(func.count()).select_from(VacancyConsentReceipt)) == 0
    assert db.scalar(select(func.count()).select_from(EmailDelivery)) == 0
    assert sender.messages == []


@pytest.mark.anyio
async def test_removing_direct_selection_restores_prior_scope_and_retention() -> None:
    app, db, sender = _app_and_db()
    today = pacific_today()
    current = _opening(db, move_in_offset=45)
    candidate = _application(
        db,
        "candidate@example.com",
        name="Candidate Household",
        retention_due_on=one_year_after(current.move_in_date),
    )
    _participate(db, candidate, current)
    db.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        created = await client.post(
            "/openings/direct-selection",
            json={
                "unitSizeBedrooms": 2,
                "housingChargeCents": 135_000,
                "moveInDate": (today + timedelta(days=90)).isoformat(),
                "applicationId": candidate.id,
            },
        )
        direct_id = next(
            opening["id"] for opening in created.json()["openings"]
            if opening["intakeMode"] == "direct_selection"
        )
        removed = await client.delete(f"/openings/{direct_id}/direct-selection")

    assert removed.status_code == 200
    assert all(
        opening["intakeMode"] == "applications"
        for opening in removed.json()["openings"]
    )
    assert db.get(Opening, direct_id) is None
    assert candidate.retention_due_on == one_year_after(current.move_in_date)
    assert [application.id for application in committee_applications(db)] == [candidate.id]
    assert sender.messages == []


@pytest.mark.anyio
async def test_direct_selection_revalidates_the_previous_applicant() -> None:
    app, db, _sender = _app_and_db()
    today = pacific_today()
    prior = _opening(db, move_in_offset=-30)
    candidate = _application(
        db,
        "candidate@example.com",
        name="Candidate Household",
        retention_due_on=today - timedelta(days=1),
    )
    _participate(db, candidate, prior, outcome=OpeningOutcome.UNSUCCESSFUL)
    db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/openings/direct-selection",
            json={
                "unitSizeBedrooms": 2,
                "housingChargeCents": 135_000,
                "moveInDate": (today + timedelta(days=90)).isoformat(),
                "applicationId": candidate.id,
            },
        )

    assert response.status_code == 422
    assert db.scalar(
        select(func.count())
        .select_from(Opening)
        .where(Opening.intake_mode == OpeningIntakeMode.DIRECT_SELECTION)
    ) == 0


@pytest.mark.anyio
async def test_direct_selection_is_permanent_on_the_move_in_date() -> None:
    app, db, _sender = _app_and_db()
    today = pacific_today()
    prior = _opening(db, move_in_offset=-30)
    candidate = _application(
        db,
        "candidate@example.com",
        name="Candidate Household",
        retention_due_on=today + timedelta(days=200),
    )
    _participate(db, candidate, prior, outcome=OpeningOutcome.UNSUCCESSFUL)
    db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        created = await client.post(
            "/openings/direct-selection",
            json={
                "unitSizeBedrooms": 2,
                "housingChargeCents": 135_000,
                "moveInDate": (today + timedelta(days=90)).isoformat(),
                "applicationId": candidate.id,
            },
        )
        direct_id = next(
            opening["id"] for opening in created.json()["openings"]
            if opening["intakeMode"] == "direct_selection"
        )
        direct = db.get(Opening, direct_id)
        assert direct is not None
        direct.move_in_date = today
        db.commit()
        removed = await client.delete(f"/openings/{direct_id}/direct-selection")

    assert removed.status_code == 422
    assert db.get(Opening, direct_id) is not None
