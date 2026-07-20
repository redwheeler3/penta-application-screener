import threading

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai.mock_provider import MockProvider
from app.ai.provider import AIResult, Usage
from app.ai.schemas import FlagCategory, ScreeningFlag, ScreeningReport
from app.ai.screening import (
    analyze_one,
    applications_for_screening,
    build_prompt,
    estimate_screening,
    run_screening,
)
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
    status: ApplicationStatus,
    raw_hash: str,
    status_source: StatusSource = StatusSource.UNTOUCHED,
    raw_row: dict | None = None,
    normalized: dict | None = None,
) -> Application:
    app = Application(
        primary_email=email,
        applicant_name="Test Applicant",
        raw_row=raw_row or {},
        raw_row_hash=raw_hash,
        normalized=normalized or {},
        status=status,
        status_source=status_source,
        hard_filter_reasons=[],
    )
    db.add(app)
    db.commit()
    return app


def clean() -> ScreeningReport:
    return ScreeningReport(flags=[])


def flagged() -> ScreeningReport:
    return ScreeningReport(
        flags=[
            ScreeningFlag(
                category=FlagCategory.PLACEHOLDER_NAME,
                summary="Child name looks like a placeholder.",
                evidence='Child: "Baby TBD"',
            )
        ]
    )


def test_applications_for_screening_scope() -> None:
    """Eligible and AI-ineligible apps are analyzed so a prompt change can revise
    the verdict either way; rules-ineligible apps are excluded (rules outrank AI).
    Human-owned statuses are included so their flags refresh for the staleness nudge.
    """
    db = make_session()
    add_application(db, email="eligible@x.com", status=ApplicationStatus.ELIGIBLE, raw_hash="h1")
    add_application(
        db,
        email="ai-no@x.com",
        status=ApplicationStatus.INELIGIBLE,
        status_source=StatusSource.AI,
        raw_hash="h2",
    )
    add_application(
        db,
        email="rules-no@x.com",
        status=ApplicationStatus.INELIGIBLE,
        status_source=StatusSource.RULES,
        raw_hash="h3",
    )
    add_application(
        db,
        email="human-no@x.com",
        status=ApplicationStatus.INELIGIBLE,
        status_source=StatusSource.HUMAN,
        raw_hash="h4",
    )

    emails = {a.primary_email for a in applications_for_screening(db)}
    assert emails == {"eligible@x.com", "ai-no@x.com", "human-no@x.com"}


def test_build_prompt_includes_essays_and_pet_policy() -> None:
    db = make_session()
    app = add_application(
        db,
        email="a@x.com",
        status=ApplicationStatus.ELIGIBLE,
        raw_hash="h1",
        raw_row={
            "If you have any pets, please describe them here.": "Two dogs and a cat",
            "Please introduce yourself and your family, including your employment background, interests, and values.": "We are a family.",
        },
        normalized={"pets_text": "Two dogs and a cat", "applicant_name": "Avery"},
    )
    settings = AppSettings()

    prompt = build_prompt(app, settings)

    assert "Two dogs and a cat" in prompt  # pets text surfaced
    assert "We are a family." in prompt  # essay surfaced
    assert "at most 1 dog(s)" in prompt  # pet policy from settings
    assert "only dogs and cats are allowed" in prompt


def test_screening_version_changes_with_pet_policy() -> None:
    # Regression: the pet-policy threshold is a judgment input (max 1 vs 2 cats flips a
    # 2-cat applicant), so it must be in the version → changing it misses the cache and
    # shows Screen out of date. Previously the version hashed only the template, so a
    # policy change silently reused stale results and reported "up to date".
    from app.ai.screening import screening_prompt_version

    one_cat = AppSettings()
    one_cat.max_cats = 1
    two_cats = AppSettings()
    two_cats.max_cats = 2

    assert screening_prompt_version(one_cat) != screening_prompt_version(two_cats)
    # Same settings → stable version (still a real cache when nothing changed).
    assert screening_prompt_version(one_cat) == screening_prompt_version(AppSettings())


