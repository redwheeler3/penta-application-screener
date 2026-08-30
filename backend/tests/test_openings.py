from datetime import UTC, date, datetime, timedelta

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import require_current_user
from app.core.time import pacific_today
from app.db.models import (
    ApplicantDraft,
    ApplicantDraftIntent,
    Application,
    ApplicationParticipation,
    Base,
    BrowserSession,
    MagicLinkPurpose,
    MagicLinkToken,
    Opening,
    OpeningOutcome,
    PasswordlessIdentityKind,
    User,
    UserRole,
)
from app.db.session import get_db
from app.services.application_scope import committee_applications
from app.services.email_sender import CapturedEmailSender, get_email_sender
from app.services.openings import opening_phase
from app.services.passwordless_auth import create_browser_session, issue_magic_link
from tests.app_support import shared_test_app


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
    app = shared_test_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_current_user] = lambda: user
    return app, db


def _opening_payload(**overrides) -> dict:
    payload = {
        "unitSizeBedrooms": 2,
        "housingChargeCents": 125_000,
        "applicationOpenDate": "2026-09-01",
        "applicationCloseDate": "2026-09-15",
        "moveInDate": "2026-10-01",
        "expectedAudienceCount": 0,
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
async def test_admin_creation_opens_an_opening_immediately() -> None:
    app, db = _app_and_db(UserRole.ADMIN)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        created = await client.post("/openings", json=_opening_payload())
        opening = created.json()["openings"][0]
        opening_id = opening["id"]

        assert created.status_code == 200
        assert opening["phase"] == "open"
        assert opening["applicationOpenDate"] == pacific_today().isoformat()
        assert opening["applicationCloseDate"] == "2026-09-15"
        assert opening["publishedAt"] is not None
        assert opening["submissionCount"] == 0

        edited = await client.put(
            f"/openings/{opening_id}",
            json=_opening_payload(housingChargeCents=130_000),
        )

    assert edited.json()["openings"][0]["housingChargeCents"] == 130_000
    assert db.get(Opening, opening_id).housing_charge_cents == 130_000


@pytest.mark.anyio
async def test_opening_dates_must_be_chronological() -> None:
    app, _ = _app_and_db(UserRole.ADMIN)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        close_in_past = await client.post(
            "/openings",
            json=_opening_payload(applicationCloseDate="2026-08-26"),
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

    assert close_in_past.status_code == 422
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


@pytest.mark.anyio
async def test_changing_move_in_date_updates_private_draft_retention() -> None:
    app, db = _app_and_db(UserRole.ADMIN)
    opening = Opening(
        unit_size_bedrooms=2,
        housing_charge_cents=125_000,
        application_open_date=date(2026, 9, 1),
        application_close_date=date(2026, 9, 15),
        move_in_date=date(2026, 10, 1),
        published_at=datetime.now(UTC),
    )
    application = Application(
        primary_email="claimed-draft@example.com",
        raw_row={},
        raw_row_hash="claimed-draft",
        normalized={},
        working_opening_ids=[],
        retention_due_on=date(2027, 10, 1),
    )
    db.add_all([opening, application])
    db.flush()
    application.working_opening_ids = [opening.id]
    pending = ApplicantDraft(
        email="pending-draft@example.com",
        intent=ApplicantDraftIntent.SAVE,
        draft_token_hash="pending-draft-token-hash",
        working_opening_ids=[opening.id],
        created_at=datetime.now(UTC),
        saved_at=datetime.now(UTC),
        retention_due_on=date(2027, 10, 1),
    )
    db.add(pending)
    db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            f"/openings/{opening.id}",
            json=_opening_payload(moveInDate="2026-11-01"),
        )

    assert response.status_code == 200
    assert application.retention_due_on == date(2027, 11, 1)
    assert pending.retention_due_on == date(2027, 11, 1)


def _opening_with_candidates(db, *, archived: bool = False) -> tuple[Opening, list[Application]]:
    today = pacific_today()
    opening = Opening(
        unit_size_bedrooms=2,
        housing_charge_cents=125_000,
        application_open_date=today - timedelta(days=30),
        application_close_date=today - timedelta(days=10),
        move_in_date=today if archived else today + timedelta(days=10),
        published_at=datetime.now(UTC),
    )
    applications = [
        Application(
            primary_email=f"candidate-{index}@example.com",
            applicant_name=f"Candidate {index}",
            raw_row={},
            raw_row_hash=f"candidate-{index}",
            normalized={},
            submitted_at=datetime.now(UTC),
        )
        for index in range(1, 4)
    ]
    db.add_all([opening, *applications])
    db.flush()
    db.add_all(
        ApplicationParticipation(
            application_id=application.id,
            opening_id=opening.id,
            applied_at=datetime.now(UTC),
        )
        for application in applications
    )
    db.commit()
    return opening, applications


@pytest.mark.anyio
async def test_closed_selection_is_reversible_and_changes_committee_scope() -> None:
    app, db = _app_and_db(UserRole.ADMIN)
    opening, applications = _opening_with_candidates(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        selected = await client.post(
            f"/openings/{opening.id}/selection",
            json={"applicationId": applications[0].id},
        )
        picker_after_selection = await client.get(f"/openings/{opening.id}/selection")
        undone = await client.delete(f"/openings/{opening.id}/selection")

    participations = db.query(ApplicationParticipation).order_by(
        ApplicationParticipation.application_id
    ).all()
    assert selected.status_code == 200
    assert selected.json()["decisionPermanent"] is False
    assert [candidate["applicationId"] for candidate in picker_after_selection.json()["candidates"]] == [
        applications[1].id,
        applications[2].id,
    ]
    assert undone.json()["selectedApplicationId"] is None
    assert all(participation.outcome is None for participation in participations)
    assert [item.id for item in committee_applications(db)] == [
        application.id for application in applications
    ]


@pytest.mark.anyio
async def test_selection_revokes_credentials_and_undo_does_not_restore_them() -> None:
    app, db = _app_and_db(UserRole.ADMIN)
    opening, applications = _opening_with_candidates(db)
    selected_application = applications[0]
    issued_session = create_browser_session(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=selected_application.id,
    )
    issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        email=selected_application.primary_email,
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
        application_id=selected_application.id,
    )
    issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        email="new-address@example.com",
        purpose=MagicLinkPurpose.EMAIL_CHANGE,
        application_id=selected_application.id,
    )
    draft = ApplicantDraft(
        email=selected_application.primary_email,
        intent=ApplicantDraftIntent.SAVE,
        application_id=selected_application.id,
        draft_token_hash="selected-collision-draft",
        working_opening_ids=[opening.id],
        created_at=datetime.now(UTC),
        saved_at=datetime.now(UTC),
        retention_due_on=selected_application.retention_due_on or opening.move_in_date,
    )
    db.add(draft)
    db.flush()
    issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        email=selected_application.primary_email,
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
        applicant_draft_id=draft.id,
    )
    db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        selected = await client.post(
            f"/openings/{opening.id}/selection",
            json={"applicationId": selected_application.id},
        )
        undone = await client.delete(f"/openings/{opening.id}/selection")

    db.expire_all()
    sessions = db.query(BrowserSession).all()
    links = db.query(MagicLinkToken).all()
    assert selected.status_code == 200
    assert undone.status_code == 200
    assert len(sessions) == 1
    assert sessions[0].id == issued_session.record.id
    assert sessions[0].revoked_at is not None
    assert len(links) == 3
    assert all(link.revoked_at is not None for link in links)


