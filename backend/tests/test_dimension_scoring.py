"""Unit tests for milestone 7 passes: the dimensions-hash cache discipline and
the per-candidate scoring pass through the shared engine."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.dimension_scoring import (
    KIND_PREFIX,
    analyze_one,
    kind_for,
    screen_dimension_scores,
)
from app.ai.mock_provider import MockProvider
from app.ai.schemas import (
    DimensionScore,
    DimensionScoringReport,
    PoolDimension,
    PoolPatternReport,
    ScoreConfidence,
)
from app.db.models import Application, ApplicationStatus, Base
from app.schemas.settings import AppSettings
from app.services.screening_run import dimensions_hash


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


def test_dimensions_hash_is_order_independent_and_key_only() -> None:
    a = report_with(["community", "skills"])
    b = report_with(["skills", "community"])  # reordered
    assert dimensions_hash(a) == dimensions_hash(b)

    c = report_with(["community", "skills", "stability"])  # different set
    assert dimensions_hash(a) != dimensions_hash(c)


def test_kind_embeds_dimensions_hash() -> None:
    report = report_with(["community", "skills"])
    assert kind_for(report) == f"{KIND_PREFIX}:{dimensions_hash(report)}"


def test_different_dimension_sets_do_not_share_cache() -> None:
    db = make_db()
    application = add_eligible(db, email="a@x.com", raw_hash="h1")
    settings = AppSettings()
    provider = MockProvider()

    report_a = report_with(["community", "skills"])
    report_b = report_with(["community", "skills", "stability"])

    # First scoring under report_a calls the model and caches under its kind.
    provider.queue(a_scoring_report(["community", "skills"]))
    out_a = analyze_one(
        db, provider, application=application, report=report_a, settings=settings
    )
    assert out_a.cached is False
    assert len(provider.calls) == 1

    # Re-scoring under report_a hits the cache (no new call).
    out_a2 = analyze_one(
        db, provider, application=application, report=report_a, settings=settings
    )
    assert out_a2.cached is True
    assert len(provider.calls) == 1

    # A different dimension set must NOT reuse report_a's cached scores: it has a
    # distinct kind, so the engine makes a fresh call.
    provider.queue(a_scoring_report(["community", "skills", "stability"]))
    out_b = analyze_one(
        db, provider, application=application, report=report_b, settings=settings
    )
    assert out_b.cached is False
    assert len(provider.calls) == 2


def test_scoring_estimate_self_tunes_across_dimension_sets() -> None:
    # The bug: each Rank run gets a fresh dims_hash, so scoring's per-run kind
    # never accumulates usage and the estimate stayed pinned to the fallback
    # constant (which under-counted ~2.5x). The fix matches usage by the
    # "dimension_scoring:" prefix, so a NEW dimension set's estimate learns from
    # prior runs' real usage.
    from app.ai.dimension_scoring import (
        SCORING_FALLBACK_INPUT_TOKENS,
        SCORING_FALLBACK_OUTPUT_TOKENS,
        estimate_dimension_scoring,
        estimate_scoring_without_dimensions,
    )
    from app.ai.pricing import cost_usd
    from app.ai.provider import Usage

    db = make_db()
    application = add_eligible(db, email="a@x.com", raw_hash="h1")
    settings = AppSettings()
    provider = MockProvider()

    # Run scoring under set A, recording real usage with token counts deliberately
    # DIFFERENT from the fallback constants, so the estimate's value reveals which
    # source it used.
    observed_in, observed_out = 5000, 2500
    report_a = report_with(["community", "skills"])
    provider.queue(
        a_scoring_report(["community", "skills"]),
        # Echo the model the estimate filters on (the real provider does this; the
        # mock defaults to a placeholder id that wouldn't match the usage query).
        model_id=settings.ai.first_pass_model,
        input_tokens=observed_in,
        output_tokens=observed_out,
    )
    analyze_one(db, provider, application=application, report=report_a, settings=settings)

    # Estimate for a DIFFERENT set B (fresh dims_hash, zero cache rows of its own).
    # With the prefix match it prices one uncached candidate at set A's OBSERVED
    # tokens — not the fallback constant.
    report_b = report_with(["community", "skills", "stability"])
    est_b = estimate_dimension_scoring(db, report_b, settings)
    expected = round(
        cost_usd(settings.ai.first_pass_model, Usage(observed_in, observed_out)), 4
    )
    fallback = round(
        cost_usd(
            settings.ai.first_pass_model,
            Usage(SCORING_FALLBACK_INPUT_TOKENS, SCORING_FALLBACK_OUTPUT_TOKENS),
        ),
        4,
    )
    assert est_b["to_analyze"] == 1
    assert est_b["estimated_usd"] == expected
    assert est_b["estimated_usd"] != fallback  # proves it read observed, not the constant

    # The no-dimensions path (used by the combined Rank estimate before discovery)
    # self-tunes from the same prior usage rather than the blind constant.
    est_nodims = estimate_scoring_without_dimensions(db, settings)
    assert est_nodims["estimated_usd"] == expected


def test_screen_scores_all_eligible_and_does_not_touch_status() -> None:
    db = make_db()
    app1 = add_eligible(db, email="a@x.com", raw_hash="h1")
    app2 = add_eligible(db, email="b@x.com", raw_hash="h2")
    settings = AppSettings()
    provider = MockProvider()
    report = report_with(["community", "skills"])

    provider.queue(a_scoring_report(["community", "skills"]))
    provider.queue(a_scoring_report(["community", "skills"]))

    results = list(
        screen_dimension_scores(
            db,
            provider,
            applications=[app1, app2],
            report=report,
            settings=settings,
            max_workers=2,
        )
    )
    assert len(results) == 2
    assert all(not r.failed for r in results)
    # Informational: status untouched.
    db.refresh(app1)
    db.refresh(app2)
    assert app1.status == ApplicationStatus.ELIGIBLE
    assert app2.status == ApplicationStatus.ELIGIBLE
