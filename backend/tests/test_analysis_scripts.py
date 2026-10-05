"""Exercise dormant CLI entrypoints against current, opening-scoped synthetic data."""

from datetime import timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.time import pacific_today
from app.db.models import Analysis, Opening
from scripts import analyze_convergence, decompose_drift, harvest_golden_cases
from tests.db_support import memory_session


@pytest.mark.parametrize("module", [analyze_convergence, decompose_drift, harvest_golden_cases])
def test_analysis_entrypoints_use_current_models_and_one_opening(module, monkeypatch, capsys):
    with memory_session(foreign_keys=True) as db:
        today = pacific_today()
        openings = [Opening(unit_size_bedrooms=2, housing_charge_cents=100_000,
            application_open_date=today, application_close_date=today + timedelta(days=10),
            move_in_date=today + timedelta(days=30)) for _ in range(2)]
        db.add_all(openings)
        db.flush()
        wanted, other = [opening.id for opening in openings]
        db.add_all([Analysis(opening_id=wanted, dimension_report={"dimensions": [{"key": "wanted_axis"}]}),
            Analysis(opening_id=other, dimension_report={"dimensions": [{"key": "other_axis"}]})])
        db.commit()
        factory = sessionmaker(bind=db.get_bind())
        if module is analyze_convergence:
            monkeypatch.setattr(module, "SessionLocal", factory)
        else:
            monkeypatch.setattr("app.db.session.SessionLocal", factory)
        module.main(["--opening-id", str(wanted)])
        output = capsys.readouterr().out
        assert "other_axis" not in output
        assert output
        if module is analyze_convergence:
            assert "wanted_axis" in output
        with factory() as check:
            assert len(check.query(Analysis).all()) == 2
