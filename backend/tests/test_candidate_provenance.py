"""A detail's score values and provenance belong to the same captured rows and criteria."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.ai.dimension_scoring import score_dimensions
from app.ai.schemas import (
    DimensionScore,
    DimensionScoringReport,
    PoolDimensionReport,
    ScoreConfidence,
)
from app.api.applications import presentation
from app.db.models import Application, ApplicationAIResult, User, UserRole
from app.schemas.settings import AppSettings
from app.services.ranking.analysis import apply_consolidation, create_analysis
from app.services.ranking.member_state import get_or_reconcile_member_ranking
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


@pytest.mark.parametrize("merge_at", ["before-member-read", "after-score-capture"])
def test_detail_keeps_scores_and_priorities_together_during_consolidation(monkeypatch, merge_at) -> None:
    _app, writer, provider = setup_app(UserRole.MEMBER)
    user = writer.scalar(select(User))
    application = add_eligible(writer, email="synthetic@example.com", raw_hash="synthetic")
    application_id, user_id = application.id, user.id
    opening_id = current_opening_id(writer)
    settings = AppSettings()
    dimension = a_pattern_report().dimensions[0]
    # The survivor belongs to an earlier report. Both keys need valid cached
    # scores so the real consolidation can safely replace the current criterion.
    for key, value in [("older", 0.25), ("newer", 0.75)]:
        report = PoolDimensionReport(dimensions=[dimension.model_copy(update={
            "key": key, "definition": f"Synthetic {key} wording",
        })])
        analysis = create_analysis(writer, user=user, opening_id=opening_id, report=report,
            inputs_fingerprint=key, narrative=None,
            tier_layout=[{"id": "top", "label": "Top", "dimension_keys": [key]}])
        provider.routed.clear()
        provider.route("applicant_id", DimensionScoringReport(scores=[DimensionScore(
            dimension_key=key, score=value, confidence=ScoreConfidence.HIGH,
            rationale="Synthetic rationale", evidence="Synthetic evidence",
        )]))
        assert all(not result.failed for result in score_dimensions(writer, provider,
            applications=[application], report=report, settings=settings, max_workers=1))

    merged = []

    def consolidate():
        member = get_or_reconcile_member_ranking(writer, analysis, user)
        apply_consolidation(writer, analysis, member, merges={"newer": "older"},
            audit=[], narrative=None, settings=settings)
        merged.append(analysis.dimension_report["dimensions"][0]["key"])

    read_member = presentation.get_or_reconcile_member_ranking
    read_scores = presentation.selected_application_scores

    def capture_member(*args, **kwargs):
        if merge_at == "before-member-read":
            consolidate()
        return read_member(*args, **kwargs)

    def capture_scores(*args, **kwargs):
        results = read_scores(*args, **kwargs)
        if merge_at == "after-score-capture":
            consolidate()
        return results

    monkeypatch.setattr(presentation, "get_or_reconcile_member_ranking", capture_member)
    monkeypatch.setattr(presentation, "selected_application_scores", capture_scores)
    with Session(writer.get_bind()) as reader:
        detail = presentation.serialize_detail(reader.get(Application, application_id),
            reader, reader.get(User, user_id), opening_id)

    expected_key, expected_score = ("older", 0.25) if merge_at == "before-member-read" else ("newer", 0.75)
    assert merged == ["older"]
    assert [(score.dimension_key, score.score, score.weight) for score in detail.dimension_scores] == [
        (expected_key, expected_score, 1.0),
    ]
    assert detail.dimension_scoring_trace.dimension_count == 1


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
