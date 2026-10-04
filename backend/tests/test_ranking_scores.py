"""Selected scores stay batched as criteria and score history grow."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event

from app.db.models import Analysis, ApplicationAIResult, UserRole
from app.services.ranking.view import candidate_scores
from tests.application_support import current_opening_id
from tests.db_support import add_selected_result
from tests.ranking_support import a_pattern_report, add_eligible, setup_app


@pytest.mark.parametrize("dimension_count", [1, 15])
def test_score_read_uses_one_query_and_ignores_newer_unselected_history(dimension_count) -> None:
    _app, db, _provider = setup_app(UserRole.MEMBER)
    active = add_eligible(db, email="active@example.com", raw_hash="active")
    historical = add_eligible(db, email="historical@example.com", raw_hash="historical")
    historical.withdrawn_at = datetime.now(UTC)
    report = a_pattern_report()
    report.dimensions = [
        report.dimensions[0].model_copy(update={"key": f"criterion_{i}"})
        for i in range(dimension_count)
    ]
    analysis = Analysis(opening_id=current_opening_id(db), dimension_report=report.model_dump(mode="json"))
    now = datetime.now(UTC)
    for application in (active, historical):
        for dimension in report.dimensions:
            for version, (created_at, score) in enumerate([
                (now - timedelta(days=1), -0.9), (now, 0.2), (now, 0.8),
            ]):
                row = ApplicationAIResult(
                    application_id=application.id, kind=f"dimension_scoring:{dimension.key}",
                    cache_key=f"{application.id}-{dimension.key}-{version}", model_id="synthetic",
                    prompt_version="test", created_at=created_at,
                    output={"score": score, "confidence": "high", "rationale": "Synthetic", "evidence": "Example"},
                )
                if version == 1:
                    add_selected_result(db, row)
                else:
                    db.add(row)
    db.commit()
    active_id, historical_id = active.id, historical.id
    score_queries = []

    def record(_connection, _cursor, statement, parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT") and any(
            isinstance(value, str) and value.startswith("dimension_scoring:") for value in parameters
        ):
            score_queries.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", record)
    try:
        scores = candidate_scores(db, analysis)
        assert [candidate.application_id for candidate in scores] == [active_id]
        assert [score.dimension_key for score in scores[0].scores] == [dimension.key for dimension in report.dimensions]
        assert [score.score for score in scores[0].scores] == [0.2] * dimension_count
        assert len(score_queries) == 1
        assert "application_ai_results.narrative" not in score_queries[0]
        score_queries.clear()
        scores = candidate_scores(db, analysis, include_application=historical)
        assert {candidate.application_id for candidate in scores} == {active_id, historical_id}
        assert len(score_queries) == 1
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record)