@pytest.mark.anyio
async def test_archived_selection_is_permanent() -> None:
    app, db = _app_and_db(UserRole.ADMIN)
    opening, applications = _opening_with_candidates(db, archived=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        selected = await client.post(
            f"/openings/{opening.id}/selection",
            json={"applicationId": applications[0].id},
        )
        undone = await client.delete(f"/openings/{opening.id}/selection")
        replaced = await client.post(
            f"/openings/{opening.id}/selection",
            json={"applicationId": applications[1].id},
        )

    outcomes = db.query(ApplicationParticipation).order_by(
        ApplicationParticipation.application_id
    ).all()
    assert selected.json()["decisionPermanent"] is True
    assert undone.status_code == 422
    assert replaced.status_code == 422
    assert [participation.outcome for participation in outcomes] == [
        OpeningOutcome.SELECTED,
        OpeningOutcome.UNSUCCESSFUL,
        OpeningOutcome.UNSUCCESSFUL,
    ]
    assert committee_applications(db) == []


@pytest.mark.anyio
async def test_closed_no_household_decision_is_explicit_and_reversible() -> None:
    app, db = _app_and_db(UserRole.ADMIN)
    opening, applications = _opening_with_candidates(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        decided = await client.post(f"/openings/{opening.id}/selection/no-household")
        undone = await client.delete(f"/openings/{opening.id}/selection")

    assert decided.status_code == 200
    assert decided.json()["selectedApplicationId"] is None
    assert decided.json()["noHouseholdSelected"] is True
    assert decided.json()["decisionPermanent"] is False
    assert undone.json()["noHouseholdSelected"] is False
    assert opening.no_household_selected_at is None
    assert all(
        participation.outcome is None
        for participation in db.query(ApplicationParticipation).all()
    )
    assert [item.id for item in committee_applications(db)] == [
        application.id for application in applications
    ]


@pytest.mark.anyio
async def test_archived_no_household_decision_is_permanent_and_sends_notices() -> None:
    app, db = _app_and_db(UserRole.ADMIN)
    sender = CapturedEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    opening, applications = _opening_with_candidates(db, archived=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        decided = await client.post(f"/openings/{opening.id}/selection/no-household")
        undone = await client.delete(f"/openings/{opening.id}/selection")

    assert decided.status_code == 200
    assert decided.json()["noHouseholdSelected"] is True
    assert decided.json()["decisionPermanent"] is True
    assert undone.status_code == 422
    assert len(sender.messages) == len(applications)
    assert all(
        participation.outcome == OpeningOutcome.UNSUCCESSFUL
        and participation.unsuccessful_notified_at is not None
        for participation in db.query(ApplicationParticipation).all()
    )


@pytest.mark.anyio
async def test_selected_household_is_excluded_from_other_opening_picker() -> None:
    app, db = _app_and_db(UserRole.ADMIN)
    first, applications = _opening_with_candidates(db)
    today = pacific_today()
    second = Opening(
        unit_size_bedrooms=3,
        housing_charge_cents=150_000,
        application_open_date=today - timedelta(days=30),
        application_close_date=today - timedelta(days=10),
        move_in_date=today + timedelta(days=10),
        published_at=datetime.now(UTC),
    )
    db.add(second)
    db.flush()
    db.add_all(
        ApplicationParticipation(
            application_id=application.id,
            opening_id=second.id,
            applied_at=datetime.now(UTC),
        )
        for application in applications
    )
    db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post(
            f"/openings/{first.id}/selection",
            json={"applicationId": applications[0].id},
        )
        second_picker = await client.get(f"/openings/{second.id}/selection")

    assert [candidate["applicationId"] for candidate in second_picker.json()["candidates"]] == [
        applications[1].id,
        applications[2].id,
    ]


@pytest.mark.anyio
async def test_admin_can_review_selected_application_only_through_retained_route() -> None:
    app, db = _app_and_db(UserRole.ADMIN)
    opening, applications = _opening_with_candidates(db, archived=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post(
            f"/openings/{opening.id}/selection",
            json={"applicationId": applications[0].id},
        )
        live_detail = await client.get(f"/applications/{applications[0].id}")
        retained_detail = await client.get(
            f"/applications/{applications[0].id}/retained"
        )

    assert live_detail.status_code == 404
    assert retained_detail.status_code == 200
    assert retained_detail.json()["application"]["id"] == applications[0].id


@pytest.mark.anyio
async def test_member_cannot_review_retained_selected_application() -> None:
    app, db = _app_and_db(UserRole.MEMBER)
    _, applications = _opening_with_candidates(db, archived=True)
    participation = db.query(ApplicationParticipation).filter_by(
        application_id=applications[0].id
    ).one()
    participation.outcome = OpeningOutcome.SELECTED
    db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(f"/applications/{applications[0].id}/retained")

    assert response.status_code == 403
