"""The operator wrapper snapshots and runs the production pipeline on synthetic copies."""

import hashlib
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.ai.mock_provider import MockProvider
from app.ai.schemas import DimensionMatchReport
from app.core.time import pacific_today
from app.db.models import Analysis, Base, Opening, User, UserRole
from app.evals import model_rank_bakeoff as bakeoff
from app.services.run_lock import ensure_lock_row
from app.services.settings import get_app_settings
from tests.application_support import current_opening_id
from tests.ranking_support import (
    a_pattern_report,
    a_scoring_report,
    add_eligible,
    route_criteria,
)


def test_snapshot_captures_committed_wal_schema_and_rows_without_changing_source(tmp_path):
    source, target = tmp_path / "source.db", tmp_path / "work.db"
    with closing(sqlite3.connect(source)) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("CREATE TABLE marker (value TEXT)")
        db.execute("INSERT INTO marker VALUES ('committed in WAL')")
        db.commit()
        before = source.read_bytes(), source.with_suffix(".db-wal").read_bytes()
        bakeoff.snapshot_database(source, target)
        with closing(sqlite3.connect(target)) as copied:
            assert copied.execute("SELECT value FROM marker").fetchall() == [("committed in WAL",)]
        assert (source.read_bytes(), source.with_suffix(".db-wal").read_bytes()) == before
        assert db.execute("SELECT count(*) FROM marker").fetchone() == (1,)
        with pytest.raises(ValueError, match="distinct"):
            bakeoff.snapshot_database(source, source)
        with pytest.raises(FileExistsError):
            bakeoff.snapshot_database(source, target)


@pytest.fixture
def rank_source(tmp_path):
    path = tmp_path / "source.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ensure_lock_row(db)
        db.add(User(email="synthetic-admin@example.com", display_name="Synthetic admin", role=UserRole.ADMIN, is_active=True))
        add_eligible(db, email="synthetic-applicant@example.com", raw_hash="synthetic")
        opening_id = current_opening_id(db)
        today = pacific_today()
        other = Opening(unit_size_bedrooms=2, housing_charge_cents=100_000,
            application_open_date=today - timedelta(days=1), application_close_date=today + timedelta(days=10),
            move_in_date=today + timedelta(days=30), published_at=datetime.now(UTC))
        db.add(other)
        db.flush()
        db.add(Analysis(opening_id=other.id, dimension_report=a_pattern_report().model_dump(mode="json")))
        db.commit()
    engine.dispose()
    return path, opening_id


@pytest.mark.parametrize("failure", [None, "decomposition", "preflight"])
def test_rank_copy_scopes_actual_pipeline_settings_results_and_cleanup(rank_source, tmp_path, monkeypatch, failure):
    source, opening_id = rank_source
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    provider = MockProvider()
    route_criteria(provider, a_pattern_report())
    provider.route("applicant_id", a_scoring_report())
    provider.route("prior_dimensions", DimensionMatchReport(matches=[]))
    calls = []
    real_call = provider.structured_output
    def call(**kwargs):
        calls.append(kwargs)
        if failure == "decomposition" and kwargs["schema"].__name__ == "DecompositionReport":
            raise RuntimeError("Synthetic failure")
        result = real_call(**kwargs)
        return replace(result, model_id=kwargs["model_id"])
    monkeypatch.setattr(provider, "structured_output", call)
    monkeypatch.setattr(bakeoff, "StrandsProvider", lambda **_: provider)
    engines, disposed = [], []
    def create(*args, **kwargs):
        engine = create_engine(*args, **kwargs)
        engines.append(engine)
        event.listen(engine, "engine_disposed", lambda engine: disposed.append(engine))
        return engine
    monkeypatch.setattr(bakeoff, "create_engine", create)
    work = tmp_path / "work.db"
    params = {"source_db": source, "work_db": work, "opening_id": opening_id if failure != "preflight" else 999,
        "configuration": "direct-candidate", "region": "us-east-1", "max_workers": 1, "openai_reasoning_effort": "high"}
    if failure:
        expected = "Rank did not complete" if failure == "decomposition" else "opening"
        with pytest.raises(Exception, match=expected):
            bakeoff.run_rank_copy(**params)
    else:
        report = bakeoff.run_rank_copy(**params)
        assert report["opening_id"] == opening_id
        assert report["stream_summary"]["type"] == "summary"
        assert report["fixture"]["dimensions"]
        assert all(value == "high" for value in report["reasoning"].values())
        assert calls
        assert all(call["reasoning_effort"] == "high" for call in calls)
        assert any(call["schema"].__name__ == "DimensionScoringReport" for call in calls)
    assert disposed == engines
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    inspection = create_engine(f"sqlite:///{work}")
    with Session(inspection) as db:
        ai = get_app_settings(db).ai
        assert ai.dimension_scoring_reasoning_effort == "high"
        if failure:
            assert len(db.scalars(select(Analysis)).all()) == 1

    inspection.dispose()
