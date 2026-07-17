"""The synthetic-pool guard for score-defensibility eval-evidence capture.

Built and tested BEFORE the capture path it guards (same order as the DB-guard hook):
the whole point is that committing an applicant evidence quote is refused unless the pool
is provably synthetic. These tests pin the three outcomes — allowlisted sheet passes, an
unknown sheet is refused, a missing source is refused (fail-safe)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import RankingRun, SyncRun
from app.evals.synthetic_guard import (
    SYNTHETIC_SHEET_IDS,
    NonSyntheticPoolError,
    is_synthetic_pool,
    require_synthetic_pool,
)

_SYNTHETIC = next(iter(SYNTHETIC_SHEET_IDS))


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _run_from_sheet(db: Session, sheet_id: str | None) -> RankingRun:
    """A RankingRun whose pool traces to a SyncRun with the given sheet id (or no source
    at all when sheet_id is None)."""
    source_id = None
    if sheet_id is not None:
        sync = SyncRun(source_sheet_id=sheet_id, row_count=1, settings_fingerprint="fp")
        db.add(sync)
        db.flush()
        source_id = sync.id
    run = RankingRun(name="r", criteria={}, status="patterns_discovered", source_sync_run_id=source_id)
    db.add(run)
    db.flush()
    return run


def test_allowlisted_synthetic_sheet_is_accepted(db) -> None:
    run = _run_from_sheet(db, _SYNTHETIC)
    assert is_synthetic_pool(db, run) is True
    assert require_synthetic_pool(db, run) == _SYNTHETIC


def test_unknown_sheet_is_refused(db) -> None:
    run = _run_from_sheet(db, "some-real-deployment-sheet-id")
    assert is_synthetic_pool(db, run) is False
    with pytest.raises(NonSyntheticPoolError, match="not on the synthetic allowlist"):
        require_synthetic_pool(db, run)


def test_missing_source_is_refused(db) -> None:
    run = _run_from_sheet(db, None)
    assert is_synthetic_pool(db, run) is False
    with pytest.raises(NonSyntheticPoolError, match="no recorded source sheet"):
        require_synthetic_pool(db, run)


def test_dangling_source_sync_run_is_refused(db) -> None:
    # source_sync_run_id points at a SyncRun that doesn't exist — treat as unprovable.
    run = RankingRun(name="r", criteria={}, status="patterns_discovered", source_sync_run_id=999)
    db.add(run)
    db.flush()
    assert is_synthetic_pool(db, run) is False
    with pytest.raises(NonSyntheticPoolError):
        require_synthetic_pool(db, run)
