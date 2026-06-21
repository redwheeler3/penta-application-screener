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
                default_weight=0.5,
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
