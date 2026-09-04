from types import SimpleNamespace

import pytest

from app.ai.schemas import ScreeningReport
from app.db.models import Analysis, Application
from app.schemas.settings import AppSettings
from scripts import harvest_screening_cases


def _application() -> Application:
    return Application(
        id=9,
        primary_email="synthetic@example.com",
        applicant_name="Synthetic",
        raw_row={},
        raw_row_hash="hash",
        normalized={},
        synthetic_data=True,
    )


def test_candidates_use_only_current_opening_cache_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _application()
    report = ScreeningReport()
    seen: dict = {}

    monkeypatch.setattr(
        harvest_screening_cases,
        "opening_ai_applications",
        lambda _db, opening_id: [application] if opening_id == 4 else [],
    )
    monkeypatch.setattr(
        harvest_screening_cases, "get_app_settings", lambda _db: AppSettings()
    )

    def cached(_db, cached_application, **identity):
        seen.update(identity)
        assert cached_application is application
        return SimpleNamespace(output=report)

    monkeypatch.setattr(harvest_screening_cases, "cached_outcome", cached)

    candidates = harvest_screening_cases.screening_candidates(
        object(), Analysis(opening_id=4, synthetic_data=True)
    )

    assert candidates == [
        harvest_screening_cases.ScreeningCandidate(application, report)
    ]
    assert seen["kind"] == "screening"
    assert seen["prompt_version"] == harvest_screening_cases.screening_prompt_version()
    assert seen["model_id"] == AppSettings().ai.screening_model
