from types import SimpleNamespace

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import AdminSetting, Base
from app.main import create_app
from app.schemas.settings import AppSettings
from app.services.settings import get_app_settings, save_app_settings


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_get_app_settings_returns_defaults_when_none_saved() -> None:
    db = make_session()

    settings = get_app_settings(db)

    # AppSettings is shared AI infrastructure; eligibility rules are stored separately.
    assert settings.ai.region == "us-east-1"


def test_get_app_settings_ignores_pre_split_rule_keys() -> None:
    """Unknown keys in a stored app_settings blob do not break loading."""
    db = make_session()
    db.add(
        AdminSetting(
            key="app_settings",
            value={
                "retired_option": "ignored",
                "max_dogs": 2,
                "income_min": 70_000,
                "income_max": 150_000,
                "min_children": 1,
                "disabled_checks": ["owns_real_estate"],
            },
        )
    )
    db.commit()

    settings = get_app_settings(db)

    assert settings.ai.region == "us-east-1"


def test_save_app_settings_round_trips() -> None:
    db = make_session()
    saved = AppSettings()
    saved.ai.discovery_fan_out = 3

    save_app_settings(db, saved)
    loaded = get_app_settings(db)

    assert loaded == saved


def test_save_app_settings_round_trips_ai_block() -> None:
    """A saved spending cap (and the rest of the ai block) survives the round
    trip — the UI edits the cap, so it must persist rather than reset.
    """
    db = make_session()
    saved = AppSettings()
    saved.ai.spending_cap_usd = 2.5

    save_app_settings(db, saved)
    loaded = get_app_settings(db)

    assert loaded.ai.spending_cap_usd == 2.5
    # The unedited ai fields keep their defaults, not get dropped.
    assert loaded.ai.max_workers == 50
    assert loaded.ai.region == "us-east-1"


@pytest.mark.anyio
async def test_read_settings_requires_login() -> None:
    transport = ASGITransport(app=create_app())

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/settings")

    assert response.status_code == 401


@pytest.mark.anyio
async def test_settings_lists_supported_model_routes_without_exposing_secrets(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.settings.get_settings",
        lambda: SimpleNamespace(openai_api_key="", anthropic_api_key=""),
    )
    app, _ = _rules_client(role="admin")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/settings")

    assert response.status_code == 200
    options = response.json()["aiModelOptions"]
    assert len(options) == 8
    assert {
        (option["modelId"], option["provider"], option["configured"])
        for option in options
    } >= {
        ("us.anthropic.claude-haiku-4-5-20251001-v1:0", "bedrock", True),
        ("claude-haiku-4-5-20251001", "anthropic", False),
        ("openai.gpt-5.6-luna", "bedrock", True),
        ("gpt-5.6-luna", "openai", False),
    }


@pytest.mark.anyio
async def test_member_cannot_change_shared_ai_settings() -> None:
    app, _ = _rules_client(role="member")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put("/settings", json={"ai": {"spendingCapUsd": 3.0}})

    assert response.status_code == 403


@pytest.mark.anyio
async def test_unconfigured_direct_provider_cannot_be_saved(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.settings.get_settings",
        lambda: SimpleNamespace(openai_api_key="", anthropic_api_key=""),
    )
    app, _ = _rules_client(role="admin")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/settings",
            json={"ai": {"screeningModel": "gpt-5.6-luna"}},
        )

    assert response.status_code == 409
    assert response.json()["code"] == "ai_provider_not_configured"


# --- Per-member eligibility rules -----------------------------------------------------


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


def _rules_client(role: str = "member") -> tuple:
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
    user_role = UserRole.ADMIN if role == "admin" else UserRole.MEMBER
    user = User(email=f"{role}@x.com", display_name=role, role=user_role, is_active=True)
    db.add(user)
    db.commit()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_current_user] = lambda: user
    return app, db


# A complete EligibilityRules wire body (camelCase), for PUTs. Override fields per-test.
def _rules_body(**overrides) -> dict:
    body = {
        "incomeMin": 70_000, "incomeMax": 150_000, "minAdultAge": 18, "maxChildAge": 17,
        "minChildren": 1, "maxChildren": 4, "maxDogs": 1, "maxCats": 1,
        "allowOtherPets": False, "disabledChecks": [],
    }
    body.update(overrides)
    return body


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
                "maxChildAge": 17, "minChildren": 1, "maxChildren": 4, "disabledChecks": [],
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
                "maxChildAge": 17, "minChildren": 1, "maxChildren": 4, "disabledChecks": [],
            },
        )
        assert resp.status_code == 422
        assert resp.json()["code"] == "invalid_settings"


# --- Committee-default edit and member reset ------------------------------------------


@pytest.mark.anyio
async def test_member_reset_drops_divergence_and_follows_default() -> None:
    app, _ = _rules_client()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Member diverges.
        await client.put("/eligibility-rules", json=_rules_body(incomeMin=90_000))
        assert (await client.get("/eligibility-rules")).json()["isDefault"] is False

        # DELETE resets them to the committee default.
        reset = await client.delete("/eligibility-rules")
        assert reset.status_code == 200
        assert reset.json()["isDefault"] is True
        assert reset.json()["rules"]["incomeMin"] == 70_000
        assert (await client.get("/eligibility-rules")).json()["isDefault"] is True


@pytest.mark.anyio
async def test_member_reset_is_idempotent_when_never_diverged() -> None:
    app, _ = _rules_client()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # No divergence yet — reset is a harmless no-op.
        reset = await client.delete("/eligibility-rules")
        assert reset.status_code == 200
        assert reset.json()["isDefault"] is True


@pytest.mark.anyio
async def test_admin_edits_committee_default() -> None:
    app, _ = _rules_client(role="admin")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Default starts at schema defaults.
        assert (await client.get("/eligibility-rules/committee-default")).json()["incomeMin"] == 70_000

        put = await client.put("/eligibility-rules/committee-default", json=_rules_body(incomeMin=85_000))
        assert put.status_code == 200
        assert put.json()["incomeMin"] == 85_000
        # A non-diverged member now reads the new default.
        assert (await client.get("/eligibility-rules")).json()["rules"]["incomeMin"] == 85_000


@pytest.mark.anyio
async def test_member_cannot_edit_committee_default() -> None:
    app, _ = _rules_client(role="member")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.put("/eligibility-rules/committee-default", json=_rules_body(incomeMin=85_000))
        assert resp.status_code == 403


@pytest.mark.anyio
async def test_admin_default_edit_does_not_touch_diverged_member() -> None:
    # Model A: editing the default has zero side effects on a member who diverged.
    app, _ = _rules_client(role="admin")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # This admin also diverges their own rules.
        await client.put("/eligibility-rules", json=_rules_body(incomeMin=95_000))
        # Then changes the committee default.
        await client.put("/eligibility-rules/committee-default", json=_rules_body(incomeMin=60_000))
        # Their own divergence is untouched — no reconciliation.
        me = (await client.get("/eligibility-rules")).json()
        assert me["isDefault"] is False
        assert me["rules"]["incomeMin"] == 95_000


@pytest.mark.anyio
async def test_eligibility_check_catalog_is_backend_owned() -> None:
    app, _ = _rules_client()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/eligibility-rules/catalog")

    assert response.status_code == 200
    catalog = response.json()
    assert {check["id"] for check in catalog["deterministic"]} >= {
        "income_below_range",
        "owns_real_estate",
    }
    assert {check["id"] for check in catalog["ai"]} >= {
        "fake_contact",
        "pets_over_limit",
    }
