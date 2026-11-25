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
        db.add_all([Analysis(opening_id=wanted, source_application_ids=[], synthetic_data=True, dimension_report={"dimensions": [{"key": "wanted_axis"}]}),
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


@pytest.mark.parametrize("mode", ["matching", "decomposition"])
@pytest.mark.parametrize(("verified", "sources", "accepted"), [(True, [], True), (True, None, False), (False, [], False)])
def test_categorical_harvest_guards_evidence_before_printing(mode, verified, sources, accepted, monkeypatch, capsys):
    from app.db.models import AnalysisAudit
    from app.evals.synthetic_guard import NonSyntheticPoolError

    db = memory_session()
    today = pacific_today()
    opening = Opening(unit_size_bedrooms=2, housing_charge_cents=100_000, move_in_date=today)
    db.add(opening)
    db.flush()
    marker = "Fictional source rationale"
    report = {"dimensions": [{"key": k, "definition": k} for k in ("first", "second")]}
    audit = AnalysisAudit(decompose={"settled": [{"key": "merged", "decision": marker, "source_keys": ["first", "second"]}]})
    db.add(Analysis(opening_id=opening.id, dimension_report=report, synthetic_data=verified, source_application_ids=sources, audit=audit))
    db.commit()
    monkeypatch.setattr("app.db.session.SessionLocal", sessionmaker(bind=db.get_bind()))
    if accepted:
        harvest_golden_cases.main([mode, "--opening-id", str(opening.id)])
        assert marker in capsys.readouterr().out
    else:
        with pytest.raises(NonSyntheticPoolError):
            harvest_golden_cases.main([mode, "--opening-id", str(opening.id)])
        assert not capsys.readouterr().out
