import threading

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai.mock_provider import MockProvider
from app.ai.provider import AIResult, Usage
from app.ai.schemas import FlagCategory, ScreeningFlag, ScreeningReport
from app.ai.screening import (
    applications_for_screening,
    build_prompt,
    estimate_screening,
    run_screening,
)
from app.db.models import Application, Base
from app.schemas.settings import AppSettings


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def add_application(
    db: Session,
    *,
    email: str,
    raw_hash: str,
    rules_ineligible: bool = False,
    raw_row: dict | None = None,
    normalized: dict | None = None,
) -> Application:
    """An applicant on the machine baseline. Reasons are no longer stored — they are
    computed on read from ``normalized`` + the committee-default ruleset, so a
    rules-ineligible applicant is one whose ``normalized`` trips a hard filter (here,
    owning real estate); everything else is machine-eligible."""
    normalized = dict(normalized or {})
    if rules_ineligible:
        normalized["has_real_estate"] = True
    app = Application(
        primary_email=email,
        applicant_name="Test Applicant",
        raw_row=raw_row or {},
        raw_row_hash=raw_hash,
        normalized=normalized,
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
    """Every application the rules did NOT disqualify is analyzed — screening recomputes
    the AI flags that feed the shared machine baseline, so it screens whether or not any
    member later overrode the verdict. Only rules-ineligible apps (a hard-filter reason
    present) are excluded: their verdict is deterministic, so no AI pass could change it.
    """
    db = make_session()
    add_application(db, email="clean@x.com", raw_hash="h1")
    add_application(db, email="clean-2@x.com", raw_hash="h2")
    add_application(db, email="rules-no@x.com", raw_hash="h3", rules_ineligible=True)

    emails = {a.primary_email for a in applications_for_screening(db)}
    assert emails == {"clean@x.com", "clean-2@x.com"}


def test_forced_eligible_override_is_screened_despite_rules() -> None:
    """A rules-ineligible applicant a member forced ELIGIBLE is still screened. Overriding
    pulls them into that member's active review pool, where the AI's flags/pet inventory/
    reasoning matter most — the override fixes the verdict, but the reviewer still wants the
    evidence behind the application. So it re-enters scope even though the rules reject it."""
    from app.db.models import ApplicationStatus, MemberEligibility, User, UserRole

    db = make_session()
    forced = add_application(db, email="rules-no@x.com", raw_hash="h1", rules_ineligible=True)
    # A second rules-ineligible applicant with NO override stays excluded (control).
    add_application(db, email="still-out@x.com", raw_hash="h2", rules_ineligible=True)

    user = User(email="m@x.com", display_name="M", role=UserRole.MEMBER, is_active=True)
    db.add(user)
    db.commit()
    db.add(MemberEligibility(
        user_id=user.id, application_id=forced.id, status=ApplicationStatus.ELIGIBLE,
    ))
    db.commit()

    emails = {a.primary_email for a in applications_for_screening(db)}
    assert emails == {"rules-no@x.com"}  # forced-eligible in; un-overridden rules-out stays out


def test_build_prompt_surfaces_pets_and_essays_and_asks_for_extraction() -> None:
    # M15 1e: the prompt no longer cites a pet POLICY (no threshold interpolated); it
    # surfaces the free-text pets field and asks the model to EXTRACT a neutral inventory.
    db = make_session()
    app = add_application(
        db,
        email="a@x.com",
        raw_hash="h1",
        raw_row={
            "If you have any pets, please describe them here.": "Two dogs and a cat",
            "Please introduce yourself and your family, including your employment background, interests, and values.": "We are a family.",
        },
        normalized={"pets_text": "Two dogs and a cat", "applicant_name": "Avery"},
    )

    prompt = build_prompt(app)

    assert "Two dogs and a cat" in prompt  # pets text surfaced for extraction
    assert "We are a family." in prompt  # essay surfaced
    assert "How to extract pets" in prompt  # instructs neutral extraction
    # The prompt must NOT cite a threshold or ask the model to judge policy (that moved to
    # the deterministic per-member hard filter).
    assert "at most 1 dog" not in prompt
    assert "only dogs and cats are allowed" not in prompt


def test_screening_version_is_stable_and_settings_independent() -> None:
    # M15 1e: pets left the prompt for a deterministic per-member filter, so the version is
    # now a pure function of the prompt text — no settings argument, and a pet-limit change
    # (which is a hard-filter change, judged on read) no longer invalidates the cache.
    from app.ai.screening import screening_prompt_version

    assert screening_prompt_version() == screening_prompt_version()


def test_screening_runs_and_caches() -> None:
    db = make_session()
    app = add_application(db, email="a@x.com", raw_hash="h1")
    provider = MockProvider()
    provider.queue(flagged(), model_id=AppSettings().ai.screening_model)
    settings = AppSettings()

    first = list(run_screening(db, provider, applications=[app], settings=settings, max_workers=1))
    assert first[0].outcome.cached is False
    assert first[0].outcome.output.flags[0].category == FlagCategory.PLACEHOLDER_NAME

    # No second queued result: a real call would raise, so a hit proves caching.
    second = list(run_screening(db, provider, applications=[app], settings=settings, max_workers=1))
    assert second[0].outcome.cached is True
    assert len(provider.calls) == 1


def test_screen_isolates_a_failed_call() -> None:
    """A model call that raises yields a result with an error and does not abort
    the batch; the other applications are still screened and persisted.
    """
    db = make_session()
    good = add_application(
        db, email="good@x.com", raw_hash="h1",
        normalized={"applicant_name": "Good One"},
    )
    bad = add_application(
        db, email="bad@x.com", raw_hash="h2",
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
            db, email=f"a{i}@x.com",
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
    add_application(db, email="a@x.com", raw_hash="h1")
    add_application(db, email="b@x.com", raw_hash="h2")
    # No hard-filter reason: analyzed (a re-run may add or clear AI flags).
    add_application(db, email="c@x.com", raw_hash="h3")
    # Rules-ineligible (a hard filter trips on read): excluded, verdict is deterministic.
    add_application(db, email="d@x.com", raw_hash="h4", rules_ineligible=True)

    est = estimate_screening(db, AppSettings())
    assert est["total"] == 3
    assert est["to_analyze"] == 3
    assert est["estimated_usd"] >= 0
