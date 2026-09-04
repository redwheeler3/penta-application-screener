from types import SimpleNamespace

import pytest

from app.ai.schemas import (
    DimensionScore,
    PoolDimension,
    PoolDimensionReport,
    ScoreConfidence,
)
from app.db.models import Analysis, Application
from app.schemas.settings import AppSettings
from scripts import harvest_scoring_cases


def _application() -> Application:
    return Application(
        id=7,
        primary_email="synthetic@example.com",
        applicant_name="Synthetic",
        raw_row={},
        raw_row_hash="hash",
        normalized={},
        synthetic_data=True,
    )


def _dimension() -> PoolDimension:
    return PoolDimension(
        key="employment_tenure",
        name="Employment tenure",
        definition="Length of current employment.",
        high_end="Long tenure.",
        low_end="Recently started.",
        why_it_differentiates="Tenure varies.",
    )


def test_candidates_use_only_current_cache_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    application = _application()
    dimension = _dimension()
    score = DimensionScore(
        dimension_key=dimension.key,
        score=0,
        rationale="No dates provided.",
        evidence="",
        confidence=ScoreConfidence.LOW,
    )
    seen: dict = {}

    monkeypatch.setattr(
        harvest_scoring_cases,
        "current_dimension_report",
        lambda _analysis: PoolDimensionReport(dimensions=[dimension]),
    )
    monkeypatch.setattr(
        harvest_scoring_cases,
        "applications_to_score",
        lambda _db, opening_id: [application] if opening_id == 3 else [],
    )
    monkeypatch.setattr(
        harvest_scoring_cases, "get_app_settings", lambda _db: AppSettings()
    )

    def cached(_db, cached_application, **identity):
        seen.update(identity)
        assert cached_application is application
        return SimpleNamespace(output=score)

    monkeypatch.setattr(harvest_scoring_cases, "cached_outcome", cached)

    candidates = harvest_scoring_cases.scoring_candidates(
        object(), Analysis(opening_id=3, synthetic_data=True)
    )

    assert candidates == [
        harvest_scoring_cases.ScoringCandidate(application, dimension, score)
    ]
    assert seen["kind"] == "dimension_scoring:employment_tenure"
    assert seen["prompt_version"] == harvest_scoring_cases.PROMPT_VERSION
    assert seen["model_id"] == AppSettings().ai.dimension_scoring_model
