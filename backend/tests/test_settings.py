import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import AdminSetting, Base
from app.main import create_app
from app.schemas.settings import AppSettings, google_sheet_url_from_id
from app.services.settings import get_app_settings, save_app_settings


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_get_app_settings_returns_defaults_when_none_saved() -> None:
    db = make_session()

    settings = get_app_settings(db)

    assert settings.google_sheet_id == ""
    assert settings.max_dogs == 1
    assert settings.max_cats == 1
    assert settings.allow_other_pets is False


def test_get_app_settings_ignores_pre_split_rule_keys() -> None:
    """A stored app_settings blob written before M15 1d still carries the numeric rule keys
    (income_min, etc.). Those moved to committee_default_rules, but the old keys must not
    break load — AppSettings ignores unknown keys."""
    db = make_session()
    db.add(
        AdminSetting(
            key="app_settings",
            value={
                "google_sheet_id": "sheet-123",
                "max_dogs": 2,
                "income_min": 70_000,
                "income_max": 150_000,
                "min_children": 1,
                "disabled_rules": ["owns_real_estate"],
            },
        )
    )
    db.commit()

    settings = get_app_settings(db)

    assert settings.google_sheet_id == "sheet-123"
    assert settings.max_dogs == 2


def test_save_app_settings_round_trips() -> None:
    db = make_session()
    saved = AppSettings(
        google_sheet_id="sheet-123",
        max_dogs=2,
        max_cats=0,
        allow_other_pets=True,
    )

    save_app_settings(db, saved)
    loaded = get_app_settings(db)

    assert loaded == saved


def test_save_app_settings_round_trips_ai_block() -> None:
    """A saved spending cap (and the rest of the ai block) survives the round
    trip — the UI edits the cap, so it must persist rather than reset.
    """
    db = make_session()
    saved = AppSettings(google_sheet_id="sheet-123")
    saved.ai.spending_cap_usd = 2.5

    save_app_settings(db, saved)
    loaded = get_app_settings(db)

    assert loaded.ai.spending_cap_usd == 2.5
    # The unedited ai fields keep their defaults, not get dropped.
    assert loaded.ai.max_workers == 50
    assert loaded.ai.region == "us-west-2"


def test_app_settings_accepts_google_sheet_url() -> None:
    settings = AppSettings(
        google_sheet_id="https://docs.google.com/spreadsheets/d/sheet-123/edit?gid=0#gid=0",
    )

    assert settings.google_sheet_id == "sheet-123"


def test_app_settings_accepts_raw_google_sheet_id() -> None:
    settings = AppSettings(google_sheet_id=" sheet-123 ")

    assert settings.google_sheet_id == "sheet-123"


def test_google_sheet_url_from_id_returns_copyable_url() -> None:
    assert google_sheet_url_from_id("sheet-123") == "https://docs.google.com/spreadsheets/d/sheet-123/edit"


@pytest.mark.anyio
async def test_read_settings_requires_login() -> None:
    transport = ASGITransport(app=create_app())

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/settings")

    assert response.status_code == 401


# --- Per-member eligibility rules (M15 1d) --------------------------------------------


def test_member_rules_defaults_to_committee_default_then_diverges() -> None:
    from app.schemas.settings import EligibilityRules
    from app.services.rules import (
        member_rules,
        save_committee_default_rules,
        save_member_rules,
    )

    db = make_session()
    save_committee_default_rules(db, EligibilityRules(income_min=70_000))

    rules, is_default = member_rules(db, user_id=1)
    assert is_default is True
    assert rules.income_min == 70_000

    # Copy-on-write divergence: the member now reads their own rules.
    save_member_rules(db, user_id=1, rules=EligibilityRules(income_min=90_000))
    rules, is_default = member_rules(db, user_id=1)
    assert is_default is False
    assert rules.income_min == 90_000
    # Another member with no row still sees the committee default.
    assert member_rules(db, user_id=2)[1] is True


def _rules_client() -> tuple:
    from sqlalchemy.pool import StaticPool

    from app.api.dependencies import require_current_user
    from app.db.models import User, UserRole
    from app.db.session import get_db

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import sessionmaker

    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    user = User(email="m@x.com", display_name="M", role=UserRole.MEMBER, is_active=True)
    db.add(user)
    db.commit()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_current_user] = lambda: user
    return app, db


@pytest.mark.anyio
async def test_get_and_put_eligibility_rules_round_trip() -> None:
    app, _ = _rules_client()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Default: schema defaults, is_default True.
        body = (await client.get("/eligibility-rules")).json()
        assert body["isDefault"] is True
        assert body["rules"]["incomeMin"] == 70_000

        # PUT the member's own rules -> is_default False, values persist.
        put = await client.put(
            "/eligibility-rules",
            json={
                "incomeMin": 80_000, "incomeMax": 160_000, "minAdultAge": 18,
                "maxChildAge": 17, "minChildren": 1, "maxChildren": 4, "disabledRules": [],
            },
        )
        assert put.status_code == 200
        assert put.json()["isDefault"] is False
        assert put.json()["rules"]["incomeMin"] == 80_000
        assert (await client.get("/eligibility-rules")).json()["isDefault"] is False


@pytest.mark.anyio
async def test_put_eligibility_rules_rejects_inverted_income_range() -> None:
    app, _ = _rules_client()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.put(
            "/eligibility-rules",
            json={
                "incomeMin": 200_000, "incomeMax": 100_000, "minAdultAge": 18,
                "maxChildAge": 17, "minChildren": 1, "maxChildren": 4, "disabledRules": [],
            },
        )
        assert resp.status_code == 422
        assert resp.json()["code"] == "invalid_settings"
