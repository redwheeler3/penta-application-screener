"""The fail-closed guard for evidence-bearing eval fixture capture."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.ai.schemas import PoolDimensionReport
from app.db.models import Analysis, User, UserRole
from app.evals.synthetic_guard import (
    NonSyntheticPoolError,
    is_synthetic_pool,
    require_synthetic_pool,
)
from app.schemas.settings import AppSettings
from app.services.applications.scope import opening_ai_applications
from app.services.ranking.analysis import create_analysis
from app.services.ranking.provenance import (
    capture_rank_sources,
    rank_inputs_fingerprint,
)
from tests.application_support import current_opening_id
from tests.ranking_support import add_eligible, setup_app


def test_explicitly_synthetic_run_is_accepted() -> None:
    analysis = Analysis(id=1, dimension_report={}, synthetic_data=True, source_application_ids=[])

    assert is_synthetic_pool(analysis) is True
    assert require_synthetic_pool(analysis, []) == "synthetic application data"


def test_unverified_run_is_refused() -> None:
    analysis = Analysis(id=2, dimension_report={}, synthetic_data=False)

    assert is_synthetic_pool(analysis) is False
    with pytest.raises(NonSyntheticPoolError, match="not stamped as synthetic"):
        require_synthetic_pool(analysis, [])


def test_analysis_is_synthetic_only_when_its_whole_pool_is_synthetic() -> None:
    _app, db, _provider = setup_app(role=UserRole.MEMBER)
    user = db.scalar(select(User))
    assert user is not None
    synthetic = add_eligible(db, email="synthetic@x.com", raw_hash="synthetic")
    synthetic.synthetic_data = True
    db.commit()

    sources, verified = capture_rank_sources(db, opening_ai_applications(db, current_opening_id(db)))
    analysis = create_analysis(
        db,
        opening_id=current_opening_id(db),
        user=user,
        report=PoolDimensionReport(dimensions=[]),
        inputs_fingerprint=rank_inputs_fingerprint(db, current_opening_id(db), AppSettings()),
        narrative=None, source_application_ids=sources, synthetic_data=verified,
    )
    assert analysis.synthetic_data is True

    add_eligible(db, email="unverified@x.com", raw_hash="unverified")
    sources, verified = capture_rank_sources(db, opening_ai_applications(db, current_opening_id(db)))
    analysis = create_analysis(
        db,
        opening_id=current_opening_id(db),
        user=user,
        report=PoolDimensionReport(dimensions=[]),
        inputs_fingerprint=rank_inputs_fingerprint(db, current_opening_id(db), AppSettings()),
        narrative=None, source_application_ids=sources, synthetic_data=verified,
    )
    assert analysis.synthetic_data is False


def test_capture_keeps_non_synthetic_assurance_after_a_source_withdraws():
    _app, db, _provider = setup_app(role=UserRole.MEMBER)
    ordinary = add_eligible(db, email="ordinary@example.com", raw_hash="ordinary")
    synthetic = add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    synthetic.synthetic_data = True
    db.commit()
    sources, verified = capture_rank_sources(db, [ordinary, synthetic])
    ordinary.withdrawn_at = datetime.now(UTC)
    db.commit()
    analysis = create_analysis(db, user=db.scalar(select(User)), opening_id=current_opening_id(db),
        report=PoolDimensionReport(), narrative=None, inputs_fingerprint="captured",
        source_application_ids=sources, synthetic_data=verified)
    assert not analysis.synthetic_data
    assert ordinary.id in analysis.source_application_ids
    with pytest.raises(NonSyntheticPoolError):
        require_synthetic_pool(analysis, [synthetic])


def test_unknown_or_non_synthetic_history_cannot_certify_inherited_text():
    _app, db, _provider = setup_app(role=UserRole.MEMBER)
    application = add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    application.synthetic_data = True
    db.add(Analysis(dimension_report={}, synthetic_data=True))
    db.commit()
    _sources, verified = capture_rank_sources(db, [application])
    assert not verified


def test_historical_stamp_cannot_certify_a_later_ordinary_applicant():
    from app.db.models import Application
    analysis = Analysis(id=1, dimension_report={}, synthetic_data=True, source_application_ids=[1])
    with pytest.raises(NonSyntheticPoolError):
        require_synthetic_pool(analysis, [Application(synthetic_data=False)])


def test_expired_captured_source_cannot_publish_pool_text():
    from app.core.time import pacific_today
    _app, db, _provider = setup_app(role=UserRole.MEMBER)
    application = add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    application.retention_due_on = pacific_today()
    db.commit()
    with pytest.raises(ValueError, match="expired during analysis"):
        create_analysis(db, user=db.scalar(select(User)), opening_id=current_opening_id(db),
            report=PoolDimensionReport(), narrative="Synthetic marker", inputs_fingerprint="captured",
            source_application_ids=[application.id], synthetic_data=False)
    db.rollback()
    assert db.scalar(select(Analysis)) is None


@pytest.mark.parametrize("initial_synthetic", [False, True])
@pytest.mark.parametrize("runtime_synthetic", [False, True])
def test_published_answers_refresh_assurance_and_actual_fixture_export(monkeypatch, initial_synthetic, runtime_synthetic):
    from app.core.config import get_settings
    from app.evals.fixture import build_fixture
    from app.schemas.applicant.answers import CanonicalApplicationAnswers
    from app.services.applications.intake import (
        create_application,
        publish_working_copy,
        save_working_copy,
    )
    from tests.applicant.support import app_and_db, sample_answers
    from tests.application_support import current_opening

    _app, db, _sender = app_and_db()
    opening = current_opening(db)
    monkeypatch.setattr("app.services.applications.intake.get_settings", lambda: get_settings().model_copy(
        update={"application_data_is_synthetic": runtime_synthetic}))
    now = datetime.now(UTC)
    answers = CanonicalApplicationAnswers.model_validate(sample_answers())
    application = create_application(db, str(answers.applicant.email), answers, saved_at=now, opening_ids=[opening.id])
    assert application.synthetic_data == runtime_synthetic
    application.synthetic_data = initial_synthetic
    save_working_copy(db, application, answers, saved_at=now, opening_ids=[opening.id])
    assert application.synthetic_data == initial_synthetic
    publish_working_copy(db, application, answers, [opening], submitted_at=now)
    db.commit()
    assert application.synthetic_data == runtime_synthetic
    source_ids, verified = capture_rank_sources(db, [application])
    analysis = Analysis(opening_id=opening.id, dimension_report={}, synthetic_data=verified, source_application_ids=source_ids)
    db.add(analysis)
    db.commit()
    if runtime_synthetic:
        assert build_fixture(db, analysis) is not None
    else:
        with pytest.raises(NonSyntheticPoolError):
            build_fixture(db, analysis)
