"""Unit tests for per-dimension scoring.

Scores are cached per (candidate, dimension key); a candidate's uncached
dimensions are sent to the model in one batched call, stored as per-key rows, and
merged with reused cached scores. These tests pin: per-key cache reuse, that only
uncached dimensions are sent, token splitting, the merge shape, and the
whole-pool ceiling estimate.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.analysis import cache_key
from app.ai.dimension_scoring import (
    KIND_PREFIX,
    PROMPT_VERSION,
    applications_to_score,
    kind_for_dimension,
    score_dimensions,
)
from app.ai.mock_provider import MockProvider
from app.ai.model_catalog import MODEL_IDS_BY_ROUTE
from app.ai.schemas import (
    DimensionScore,
    DimensionScoringReport,
    PoolDimension,
    PoolDimensionReport,
    ScoreConfidence,
)
from app.ai.score_vectors import load_score_vectors
from app.db.models import (
    Analysis,
    Application,
    ApplicationAIResult,
    ApplicationAISelection,
    Base,
    User,
    UserRole,
)
from app.schemas.settings import AppSettings
from app.services.ranking.freshness import rank_inputs_fingerprint
from app.services.ranking.view import candidate_scores, selected_application_scores
from tests.application_support import activate_application, current_opening_id


def make_db() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    db.add(User(email="m@x.com", display_name="M", role=UserRole.MEMBER, is_active=True))
    db.commit()
    return db


@pytest.mark.parametrize("storage_fails", [False, True])
def test_candidate_vector_and_consumed_references_publish_atomically(monkeypatch, storage_fails):
    from app.ai import dimension_scoring

    db = make_db()
    application = add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    report = report_with(["a", "b", "c"])
    provider = MockProvider()
    provider.queue(a_scoring_report(["a", "b", "c"]))
    staged = dimension_scoring.stage_result
    calls, commits = [], []

    def stage(*args, **kwargs):
        outcome = staged(*args, **kwargs)
        calls.append(True)
        if storage_fails and len(calls) == 2:
            raise ValueError("Synthetic storage failure after staging a partial vector")
        return outcome

    monkeypatch.setattr(dimension_scoring, "stage_result", stage)
    event.listen(db, "after_commit", lambda _session: commits.append(True))
    results = score_dimensions(db, provider, applications=[application], report=report,
        settings=AppSettings(), max_workers=1)
    if storage_fails:
        with pytest.raises(ValueError, match="partial vector"):
            list(results)
        assert commits == []
        assert db.scalar(select(ApplicationAIResult)) is None
        assert db.scalar(select(ApplicationAISelection)) is None
    else:
        assert len(list(results)) == 1
        assert commits == [True]
        assert len(db.scalars(select(ApplicationAIResult)).all()) == 3
        assert len(db.scalars(select(ApplicationAISelection)).all()) == 3


def add_eligible(db: Session, *, email: str, raw_hash: str) -> Application:
    app = Application(
        primary_email=email,
        applicant_name="Test",
        raw_row={"Why a co-op": "We want community."},
        raw_row_hash=raw_hash,
        normalized={},
        submitted_at=datetime.now(UTC),
    )
    return activate_application(db, app)


def report_with(keys: list[str]) -> PoolDimensionReport:
    return PoolDimensionReport(
        dimensions=[
            PoolDimension(
                key=k,
                name=k.replace("_", " ").title(),
                definition="def",
                high_end="high", low_end="low", why_it_differentiates="why",
            )
            for k in keys
        ],
    )


def a_scoring_report(keys: list[str]) -> DimensionScoringReport:
    return DimensionScoringReport(
        scores=[
            DimensionScore(
                dimension_key=k,
                score=0.7,
                rationale="stated clearly",
                evidence="we want community",
                confidence=ScoreConfidence.MEDIUM,
            )
            for k in keys
        ]
    )


def run_scores(db, provider, apps, report, settings):
    return list(
        score_dimensions(
            db,
            provider,
            applications=apps,
            report=report,
            settings=settings,
            max_workers=2,
        )
    )


@pytest.mark.parametrize("new_consumer", [False, True])
@pytest.mark.parametrize("mixed", [False, True])
def test_cached_scores_and_provenance_match_ranking_and_consolidation(new_consumer, mixed) -> None:
    db = make_db()
    application = add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    settings = AppSettings()
    original_model = settings.ai.dimension_scoring_model
    provider = MockProvider()
    report = report_with(["community", "skills"])
    provider.queue(a_scoring_report(["community", "skills"]), model_id=original_model)
    run_scores(db, provider, [application], report, settings)
    original_ids = {row.id for row in selected_application_scores(db, application.id, report)}
    alternate_model = MODEL_IDS_BY_ROUTE["bedrock"]["sonnet"]
    assert alternate_model != original_model
    settings.ai.dimension_scoring_model = alternate_model
    alternate = a_scoring_report(["community", "skills"])
    for score in alternate.scores:
        score.score = -0.6
    provider.queue(alternate, model_id=alternate_model)
    run_scores(db, provider, [application], report, settings)
    if new_consumer:
        application.withdrawn_at = datetime.now(UTC)
        db.commit()
        application = add_eligible(db, email="reapplication@example.com", raw_hash="synthetic")
    settings.ai.dimension_scoring_model = original_model
    if mixed:
        report = report_with(["community", "skills", "new"])
        provider.queue(a_scoring_report(["new"]), model_id=original_model)
    result = run_scores(db, provider, [application], report, settings)[0]
    analysis = Analysis(opening_id=current_opening_id(db), dimension_report=report.model_dump(mode="json"))
    displayed = candidate_scores(db, analysis)[0]
    assert [score.score for score in displayed.scores] == [score.score for score in result.outcome.output.scores]
    assert all(score.score == 0.7 for score in displayed.scores)
    rows = selected_application_scores(db, application.id, report)
    assert original_ids <= {row.id for row in rows}
    assert {row.model_id for row in rows} == {original_model}
    vectors = load_score_vectors(db)
    assert all(vectors[dim.key][application.id] == 0.7 for dim in report.dimensions)
    assert len(provider.calls) == (3 if mixed else 2)


def test_kind_is_keyed_by_dimension_key() -> None:
    assert kind_for_dimension("community") == f"{KIND_PREFIX}:community"


def test_scores_keep_the_original_cache_keys_when_an_applicant_changes(monkeypatch) -> None:
    db = make_db()
    applications = [
        add_eligible(db, email=f"a{i}@example.com", raw_hash=f"old-{i}")
        for i in (1, 2)
    ]
    keys = ["community", "skills"]
    settings = AppSettings()
    original_keys = {
        cache_key(
            application=applications[1], kind=kind_for_dimension(key),
            model_id=settings.ai.dimension_scoring_model, prompt_version=PROMPT_VERSION,
        )
        for key in keys
    }
    provider = MockProvider()
    for _ in applications:
        provider.queue(a_scoring_report(keys))

    def controlled_pool(items, *, call, max_workers):
        yield items[0], call(items[0]), None
        applications[1].raw_row_hash = "new-2"
        db.commit()
        yield items[1], call(items[1]), None

    monkeypatch.setattr("app.ai.dimension_scoring.run_in_pool", controlled_pool)
    run_scores(db, provider, applications, report_with(keys), settings)
    stored_keys = set(db.scalars(select(ApplicationAIResult.cache_key).where(
        ApplicationAIResult.producer_application_id == applications[1].id,
    )))
    assert stored_keys == original_keys


def test_scores_all_dimensions_and_does_not_touch_status() -> None:
    db = make_db()
    app1 = add_eligible(db, email="a@x.com", raw_hash="h1")
    settings = AppSettings()
    provider = MockProvider()
    keys = ["community", "skills"]
    report = report_with(keys)

    provider.queue(a_scoring_report(keys))
    results = run_scores(db, provider, [app1], report, settings)

    assert len(results) == 1
    assert not results[0].failed
    # One row stored per (candidate, dimension key).
    rows = db.scalars(select(ApplicationAIResult)).all()
    assert len(rows) == 2
    assert {r.kind for r in rows} == {kind_for_dimension("community"), kind_for_dimension("skills")}
    # Informational: scoring writes only score rows, never an eligibility fact. The only
    # eligibility signals are the on-read hard-filter reasons + screening flags, so a clean
    # applicant's machine verdict is untouched by scoring.
    assert db.scalar(select(ApplicationAIResult).where(ApplicationAIResult.kind == "screening")) is None


def test_cached_dimension_is_reused_only_uncached_dims_are_sent() -> None:
    db = make_db()
    app = add_eligible(db, email="a@x.com", raw_hash="h1")
    settings = AppSettings()
    provider = MockProvider()

    # First run scores two dimensions.
    first_keys = ["community", "skills"]
    provider.queue(a_scoring_report(first_keys))
    run_scores(db, provider, [app], report_with(first_keys), settings)
    assert len(provider.calls) == 1

    # Re-rank: 'community' recurs under the same key (reused — a matched dimension
    # would have had its key adopted before this), 'stability' is new; skills dropped.
    new_report = report_with(["community", "stability"])
    # Only the uncached dimension ('stability') should be scored.
    provider.queue(a_scoring_report(["stability"]))
    results = run_scores(db, provider, [app], new_report, settings)

    assert len(provider.calls) == 2  # exactly one more call
    # That call's prompt contained only the uncached dimension.
    last_prompt = provider.calls[-1].prompt
    assert "stability" in last_prompt.lower()
    assert "community" not in last_prompt.lower()  # reused, not re-sent
    # The assembled report still covers both current dimensions (cached + fresh).
    assert {s.dimension_key for s in results[0].outcome.output.scores} == {
        "community", "stability"
    }


def test_fully_cached_candidate_makes_no_call() -> None:
    db = make_db()
    app = add_eligible(db, email="a@x.com", raw_hash="h1")
    settings = AppSettings()
    provider = MockProvider()
    keys = ["community", "skills"]
    report = report_with(keys)

    provider.queue(a_scoring_report(keys))
    run_scores(db, provider, [app], report, settings)
    calls_after_first = len(provider.calls)

    # Same keys, same applicant content → every dimension is cached.
    results = run_scores(db, provider, [app], report, settings)
    assert len(provider.calls) == calls_after_first  # no new call
    assert results[0].outcome.cached is True
    assert results[0].outcome.cost_usd == 0.0


def test_batched_call_tokens_are_split_across_dimensions() -> None:
    db = make_db()
    app = add_eligible(db, email="a@x.com", raw_hash="h1")
    settings = AppSettings()
    provider = MockProvider()
    keys = ["community", "skills", "stability"]  # 3 dims in one call
    report = report_with(keys)

    provider.queue(a_scoring_report(keys), input_tokens=900, output_tokens=300)
    run_scores(db, provider, [app], report, settings)

    rows = db.scalars(select(ApplicationAIResult)).all()
    assert len(rows) == 3
    # 900 / 3 and 300 / 3 — each row carries its even share, summing back to total.
    assert all(r.input_tokens == 300 and r.output_tokens == 100 for r in rows)
    assert sum(r.input_tokens for r in rows) == 900
    assert sum(r.output_tokens for r in rows) == 300


def test_omitted_dimension_is_re_asked_then_completes() -> None:
    # A response missing a requested dimension triggers a TARGETED re-ask for just the
    # missing one; once the model returns it, the candidate is fully scored (a row per
    # dimension) rather than storing a silent 0.0 placeholder.
    db = make_db()
    app = add_eligible(db, email="a@x.com", raw_hash="h1")
    settings = AppSettings()
    provider = MockProvider()
    keys = ["community", "skills"]
    report = report_with(keys)

    # Call 1 omits "skills"; the retry (for only the missing dim) returns it.
    provider.queue(a_scoring_report(["community"]))
    provider.queue(a_scoring_report(["skills"]))
    results = run_scores(db, provider, [app], report, settings)

    assert not results[0].failed
    scores = {s.dimension_key: s for s in results[0].outcome.output.scores}
    assert set(scores) == {"community", "skills"}
    assert scores["skills"].score == 0.7  # real score from the retry, not a placeholder
    # Both dimensions persisted a real cache row (coverage would read complete).
    rows = db.scalars(select(ApplicationAIResult)).all()
    assert {r.kind for r in rows} == {kind_for_dimension("community"), kind_for_dimension("skills")}
    # The retry re-asked ONLY the missing dimension, not the whole batch.
    assert "community" not in provider.calls[-1].prompt.lower()
    assert "skills" in provider.calls[-1].prompt.lower()


def test_persistently_omitted_dimension_fails_the_candidate_loudly() -> None:
    # If the model keeps omitting a dimension across all retries, the candidate FAILS
    # (surfaced as a PassResult error) rather than being silently stored partial — the
    # hole that let a candidate read 24/25 forever.
    from app.ai.dimension_scoring import MAX_SCORING_RETRIES

    db = make_db()
    app = add_eligible(db, email="a@x.com", raw_hash="h1")
    settings = AppSettings()
    provider = MockProvider()
    report = report_with(["community", "skills"])

    # Every attempt (initial + all retries) omits "skills".
    for _ in range(MAX_SCORING_RETRIES + 1):
        provider.queue(a_scoring_report(["community"]))
    results = run_scores(db, provider, [app], report, settings)

    assert results[0].failed
    assert "skills" in results[0].error
    # Nothing partial persisted for this candidate.
    assert db.scalars(select(ApplicationAIResult)).all() == []


def test_ceiling_estimate_prices_per_candidate_call() -> None:
    # The pre-discovery estimate models one scoring CALL per candidate: a per-call
    # input (shared facts+essays, the fallback constant before a prompt exists) plus
    # per-dimension output × the assumed dimension count. Input is not charged per dimension.
    from app.ai.dimension_scoring_cost import (
        ASSUMED_DIMENSIONS_FIRST_RUN,
        SCORING_FALLBACK_INPUT_TOKENS_PER_CANDIDATE,
        SCORING_FALLBACK_OUTPUT_TOKENS,
        estimate_rank_scoring,
    )
    from app.ai.pricing import cost_usd
    from app.ai.provider import Usage

    db = make_db()
    add_eligible(db, email="a@x.com", raw_hash="h1")
    add_eligible(db, email="b@x.com", raw_hash="h2")
    settings = AppSettings()

    # No run yet → fallback per-candidate input + per-dimension output × the
    # first-run dimension count; ceiling assumes nothing cached.
    est = estimate_rank_scoring(db, current_opening_id(db), settings,
        candidates=applications_to_score(db, current_opening_id(db)))
    per_candidate = cost_usd(
        settings.ai.dimension_scoring_model,
        Usage(
            SCORING_FALLBACK_INPUT_TOKENS_PER_CANDIDATE,
            SCORING_FALLBACK_OUTPUT_TOKENS * ASSUMED_DIMENSIONS_FIRST_RUN,
        ),
    )
    expected = round(per_candidate * 2, 4)
    assert est == expected


def test_rerun_estimate_cache_aware_fallback_when_no_history() -> None:
    # Without ledger history, the estimate still respects current cache coverage.
    from app.ai.dimension_scoring_cost import (
        ASSUMED_DIMENSIONS_FIRST_RUN,
        _avg_output_tokens_per_dimension,
        _per_candidate_input_tokens,
        estimate_rank_scoring,
    )
    from app.ai.pricing import cost_usd
    from app.ai.provider import Usage
    from app.services.ranking.analysis import create_analysis

    db = make_db()
    app1 = add_eligible(db, email="a@x.com", raw_hash="h1")
    app2 = add_eligible(db, email="b@x.com", raw_hash="h2")
    settings = AppSettings()
    keys = ["community", "skills", "participation"]
    report = report_with(keys)

    create_analysis(
        db, user=db.scalar(select(User)), opening_id=current_opening_id(db),
        report=report, inputs_fingerprint=rank_inputs_fingerprint(db, current_opening_id(db), settings),
        narrative=None,
    )
    provider = MockProvider()
    provider.queue(a_scoring_report(keys))
    provider.queue(a_scoring_report(keys))
    run_scores(db, provider, [app1, app2], report, settings)
    # NOTE: run_scores does not write a RunCostLedger row (that happens in the API
    # stream), so recent_scoring_fresh_usd() is None here → cache-aware fallback.

    est = estimate_rank_scoring(db, current_opening_id(db), settings,
        candidates=applications_to_score(db, current_opening_id(db)))

    # Everyone fully cached against the current dims → 0 uncached work → $0 estimate.
    assert est == 0.0
    # A whole-pool, no-cache ceiling would be strictly higher.
    out_per_dim = _avg_output_tokens_per_dimension(db, settings.ai.dimension_scoring_model)
    inp = _per_candidate_input_tokens([app1, app2], report)
    ceiling = cost_usd(
        settings.ai.dimension_scoring_model,
        Usage(inp, out_per_dim * ASSUMED_DIMENSIONS_FIRST_RUN),
    ) * 2
    assert est < ceiling


def test_full_rank_estimate_reuses_the_supplied_pool() -> None:
    from app.ai.dimension_scoring_cost import estimate_rank_scoring
    from app.services.ranking.analysis import create_analysis

    db = make_db()
    application = add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    create_analysis(db, user=db.scalar(select(User)), opening_id=current_opening_id(db),
        report=report_with(["community"]), inputs_fingerprint="synthetic", narrative=None)
    # The route supplies a loaded pool, not expired ORM attributes.
    db.refresh(application)
    statements = []

    @event.listens_for(db.get_bind(), "before_cursor_execute")
    def record_query(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    estimated = estimate_rank_scoring(db, current_opening_id(db), AppSettings(),
        candidates=[application])
    assert estimated > 0
    assert not any("FROM applications" in statement for statement in statements)
    assert not any("FROM member_rules" in statement for statement in statements)


def test_rerun_estimate_prefers_measured_history() -> None:
    # When prior Rank runs recorded actual fresh scoring spend, the estimate uses a
    # recency-weighted average of that measured cost — the honest predictor — rather
    # than a reconstructed count.
    from app.ai.dimension_scoring_cost import estimate_rank_scoring
    from app.ai.pricing import PassCost
    from app.services.cost_report import record_run_cost
    from app.services.ranking.analysis import create_analysis

    db = make_db()
    add_eligible(db, email="a@x.com", raw_hash="h1")
    settings = AppSettings()
    report = report_with(["community", "skills"])
    create_analysis(
        db, user=db.scalar(select(User)), opening_id=current_opening_id(db),
        report=report, inputs_fingerprint=rank_inputs_fingerprint(db, current_opening_id(db), settings),
        narrative=None,
    )

    def rank_row(scoring_fresh: float) -> None:
        record_run_cost(db, kind="rank", opening_id=current_opening_id(db), passes={
            "Dimension scoring": PassCost(calls=1, cost_usd=scoring_fresh),
        })

    # Two recorded runs: older $0.40, newer $0.10. Recency weights (2×newer + 1×older)
    # / 3 = (2*0.10 + 1*0.40)/3 = 0.20.
    rank_row(0.40)
    rank_row(0.10)

    est = estimate_rank_scoring(db, current_opening_id(db), settings,
        candidates=applications_to_score(db, current_opening_id(db)))
    assert est == round((2 * 0.10 + 1 * 0.40) / 3, 4)


def test_estimate_is_recorded_and_surfaced_for_reconciliation() -> None:
    # The ledger retains both the estimate and actual spend for reconciliation.
    from app.ai.pricing import PassCost
    from app.services.cost_report import last_runs_report, record_run_cost

    db = make_db()
    record_run_cost(
        db, kind="rank",
        passes={"Dimension scoring": PassCost(calls=1, cost_usd=0.12)},
        estimated_usd=0.30,  # ceiling estimate; actual came in under it
    )

    rank = last_runs_report(db).rank
    assert rank is not None
    assert rank.estimated_usd == 0.30
    assert rank.fresh_usd == 0.12  # actual under the ceiling — the healthy case


def test_estimate_defaults_to_zero_when_not_provided() -> None:
    # A record without an estimate reports 0.0, which the UI renders as "—".
    from app.ai.pricing import PassCost
    from app.services.cost_report import last_runs_report, record_run_cost

    db = make_db()
    record_run_cost(db, kind="screen", passes={"Screening": PassCost(calls=1, cost_usd=0.05)})

    assert last_runs_report(db).screen.estimated_usd == 0.0


def test_triggering_member_is_recorded_and_surfaced() -> None:
    # Shared run spend is attributed to the member who started it.
    from app.ai.pricing import PassCost
    from app.services.cost_report import last_runs_report, record_run_cost

    db = make_db()
    member = db.scalar(select(User))
    record_run_cost(
        db, kind="rank",
        passes={"Dimension scoring": PassCost(calls=1, cost_usd=0.12)},
        triggered_by_user_id=member.id,
    )

    assert last_runs_report(db).rank.triggered_by == "m@x.com"


def test_triggering_member_is_none_when_unattributed() -> None:
    # Pre-Phase-4 rows (and any run recorded without a user) report None — the UI omits
    # the stamp rather than showing a placeholder.
    from app.ai.pricing import PassCost
    from app.services.cost_report import last_runs_report, record_run_cost

    db = make_db()
    record_run_cost(db, kind="screen", passes={"Screening": PassCost(calls=1, cost_usd=0.05)})

    assert last_runs_report(db).screen.triggered_by is None


def test_run_cost_survives_a_removed_triggering_member() -> None:
    # A run's cost history must OUTLIVE the member who triggered it (no cascade delete):
    # the ledger row stays, the stamp just reads blank.
    from app.ai.pricing import PassCost
    from app.db.models import RunCostLedger
    from app.services.cost_report import last_runs_report, record_run_cost

    db = make_db()
    member = db.scalar(select(User))
    record_run_cost(
        db, kind="rank",
        passes={"Dimension scoring": PassCost(calls=1, cost_usd=0.12)},
        triggered_by_user_id=member.id,
    )
    db.delete(member)
    db.commit()

    rank = last_runs_report(db).rank
    assert rank is not None  # run survived the member's removal
    assert rank.fresh_usd == 0.12
    assert rank.triggered_by is None  # stamp reads blank
    assert db.scalar(select(RunCostLedger)) is not None
