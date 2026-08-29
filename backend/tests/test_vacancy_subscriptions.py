from datetime import UTC, date, datetime

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import require_current_user
from app.api.vacancy_subscriptions import signup_limiter
from app.db.models import (
    Base,
    User,
    UserRole,
    VacancyConsentReceipt,
    VacancySubscription,
    VacancySubscriptionAudit,
)
from app.db.session import get_db
from app.legal import VACANCY_CONSENT_VERSION
from app.main import create_app
from app.services.vacancy_subscriptions import (
    consume_subscription,
    purge_expired_consent_receipts,
    save_subscription,
)


def _app_and_db(role: UserRole = UserRole.ADMIN) -> tuple:
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
    signup_limiter.clear()
    return app, db, user


@pytest.mark.anyio
async def test_public_signup_replaces_preferences_without_enumerating() -> None:
    app, db, _ = _app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.post(
            "/vacancy-subscriptions",
            json={
                "email": " Person@Example.com ",
                "unitSizes": [1, 3],
                "consentVersion": VACANCY_CONSENT_VERSION,
            },
        )
        second = await client.post(
            "/vacancy-subscriptions",
            json={
                "email": "person@example.com",
                "unitSizes": [2],
                "consentVersion": VACANCY_CONSENT_VERSION,
            },
        )

    rows = list(db.scalars(select(VacancySubscription)))
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json() == {"saved": True}
    assert len(rows) == 1
    assert rows[0].email == "person@example.com"
    assert rows[0].wants_one_bedroom is False
    assert rows[0].wants_two_bedroom is True
    assert rows[0].wants_three_bedroom is False
    assert rows[0].consent_version == VACANCY_CONSENT_VERSION


def test_fulfilled_consent_receipt_is_hashed_and_expires_after_one_year() -> None:
    _, db, _ = _app_and_db()
    subscription = save_subscription(
        db,
        email="person@example.com",
        unit_sizes={1, 3},
        source="public website",
        consent_version=VACANCY_CONSENT_VERSION,
        consented_at=datetime(2026, 8, 27, 18, tzinfo=UTC),
    )

    consume_subscription(
        db,
        subscription.id,
        email_delivery_id=42,
        fulfilled_at=datetime(2026, 9, 1, 18, tzinfo=UTC),
    )
    db.commit()

    receipt = db.scalar(select(VacancyConsentReceipt))
    assert receipt is not None
    assert receipt.email_hash != "person@example.com"
    assert receipt.unit_sizes == [1, 3]
    assert receipt.consent_version == VACANCY_CONSENT_VERSION
    assert purge_expired_consent_receipts(db, today=date(2027, 8, 31)) == 0
    assert purge_expired_consent_receipts(db, today=date(2027, 9, 1)) == 1
    assert db.scalar(select(VacancyConsentReceipt)) is None


@pytest.mark.anyio
async def test_public_signup_validates_sizes_and_is_rate_limited() -> None:
    app, _, _ = _app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        invalid = await client.post(
            "/vacancy-subscriptions",
            json={
                "email": "person@example.com",
                "unitSizes": [4],
                "consentVersion": VACANCY_CONSENT_VERSION,
            },
        )
        responses = [
            await client.post(
                "/vacancy-subscriptions",
                json={
                    "email": f"person-{index}@example.com",
                    "unitSizes": [1],
                    "consentVersion": VACANCY_CONSENT_VERSION,
                },
            )
            for index in range(11)
        ]

    assert invalid.status_code == 422
    assert responses[-1].status_code == 429


@pytest.mark.anyio
async def test_public_signup_rejects_an_outdated_consent_notice() -> None:
    app, _, _ = _app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/vacancy-subscriptions",
            json={
                "email": "person@example.com",
                "unitSizes": [1],
                "consentVersion": "outdated",
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Refresh the page before submitting this vacancy request."
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "origin",
    ["https://www.pentacoop.com", "http://localhost:8080"],
)
async def test_public_signup_allows_the_website_origins(origin: str) -> None:
    app, _, _ = _app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.options(
            "/vacancy-subscriptions",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.anyio
async def test_admin_report_counts_overlapping_preferences_and_months() -> None:
    app, db, _ = _app_and_db()
    save_subscription(
        db,
        email="one@example.com",
        unit_sizes={1, 2},
        source="import",
        consented_at=datetime(2026, 7, 2, tzinfo=UTC),
    )
    save_subscription(
        db,
        email="two@example.com",
        unit_sizes={2, 3},
        source="import",
        consented_at=datetime(2026, 8, 2, tzinfo=UTC),
    )
    save_subscription(
        db,
        email="late-august@example.com",
        unit_sizes={1},
        source="public website",
        consented_at=datetime(2026, 9, 1, 6, tzinfo=UTC),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/vacancy-subscriptions/report")

    assert response.status_code == 200
    assert response.json() == {
        "total": 3,
        "oneBedroom": 2,
        "twoBedroom": 2,
        "threeBedroom": 1,
        "months": [
            {"month": "2026-07", "count": 1},
            {"month": "2026-08", "count": 2},
        ],
    }


@pytest.mark.anyio
async def test_admin_can_lookup_replace_and_delete_exact_email_with_audit() -> None:
    app, db, admin = _app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        missing = await client.post(
            "/vacancy-subscriptions/admin/lookup",
            json={"email": "help@example.com"},
        )
        saved = await client.put(
            "/vacancy-subscriptions/admin",
            json={
                "email": "HELP@example.com",
                "unitSizes": [1, 3],
                "source": "Tech support request",
            },
        )
        deleted = await client.post(
            "/vacancy-subscriptions/admin/delete",
            json={"email": "help@example.com", "source": "Privacy request"},
        )

    audits = list(db.scalars(select(VacancySubscriptionAudit).order_by(VacancySubscriptionAudit.id)))
    assert missing.json() == {"subscription": None}
    assert saved.json()["subscription"]["unitSizes"] == [1, 3]
    assert saved.json()["subscription"]["consentVersion"] is None
    assert saved.json()["subscription"]["source"] == "Tech support request"
    assert deleted.json() == {"subscription": None}
    assert [audit.action for audit in audits] == ["add", "delete"]
    assert all(audit.acted_by_user_id == admin.id for audit in audits)
    assert db.scalar(select(VacancySubscription)) is None


@pytest.mark.anyio
async def test_admin_lookup_returns_subscription_metadata_with_a_qualified_timestamp() -> None:
    app, db, _ = _app_and_db()
    save_subscription(
        db,
        email="person@example.com",
        unit_sizes={2},
        source="public website",
        consent_version=VACANCY_CONSENT_VERSION,
        consented_at=datetime(2026, 8, 27, 18, tzinfo=UTC),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/vacancy-subscriptions/admin/lookup",
            json={"email": "person@example.com"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "subscription": {
            "email": "person@example.com",
            "unitSizes": [2],
            "consentedAt": "2026-08-27T18:00:00Z",
            "consentVersion": VACANCY_CONSENT_VERSION,
            "source": "public website",
        }
    }


@pytest.mark.anyio
async def test_admin_routes_reject_members() -> None:
    app, _, _ = _app_and_db(UserRole.MEMBER)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/vacancy-subscriptions/report")
    assert response.status_code == 403


@pytest.mark.anyio
async def test_admin_request_source_must_contain_text() -> None:
    app, _, _ = _app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/vacancy-subscriptions/admin",
            json={
                "email": "help@example.com",
                "unitSizes": [1],
                "source": "   ",
            },
        )

    assert response.status_code == 422
