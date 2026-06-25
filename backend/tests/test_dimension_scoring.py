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
    PoolPatternReport,
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


def report_with(keys: list[str]) -> PoolPatternReport:
    return PoolPatternReport(
        summary="A pool.",
        dimensions=[
            PoolDimension(
                key=k,
                name=k.replace("_", " ").title(),
                definition="def",
                why_it_differentiates="why",
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

    assert len(results) == 1 and not results[0].failed
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


def test_assembled_report_fills_omitted_dimension_with_placeholder() -> None:
    db = make_db()
    app = add_eligible(db, email="a@x.com", raw_hash="h1")
    settings = AppSettings()
    provider = MockProvider()
    keys = ["community", "skills"]
    report = report_with(keys)

    # Model returns only one of the two requested dimensions.
    provider.queue(a_scoring_report(["community"]))
    results = run_scores(db, provider, [app], report, settings)

    scores = {s.dimension_key: s for s in results[0].outcome.output.scores}
    assert set(scores) == {"community", "skills"}  # shape stays complete
    assert scores["skills"].score == 0.0  # placeholder for the omitted one


def test_ceiling_estimate_prices_whole_pool_times_dimensions() -> None:
    from app.ai.dimension_scoring import (
        SCORING_FALLBACK_INPUT_TOKENS,
        SCORING_FALLBACK_OUTPUT_TOKENS,
        estimate_dimension_scoring,
    )
    from app.ai.pricing import cost_usd
    from app.ai.provider import Usage

    db = make_db()
    add_eligible(db, email="a@x.com", raw_hash="h1")
    add_eligible(db, email="b@x.com", raw_hash="h2")
    settings = AppSettings()

    # No run yet → assumes the first-run dimension count; ceiling assumes nothing
    # cached, so it prices every (candidate × dimension) pair at the fallback.
    est = estimate_dimension_scoring(db, settings)
    from app.ai.dimension_scoring import ASSUMED_DIMENSIONS_FIRST_RUN

    per_dim = cost_usd(
        settings.ai.first_pass_model,
        Usage(SCORING_FALLBACK_INPUT_TOKENS, SCORING_FALLBACK_OUTPUT_TOKENS),
    )
    expected = round(per_dim * 2 * ASSUMED_DIMENSIONS_FIRST_RUN, 4)
    assert est["estimated_usd"] == expected
    assert est["to_analyze"] == 2  # candidates (the ceiling assumes none cached)
