"""The fail-closed guard for evidence-bearing eval fixture capture."""

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
from app.services.ranking.analysis import create_analysis
from tests.ranking_support import add_eligible, setup_app


def test_explicitly_synthetic_run_is_accepted() -> None:
    analysis = Analysis(id=1, dimension_report={}, synthetic_data=True)

    assert is_synthetic_pool(analysis) is True
    assert require_synthetic_pool(analysis) == "synthetic application data"


def test_unverified_run_is_refused() -> None:
    analysis = Analysis(id=2, dimension_report={}, synthetic_data=False)

    assert is_synthetic_pool(analysis) is False
    with pytest.raises(NonSyntheticPoolError, match="not stamped as synthetic"):
        require_synthetic_pool(analysis)


def test_analysis_is_synthetic_only_when_its_whole_pool_is_synthetic() -> None:
    _app, db, _provider = setup_app(role=UserRole.MEMBER)
    user = db.scalar(select(User))
    assert user is not None
    synthetic = add_eligible(db, email="synthetic@x.com", raw_hash="synthetic")
    synthetic.synthetic_data = True
    db.commit()

    analysis = create_analysis(
        db,
        user=user,
        report=PoolDimensionReport(dimensions=[]),
        settings=AppSettings(),
        narrative=None,
    )
    assert analysis.synthetic_data is True

    add_eligible(db, email="unverified@x.com", raw_hash="unverified")
    analysis = create_analysis(
        db,
        user=user,
        report=PoolDimensionReport(dimensions=[]),
        settings=AppSettings(),
        narrative=None,
    )
    assert analysis.synthetic_data is False
