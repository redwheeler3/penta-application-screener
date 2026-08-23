import runpy
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

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
