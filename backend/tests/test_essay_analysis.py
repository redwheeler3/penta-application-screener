from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai.essay_analysis import (
    analyze_one,
    applications_to_analyze,
    build_prompt,
    estimate_essay_analysis,
    screen_essays,
)
from app.ai.mock_provider import MockProvider
from app.ai.schemas import EssayAnalysisReport
from app.db.models import Application, ApplicationStatus, Base, StatusSource
from app.schemas.settings import AppSettings


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def add_application(
    db: Session,
    *,
    email: str,
    status: ApplicationStatus = ApplicationStatus.ELIGIBLE,
    status_source: StatusSource = StatusSource.UNTOUCHED,
    raw_hash: str = "h1",
    raw_row: dict | None = None,
) -> Application:
    app = Application(
        primary_email=email,
        applicant_name="Test Applicant",
        raw_row=raw_row or {},
        raw_row_hash=raw_hash,
        normalized={},
        status=status,
        status_source=status_source,
        hard_filter_reasons=[],
    )
    db.add(app)
    db.commit()
    return app


def report() -> EssayAnalysisReport:
    return EssayAnalysisReport(
        summary="A two-adult household new to co-op living.",
        skills_offered=["carpentry"],
        stated_motivations=["community"],
    )


# --- scope: eligible only ---

def test_applications_to_analyze_is_eligible_only() -> None:
    """Essay analysis is informational and cannot change status, so it only runs
    on the eligible pool — unlike quality flags, which use a broader scope.
    """
    db = make_session()
    add_application(db, email="eligible@x.com", status=ApplicationStatus.ELIGIBLE, raw_hash="h1")
    add_application(
        db, email="ai-no@x.com", status=ApplicationStatus.INELIGIBLE,
        status_source=StatusSource.AI, raw_hash="h2",
    )
    add_application(
        db, email="rules-no@x.com", status=ApplicationStatus.INELIGIBLE,
        status_source=StatusSource.RULES, raw_hash="h3",
    )
    add_application(
        db, email="human-no@x.com", status=ApplicationStatus.INELIGIBLE,
        status_source=StatusSource.HUMAN, raw_hash="h4",
    )

    emails = {a.primary_email for a in applications_to_analyze(db)}
    assert emails == {"eligible@x.com"}


def test_build_prompt_includes_essays() -> None:
    db = make_session()
    app = add_application(
        db, email="a@x.com",
        raw_row={
            "Please introduce yourself and your family, including your employment background, interests, and values.": "We are a family of two.",
            "Describe why you want to live in a co-op and in what ways you would be a valuable member to the co-op.": "We value community.",
        },
    )
    prompt = build_prompt(app)
    assert "We are a family of two." in prompt
    assert "We value community." in prompt


# --- status independence ---

def test_analyze_one_does_not_change_status() -> None:
    """The defining property of this pass: it never touches eligibility status."""
    db = make_session()
    app = add_application(db, email="a@x.com", status=ApplicationStatus.ELIGIBLE)
    provider = MockProvider()
    provider.queue(report(), model_id=AppSettings().ai.essay_analysis_model)

    outcome = analyze_one(db, provider, application=app, settings=AppSettings())

    assert outcome.cached is False
    assert isinstance(outcome.output, EssayAnalysisReport)
    # Status and source are untouched by the essay pass.
    assert app.status == ApplicationStatus.ELIGIBLE
    assert app.status_source == StatusSource.UNTOUCHED


def test_analyze_one_caches() -> None:
    db = make_session()
    app = add_application(db, email="a@x.com")
    provider = MockProvider()
    provider.queue(report(), model_id=AppSettings().ai.essay_analysis_model)
    settings = AppSettings()

    first = analyze_one(db, provider, application=app, settings=settings)
    assert first.cached is False

    # No second queued result: a real call would raise, so a hit proves caching.
    second = analyze_one(db, provider, application=app, settings=settings)
    assert second.cached is True
    assert len(provider.calls) == 1


# --- streaming / parallel screen ---

def test_screen_essays_yields_a_result_per_application() -> None:
    db = make_session()
    apps = [add_application(db, email=f"a{i}@x.com", raw_hash=f"h{i}") for i in range(3)]
    provider = MockProvider()
    for _ in apps:
        provider.queue(report(), model_id=AppSettings().ai.essay_analysis_model)

    results = list(
        screen_essays(
            db, provider, applications=apps, settings=AppSettings(), max_workers=4,
        )
    )
    assert len(results) == 3
    assert all(not r.failed for r in results)
    # No status was changed for any of them.
    assert all(a.status == ApplicationStatus.ELIGIBLE for a in apps)
    assert all(a.status_source == StatusSource.UNTOUCHED for a in apps)


def test_estimate_counts_eligible_only() -> None:
    db = make_session()
    add_application(db, email="a@x.com", status=ApplicationStatus.ELIGIBLE, raw_hash="h1")
    add_application(db, email="b@x.com", status=ApplicationStatus.ELIGIBLE, raw_hash="h2")
    add_application(
        db, email="c@x.com", status=ApplicationStatus.INELIGIBLE,
        status_source=StatusSource.AI, raw_hash="h3",
    )

    est = estimate_essay_analysis(db, AppSettings())
    assert est["total"] == 2
    assert est["to_analyze"] == 2
