"""A detail's score values and provenance belong to the same captured rows and criteria."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import event, select

from app.api.applications import presentation
from app.db.models import ApplicationAIResult, User, UserRole
from app.services.ranking.analysis import create_analysis
from app.services.ranking.view import selected_application_scores
from tests.application_support import current_opening_id
from tests.db_support import add_selected_result
from tests.ranking_support import (
    a_pattern_report,
    a_pattern_report_v2,
    add_eligible,
    setup_app,
)


def score(application_id, key, version, *, created_at, value=0.5):
    return ApplicationAIResult(
        producer_application_id=application_id, kind=f"dimension_scoring:{key}", cache_key=f"{key}-{version}",
        model_id="synthetic-model", prompt_version=str(version), created_at=created_at,
        narrative="Synthetic unused narrative", input_tokens=10, output_tokens=20, cost_usd=0.01,
        output={"score": value, "confidence": "high", "rationale": "Synthetic", "evidence": "Example"},
    )


def test_detail_preserves_captured_score_and_trace_during_a_new_analysis(monkeypatch) -> None:
    _app, db, _provider = setup_app(UserRole.MEMBER)
    application = add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    opening_id = current_opening_id(db)
    user = db.scalar(select(User))
    report = a_pattern_report()
    create_analysis(db, user=user, opening_id=opening_id, report=report, narrative=None, inputs_fingerprint="synthetic",
        tier_layout=[{"id": "critical", "label": "Critical", "dimension_keys": [dim.key for dim in report.dimensions], "ignore": False}])
    now = datetime.now(UTC)
    for dim in report.dimensions:
        add_selected_result(db, score(application.id, dim.key, "original", created_at=now))
    db.commit()
    assemble = presentation.candidate_scores

    def advance(_db, analysis, **kwargs):
        create_analysis(db, user=user, opening_id=opening_id, report=a_pattern_report_v2(), narrative=None, inputs_fingerprint="later")
        add_selected_result(db, score(application.id, report.dimensions[0].key, "later", created_at=now + timedelta(seconds=1), value=-0.8))
        db.commit()
        return assemble(_db, analysis, **kwargs)

    monkeypatch.setattr(presentation, "candidate_scores", advance)
    detail = presentation.serialize_detail(application, db, user, opening_id)
    assert {item.dimension_key for item in detail.dimension_scores} == {dim.key for dim in report.dimensions}
    assert [item.score for item in detail.dimension_scores] == [0.5, 0.5]
    assert detail.dimension_scoring_trace.dimension_count == 2
    assert detail.dimension_scoring_trace.prompt_versions == ["original"]
    assert detail.dimension_scoring_trace.input_tokens == 20


def test_selected_score_loader_does_not_materialize_history_or_unused_narratives() -> None:
    _app, db, _provider = setup_app(UserRole.MEMBER)
    application_id = add_eligible(db, email="synthetic@example.com", raw_hash="synthetic").id
    report = a_pattern_report()
    now = datetime.now(UTC)
    for dim in report.dimensions:
        for version in range(50):
            add_selected_result(db, score(application_id, dim.key, version, created_at=now))
    db.commit()
    db.expunge_all()
    loaded = []

    def record(_session, instance):
        if isinstance(instance, ApplicationAIResult):
            loaded.append(instance.id)

    event.listen(db, "loaded_as_persistent", record)
    try:
        results = selected_application_scores(db, application_id, report)
        assert len(loaded) == len(report.dimensions)
        assert {result.prompt_version for result in results} == {"49"}
        assert all("narrative" not in result.__dict__ for result in results)
    finally:
        event.remove(db, "loaded_as_persistent", record)
