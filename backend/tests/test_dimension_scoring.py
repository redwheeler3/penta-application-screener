"""Unit tests for per-dimension dimension scoring (M9 carry-forward Phase 4).

Scores are cached per (candidate, dimension key); a candidate's uncached
dimensions are sent to the model in one batched call, stored as per-key rows, and
merged with reused cached scores. These tests pin: per-key cache reuse, that only
uncached dimensions are sent, token splitting, the merge shape, and the
whole-pool ceiling estimate.
"""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.dimension_scoring import (
    KIND_PREFIX,
    kind_for_dimension,
    score_dimensions,
)
from app.ai.mock_provider import MockProvider
from app.ai.schemas import (
    DimensionScore,
    DimensionScoringReport,
    PoolDimension,
    PoolDimensionReport,
    ScoreConfidence,
)
from app.db.models import Application, ApplicationAIResult, ApplicationStatus, Base
from app.schemas.settings import AppSettings


def make_db() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def add_eligible(db: Session, *, email: str, raw_hash: str) -> Application:
    app = Application(
        primary_email=email,
        applicant_name="Test",
        raw_row={"Why a co-op": "We want community."},
        raw_row_hash=raw_hash,
        normalized={},
        status=ApplicationStatus.ELIGIBLE,
        hard_filter_reasons=[],
    )
    db.add(app)
    db.commit()
    return app


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


def test_kind_is_keyed_by_dimension_key() -> None:
    assert kind_for_dimension("community") == f"{KIND_PREFIX}:community"


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
    # Informational: status untouched.
    db.refresh(app1)
    assert app1.status == ApplicationStatus.ELIGIBLE


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
    # per-dimension output × the assumed dimension count. NOT a per-(candidate,
    # dimension) input cost — that was the carry-forward-skew bug.
    from app.ai.dimension_scoring_cost import (
        ASSUMED_DIMENSIONS_FIRST_RUN,
        SCORING_FALLBACK_INPUT_TOKENS_PER_CANDIDATE,
        SCORING_FALLBACK_OUTPUT_TOKENS,
        estimate_dimension_scoring,
    )
    from app.ai.pricing import cost_usd
    from app.ai.provider import Usage

    db = make_db()
    add_eligible(db, email="a@x.com", raw_hash="h1")
    add_eligible(db, email="b@x.com", raw_hash="h2")
    settings = AppSettings()

    # No run yet → fallback per-candidate input + per-dimension output × the
    # first-run dimension count; ceiling assumes nothing cached.
    est = estimate_dimension_scoring(db, settings)
    per_candidate = cost_usd(
        settings.ai.dimension_scoring_model,
        Usage(
            SCORING_FALLBACK_INPUT_TOKENS_PER_CANDIDATE,
            SCORING_FALLBACK_OUTPUT_TOKENS * ASSUMED_DIMENSIONS_FIRST_RUN,
        ),
    )
    expected = round(per_candidate * 2, 4)
    assert est["estimated_usd"] == expected
    assert est["to_analyze"] == 2  # candidates (the ceiling assumes none cached)


def test_rerun_estimate_cache_aware_fallback_when_no_history() -> None:
    # Regression for the cap-tripping bug. With a current run whose dimensions are all
    # cached but NO cost-ledger history yet, the estimate falls back to the cache-aware
    # count: fully-cached candidates cost 0, so it's far below the old whole-pool
    # ceiling (which priced every candidate × every dim as if nothing were cached).
    from app.ai.dimension_scoring_cost import (
        ASSUMED_DIMENSIONS_FIRST_RUN,
        _avg_output_tokens_per_dimension,
        _per_candidate_input_tokens,
        estimate_dimension_scoring,
    )
    from app.ai.pricing import cost_usd
    from app.ai.provider import Usage
    from app.services.ranking_run import create_run

    db = make_db()
    app1 = add_eligible(db, email="a@x.com", raw_hash="h1")
    app2 = add_eligible(db, email="b@x.com", raw_hash="h2")
    settings = AppSettings()
    keys = ["community", "skills", "participation"]
    report = report_with(keys)

    create_run(
        db, report=report, settings=settings,
        narrative=None,
    )
    provider = MockProvider()
    provider.queue(a_scoring_report(keys))
    provider.queue(a_scoring_report(keys))
    run_scores(db, provider, [app1, app2], report, settings)
    # NOTE: run_scores does not write a RunCostLedger row (that happens in the API
    # stream), so recent_scoring_fresh_usd() is None here → cache-aware fallback.

    est = estimate_dimension_scoring(db, settings)

    # Everyone fully cached against the current dims → 0 uncached work → $0 estimate.
    assert est["cached"] == 2
    assert est["to_analyze"] == 0
    assert est["estimated_usd"] == 0.0
    # And strictly below the old ceiling (every candidate × assumed dims, none cached).
    out_per_dim = _avg_output_tokens_per_dimension(db, settings.ai.dimension_scoring_model)
    inp = _per_candidate_input_tokens(db, report)
    ceiling = cost_usd(
        settings.ai.dimension_scoring_model,
        Usage(inp, out_per_dim * ASSUMED_DIMENSIONS_FIRST_RUN),
    ) * 2
    assert est["estimated_usd"] < ceiling


def test_rerun_estimate_prefers_measured_history() -> None:
    # When prior Rank runs recorded actual fresh scoring spend, the estimate uses a
    # recency-weighted average of that measured cost — the honest predictor — rather
    # than a reconstructed count.
    from app.ai.dimension_scoring_cost import estimate_dimension_scoring
    from app.ai.pricing import PassCost
    from app.services.cost_report import record_run_cost
    from app.services.ranking_run import create_run

    db = make_db()
    add_eligible(db, email="a@x.com", raw_hash="h1")
    settings = AppSettings()
    report = report_with(["community", "skills"])
    create_run(
        db, report=report, settings=settings,
        narrative=None,
    )

    def rank_row(scoring_fresh: float) -> None:
        record_run_cost(db, kind="rank", passes={
            "Dimension scoring": PassCost(calls=1, cost_usd=scoring_fresh),
        })

    # Two recorded runs: older $0.40, newer $0.10. Recency weights (2×newer + 1×older)
    # / 3 = (2*0.10 + 1*0.40)/3 = 0.20.
    rank_row(0.40)
    rank_row(0.10)

    est = estimate_dimension_scoring(db, settings)
    assert est["estimated_usd"] == round((2 * 0.10 + 1 * 0.40) / 3, 4)


def test_estimate_is_recorded_and_surfaced_for_reconciliation() -> None:
    # Pillar 1 reconciliation: the pre-run estimate passed to record_run_cost is stored on
    # the ledger and surfaces on the last-run report next to the actual fresh spend, so
    # estimate-vs-actual drift is visible after the fact.
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
    # A record without an estimate (or a pre-capture run) reports 0.0 — the UI renders "—".
    from app.ai.pricing import PassCost
    from app.services.cost_report import last_runs_report, record_run_cost

    db = make_db()
    record_run_cost(db, kind="screen", passes={"Screening": PassCost(calls=1, cost_usd=0.05)})

    assert last_runs_report(db).screen.estimated_usd == 0.0
