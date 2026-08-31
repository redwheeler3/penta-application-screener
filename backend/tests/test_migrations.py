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
        legacy = migration["_rank_fingerprint"](db, AppSettings().ai, canonical=False)
        canonical = migration["_rank_fingerprint"](db, AppSettings().ai, canonical=True)

    assert len(legacy) == 16
    assert len(canonical) == 16


def test_fresh_schema_keeps_timestamp_defaults_on_opening_scoped_tables(
    tmp_path: Path, monkeypatch,
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
                    for row in connection.exec_driver_sql(
                        f"PRAGMA table_info({table})"
                    )
                }
                assert columns["created_at"] is not None
                assert columns["updated_at"] is not None
    finally:
        get_settings.cache_clear()