def test_analyze_one_runs_and_caches() -> None:
    db = make_session()
    app = add_application(db, email="a@x.com", status=ApplicationStatus.ELIGIBLE, raw_hash="h1")
    provider = MockProvider()
    provider.queue(flagged(), model_id=AppSettings().ai.screening_model)
    settings = AppSettings()

    first = analyze_one(db, provider, application=app, settings=settings)
    assert first.cached is False
    assert first.output.flags[0].category == FlagCategory.PLACEHOLDER_NAME

    # No second queued result: a real call would raise, so a hit proves caching.
    second = analyze_one(db, provider, application=app, settings=settings)
    assert second.cached is True
    assert len(provider.calls) == 1


def test_screen_isolates_a_failed_call() -> None:
    """A model call that raises yields a result with an error and does not abort
    the batch; the other applications are still screened and persisted.
    """
    db = make_session()
    good = add_application(
        db, email="good@x.com", status=ApplicationStatus.ELIGIBLE, raw_hash="h1",
        normalized={"applicant_name": "Good One"},
    )
    bad = add_application(
        db, email="bad@x.com", status=ApplicationStatus.ELIGIBLE, raw_hash="h2",
        normalized={"applicant_name": "Bad One"},
    )

    class FlakyProvider:
        def structured_output(self, *, model_id, schema, prompt, system_prompt=None):
            if "Bad One" in prompt:
                raise RuntimeError("boom")
            return AIResult(
                output=ScreeningReport(flags=[]),
                usage=Usage(input_tokens=10, output_tokens=5),
                model_id=model_id,
            )

    results = list(
        run_screening(
            db, FlakyProvider(),
            applications=[good, bad], settings=AppSettings(), max_workers=4,
        )
    )
    by_email = {r.application.primary_email: r for r in results}
    assert by_email["good@x.com"].failed is False
    assert by_email["good@x.com"].error is None
    assert by_email["good@x.com"].error_type is None
    assert by_email["bad@x.com"].failed is True
    assert "boom" in by_email["bad@x.com"].error
    # The exception's class is preserved separately, so failure modes stay countable.
    assert by_email["bad@x.com"].error_type == "RuntimeError"


def test_screen_runs_calls_concurrently() -> None:
    """All workers are in the model call at once — proving real parallelism, not
    a sequential loop. Each call blocks on a barrier that only releases when the
    expected number of calls have arrived together.
    """
    n = 5
    db = make_session()
    apps = [
        add_application(
            db, email=f"a{i}@x.com", status=ApplicationStatus.ELIGIBLE,
            raw_hash=f"h{i}", normalized={"applicant_name": f"Person {i}"},
        )
        for i in range(n)
    ]
    barrier = threading.Barrier(n, timeout=5)

    class ConcurrentProvider:
        def structured_output(self, *, model_id, schema, prompt, system_prompt=None):
            # Raises BrokenBarrierError on timeout if fewer than n arrive — i.e.
            # if the calls were serialized rather than run together.
            barrier.wait()
            return AIResult(
                output=ScreeningReport(flags=[]),
                usage=Usage(input_tokens=10, output_tokens=5),
                model_id=model_id,
            )

    results = list(
        run_screening(
            db, ConcurrentProvider(),
            applications=apps, settings=AppSettings(), max_workers=n,
        )
    )
    assert len(results) == n
    assert all(not r.failed for r in results)


def test_estimate_counts_analyzable_excluding_rules_ineligible() -> None:
    db = make_session()
    add_application(db, email="a@x.com", status=ApplicationStatus.ELIGIBLE, raw_hash="h1")
    add_application(db, email="b@x.com", status=ApplicationStatus.ELIGIBLE, raw_hash="h2")
    # AI-ineligible: counted, so a prompt change can re-clear it.
    add_application(
        db,
        email="c@x.com",
        status=ApplicationStatus.INELIGIBLE,
        status_source=StatusSource.AI,
        raw_hash="h3",
    )
    # Rules-ineligible: excluded, rules outrank AI.
    add_application(
        db,
        email="d@x.com",
        status=ApplicationStatus.INELIGIBLE,
        status_source=StatusSource.RULES,
        raw_hash="h4",
    )

    est = estimate_screening(db, AppSettings())
    assert est["total"] == 3
    assert est["to_analyze"] == 3
    assert est["estimated_usd"] >= 0
