from datetime import UTC, datetime, timedelta
from threading import get_ident

from sqlalchemy import event, select

from app.ai.dimension_consolidation import build_prompt, nominate_pairs
from app.ai.mock_provider import MockProvider
from app.ai.score_vectors import load_score_vectors
from app.db.models import Analysis, ApplicationAIResult, User, UserRole
from app.schemas.settings import AppSettings
from app.services.ranking.member_state import get_or_create_member_ranking
from app.services.ranking.pipeline import _stream_consolidate
from tests.application_support import current_opening_id
from tests.db_support import add_selected_result, memory_session
from tests.ranking_support import a_pattern_report, add_eligible, setup_app


def test_current_vectors_preserve_history_values_and_nomination_order():
    db = memory_session()
    now = datetime(2026, 10, 3, 12, tzinfo=UTC)
    # First-seen order differs from alphabetical order. Correlation ties must keep it.
    for key in ("z_first", "a_second", "m_third"):
        for applicant_id in range(1, 5):
            for version in range(10):
                add_selected_result(db, ApplicationAIResult(application_id=applicant_id, kind=f"dimension_scoring:{key}",
                    cache_key=f"synthetic-{key}-{applicant_id}-{version}", model_id="synthetic", prompt_version="test",
                    created_at=now + timedelta(seconds=version), output={"score": applicant_id * (version + 1) / 100},
                    narrative="Synthetic history that is not needed for vectors"))
    db.commit()
    previous = {}
    for row in db.scalars(select(ApplicationAIResult).order_by(ApplicationAIResult.created_at, ApplicationAIResult.id)):
        previous.setdefault(row.kind.split(":", 1)[1], {})[row.application_id] = float(row.output["score"])
    queries = []

    def record_sql(_con, _cur, statement, _params, _ctx, _many):
        queries.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", record_sql)
    try:
        current = load_score_vectors(db)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record_sql)
    assert current == previous
    assert list(current) == list(previous)
    canonical = {key: index for index, key in enumerate(previous)}
    before = nominate_pairs(["z_first"], canonical, previous)
    after = nominate_pairs(["z_first"], canonical, current)
    definitions = dict.fromkeys(canonical, "Synthetic definition")
    assert build_prompt(after, definitions) == build_prompt(before, definitions)
    assert len(queries) == 1
    assert "application_ai_results.narrative" not in queries[0]
    assert "application_ai_results.cache_key" not in queries[0]


def test_selected_vectors_ignore_other_passes():
    db = memory_session()
    now = datetime.now(UTC)
    for index, (kind, score) in enumerate([
        ("dimension_scoring:criterion", -0.8), ("dimension_scoring:criterion", 0.6), ("screening", 0.9),
    ]):
        add_selected_result(db, ApplicationAIResult(application_id=1, kind=kind, cache_key=f"synthetic-{index}",
            model_id="synthetic", prompt_version="test", created_at=now, output={"score": score}))
    db.commit()
    assert load_score_vectors(db) == {"criterion": {1: 0.6}}


def test_consolidation_reads_scores_on_the_request_thread():
    _app, db, _provider = setup_app(UserRole.MEMBER)
    add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    user = db.scalar(select(User))
    analysis = Analysis(dimension_report=a_pattern_report().model_dump(mode="json"), opening_id=current_opening_id(db))
    db.add(analysis)
    db.commit()
    member = get_or_create_member_ranking(db, analysis, user)
    request_thread = get_ident()
    score_read_threads = []

    def record_sql(_con, _cur, statement, _params, _ctx, _many):
        if "application_ai_results" in statement.lower():
            score_read_threads.append(get_ident())

    event.listen(db.get_bind(), "before_cursor_execute", record_sql)
    try:
        list(_stream_consolidate(db, MockProvider(), AppSettings(), analysis, member, a_pattern_report()))
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record_sql)
    assert score_read_threads == [request_thread]
