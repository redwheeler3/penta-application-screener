import json
import runpy
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import get_settings
from app.db.models import Base
from app.schemas.settings import AppSettings


def test_cache_identity_migration_can_build_rank_fingerprints() -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "d3e4f5a6b7c8_share_cache_across_provider_routes.py"
    )
    migration = runpy.run_path(str(migration_path))

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        historical_ai = AppSettings().ai
        historical_ai.screening_model = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        historical_ai.dimension_scoring_model = (
            "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        )
        for key in (
            "discovery_model",
            "decompose_model",
            "match_model",
            "consolidate_model",
        ):
            setattr(historical_ai, key, "us.anthropic.claude-sonnet-4-6")

        legacy = migration["_rank_fingerprint"](db, historical_ai, canonical=False)
        canonical = migration["_rank_fingerprint"](db, historical_ai, canonical=True)

    assert len(legacy) == 16
    assert len(canonical) == 16


def test_global_profile_migration_updates_only_saved_us_claude_routes() -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "3e4f5a6b7c8d_use_global_claude_profiles.py"
    )
    migration = runpy.run_path(str(migration_path))
    settings = {
        "ai": {
            "screening_model": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            "discovery_model": "us.anthropic.claude-sonnet-4-6",
            "decompose_model": "claude-sonnet-4-6",
            "spending_cap_usd": 2.0,
        },
        "unrelated": "preserved",
    }

    changed = migration["_replace_profile_ids"](settings, migration["_US_TO_GLOBAL"])

    assert changed is True
    assert settings == {
        "ai": {
            "screening_model": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
            "discovery_model": "global.anthropic.claude-sonnet-4-6",
            "decompose_model": "claude-sonnet-4-6",
            "spending_cap_usd": 2.0,
        },
        "unrelated": "preserved",
    }


def test_global_profile_migration_updates_an_existing_database(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "global-profiles.db"
    backend = Path(__file__).parents[1]
    database_url = f"sqlite:///{database.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    try:
        config = Config(str(backend / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "alembic"))
        command.upgrade(config, "2d3e4f5a6b7c")

        engine = create_engine(database_url)
        settings = {
            "ai": {
                "screening_model": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
                "discovery_model": "us.anthropic.claude-sonnet-4-6",
                "match_model": "claude-sonnet-4-6",
            }
        }
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO admin_settings (key, value, created_at, updated_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                ("app_settings", json.dumps(settings)),
            )
        engine.dispose()

        command.upgrade(config, "head")

        engine = create_engine(database_url)
        with engine.connect() as connection:
            stored = json.loads(
                connection.exec_driver_sql(
                    "SELECT value FROM admin_settings WHERE key = 'app_settings'"
                ).scalar_one()
            )
        engine.dispose()

        assert stored["ai"] == {
            "screening_model": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
            "discovery_model": "global.anthropic.claude-sonnet-4-6",
            "match_model": "claude-sonnet-4-6",
        }
    finally:
        get_settings.cache_clear()


def test_global_openai_migration_updates_only_saved_mantle_routes() -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "4f5a6b7c8d9e_use_global_openai_profiles.py"
    )
    migration = runpy.run_path(str(migration_path))
    settings = {
        "ai": {
            "screening_model": "openai.gpt-5.6-luna",
            "discovery_model": "openai.gpt-5.6-terra",
            "decompose_model": "gpt-5.6-terra",
            "spending_cap_usd": 2.0,
        },
        "unrelated": "preserved",
    }

    changed = migration["_replace_route_ids"](settings, migration["_MANTLE_TO_GLOBAL"])

    assert changed is True
    assert settings == {
        "ai": {
            "screening_model": "global.openai.gpt-5.6-luna",
            "discovery_model": "global.openai.gpt-5.6-terra",
            "decompose_model": "gpt-5.6-terra",
            "spending_cap_usd": 2.0,
        },
        "unrelated": "preserved",
    }


def test_global_openai_migration_updates_an_existing_database(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "global-openai-profiles.db"
    backend = Path(__file__).parents[1]
    database_url = f"sqlite:///{database.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    try:
        config = Config(str(backend / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "alembic"))
        command.upgrade(config, "3e4f5a6b7c8d")

        engine = create_engine(database_url)
        settings = {
            "ai": {
                "screening_model": "openai.gpt-5.6-luna",
                "discovery_model": "openai.gpt-5.6-terra",
                "match_model": "gpt-5.6-terra",
            }
        }
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO admin_settings (key, value, created_at, updated_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                ("app_settings", json.dumps(settings)),
            )
        engine.dispose()

        command.upgrade(config, "head")

        engine = create_engine(database_url)
        with engine.connect() as connection:
            stored = json.loads(
                connection.exec_driver_sql(
                    "SELECT value FROM admin_settings WHERE key = 'app_settings'"
                ).scalar_one()
            )
        engine.dispose()

        assert stored["ai"] == {
            "screening_model": "global.openai.gpt-5.6-luna",
            "discovery_model": "global.openai.gpt-5.6-terra",
            "match_model": "gpt-5.6-terra",
        }
    finally:
        get_settings.cache_clear()


def test_vacancy_hash_removal_migration_updates_an_existing_database(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "vacancy-hash-removal.db"
    backend = Path(__file__).parents[1]
    database_url = f"sqlite:///{database.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    try:
        config = Config(str(backend / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "alembic"))
        command.upgrade(config, "4f5a6b7c8d9e")

        engine = create_engine(database_url)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO vacancy_consent_receipts "
                "(subscription_id, email_hash, unit_sizes, consented_at, consent_version, "
                "source, fulfilled_at, retain_until, email_delivery_id) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, ?, CURRENT_TIMESTAMP, ?, ?)",
                (
                    1,
                    "legacy-hash",
                    "[1]",
                    "2026-08-27",
                    "public website",
                    "2027-09-01",
                    42,
                ),
            )
        engine.dispose()

        command.upgrade(config, "head")

        engine = create_engine(database_url)
        with engine.connect() as connection:
            receipt_columns = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(vacancy_consent_receipts)"
                )
            }
            audit_columns = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(vacancy_subscription_audits)"
                )
            }
            source = connection.exec_driver_sql(
                "SELECT source FROM vacancy_consent_receipts"
            ).scalar_one()
        engine.dispose()

        assert "email_hash" not in receipt_columns
        assert "email_hash" not in audit_columns
        assert source == "public website"
    finally:
        get_settings.cache_clear()


def test_fresh_schema_keeps_timestamp_defaults_on_opening_scoped_tables(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "m24-fresh.db"
    backend = Path(__file__).parents[1]
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    get_settings.cache_clear()
    try:
        config = Config(str(backend / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "alembic"))
        command.upgrade(config, "head")

        engine = create_engine(f"sqlite:///{database.as_posix()}")
        with engine.connect() as connection:
            for table in (
                "member_rules",
                "member_eligibility",
                "application_shortlist",
            ):
                columns = {
                    row[1]: row[4]
                    for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
                }
                assert columns["created_at"] is not None
                assert columns["updated_at"] is not None
    finally:
        get_settings.cache_clear()
