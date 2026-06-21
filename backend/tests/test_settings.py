import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base
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
    assert settings.unit_size == "2br"
    assert settings.move_in_date.isoformat() == "2026-09-01"
    assert settings.income_min == 70_000
    assert settings.income_max == 150_000


def test_save_app_settings_round_trips() -> None:
    db = make_session()
    saved = AppSettings(
        google_sheet_id="sheet-123",
        unit_size="3br",
        income_min=80_000,
        income_max=160_000,
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
