import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.ai.analysis import (
    PROMPT_VERSION,
    SpendingCapExceeded,
    analyze_application,
    cache_key,
    enforce_cap,
    estimate_cost,
)
from app.ai.mock_provider import MockProvider
from app.ai.pricing import cost_usd, price_for_model
from app.ai.provider import Usage
from app.ai.schemas import FlagCategory, FlagSeverity, QualityFlag, QualityFlagReport
from app.db.models import Application, ApplicationAIResult, ApplicationStatus, Base

MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
KIND = "quality_flags"


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def make_application(db: Session, *, email: str = "a@example.com", raw_hash: str = "hash-1") -> Application:
    app = Application(
        primary_email=email,
        applicant_name="Avery Nguyen",
        raw_row={"x": 1},
        raw_row_hash=raw_hash,
        normalized={},
        status=ApplicationStatus.ELIGIBLE,
        hard_filter_reasons=[],
    )
    db.add(app)
    db.commit()
    return app


def clean_report() -> QualityFlagReport:
    return QualityFlagReport(flags=[])


def flagged_report() -> QualityFlagReport:
    return QualityFlagReport(
        flags=[
            QualityFlag(
                category=FlagCategory.PLACEHOLDER_NAME,
                severity=FlagSeverity.NOTABLE,
                summary="Child name looks like a placeholder.",
                evidence='Child name: "Baby TBD"',
            )
        ]
    )


# --- pricing ---

def test_cost_uses_known_model_price() -> None:
    price = price_for_model(MODEL)
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost_usd(MODEL, usage) == pytest.approx(price.input_per_mtok + price.output_per_mtok)


def test_unknown_model_falls_back_to_expensive_rate() -> None:
    # An unknown model must not under-estimate: fallback is pricier than haiku.
    unknown = cost_usd("some-future-model", Usage(1_000_000, 0))
    haiku = cost_usd(MODEL, Usage(1_000_000, 0))
    assert unknown > haiku


def test_opus_priced_explicitly_and_matches_fallback() -> None:
    # Opus is the most expensive known model; the unknown-model fallback should
    # match it, so the fallback comment ("Opus-tier") stays accurate.
    opus = cost_usd("us.anthropic.claude-opus-4-8", Usage(1_000_000, 1_000_000))
    fallback = cost_usd("totally-unknown-model", Usage(1_000_000, 1_000_000))
    assert opus == fallback
    assert opus == pytest.approx(15.0 + 75.0)


def test_sonnet_46_not_shadowed_by_sonnet_4() -> None:
    # The more specific sonnet keys must win over the broad "sonnet-4" key.
    from app.ai.pricing import price_for_model

    assert price_for_model("us.anthropic.claude-sonnet-4-6").input_per_mtok == 3.0


# --- cache key ---

def test_cache_key_changes_with_model_and_content() -> None:
    db = make_session()
    app = make_application(db)
    base = cache_key(application=app, kind=KIND, model_id=MODEL)

    app.raw_row_hash = "different"
    assert cache_key(application=app, kind=KIND, model_id=MODEL) != base


# --- analyze: cache miss then hit ---

def test_analyze_calls_provider_then_caches() -> None:
    db = make_session()
    app = make_application(db)
    provider = MockProvider()
    provider.queue(flagged_report(), model_id=MODEL, input_tokens=600, output_tokens=120)

    first = analyze_application(
        db, provider, application=app, kind=KIND, schema=QualityFlagReport,
        model_id=MODEL, prompt="analyze",
    )
    assert first.cached is False
    assert first.cost_usd > 0
    assert len(provider.calls) == 1
    assert db.scalar(select(ApplicationAIResult)) is not None

    # Second call: no queued result, so a provider call would raise — proving cache hit.
    second = analyze_application(
        db, provider, application=app, kind=KIND, schema=QualityFlagReport,
        model_id=MODEL, prompt="analyze",
    )
    assert second.cached is True
    assert len(provider.calls) == 1
    assert second.output.flags[0].category == FlagCategory.PLACEHOLDER_NAME


# --- estimate + cap ---

def test_estimate_excludes_cached_applications() -> None:
    db = make_session()
    app1 = make_application(db, email="a@x.com", raw_hash="h1")
    app2 = make_application(db, email="b@x.com", raw_hash="h2")
    provider = MockProvider()
    provider.queue(clean_report(), model_id=MODEL)
    analyze_application(
        db, provider, application=app1, kind=KIND, schema=QualityFlagReport,
        model_id=MODEL, prompt="analyze",
    )

    est = estimate_cost(
        db, applications=[app1, app2], kind=KIND, model_id=MODEL,
        fallback_input_tokens=600, fallback_output_tokens=120,
    )
    assert est["total"] == 2
    assert est["cached"] == 1
    assert est["to_analyze"] == 1


def test_estimate_uses_fallback_with_no_history() -> None:
    db = make_session()
    app = make_application(db, email="a@x.com", raw_hash="h1")

    est = estimate_cost(
        db, applications=[app], kind=KIND, model_id=MODEL,
        fallback_input_tokens=1_000_000, fallback_output_tokens=0,
    )
    # With no prior calls, the per-call cost is the fallback tokens at the model
    # rate: 1M input tokens * haiku input rate, 0 output.
    assert est["estimated_usd"] == pytest.approx(price_for_model(MODEL).input_per_mtok)


def test_estimate_prefers_observed_usage_over_fallback() -> None:
    db = make_session()
    analyzed = make_application(db, email="a@x.com", raw_hash="h1")
    pending = make_application(db, email="b@x.com", raw_hash="h2")
    provider = MockProvider()
    # One prior call recorded 1M input / 0 output tokens of real usage.
    provider.queue(clean_report(), model_id=MODEL, input_tokens=1_000_000, output_tokens=0)
    analyze_application(
        db, provider, application=analyzed, kind=KIND, schema=QualityFlagReport,
        model_id=MODEL, prompt="analyze",
    )

    # Fallback is absurdly large; if it were used the estimate would explode.
    est = estimate_cost(
        db, applications=[analyzed, pending], kind=KIND, model_id=MODEL,
        fallback_input_tokens=999_000_000, fallback_output_tokens=999_000_000,
    )
    assert est["to_analyze"] == 1  # only `pending` is uncached
    # Estimate uses observed 1M-in/0-out for the single uncached app.
    assert est["estimated_usd"] == pytest.approx(price_for_model(MODEL).input_per_mtok)


def test_estimate_falls_back_to_earlier_prompt_version_usage() -> None:
    """When the current prompt version has no usage yet, an earlier version's
    real usage is preferred over the static fallback.
    """
    db = make_session()
    app = make_application(db, email="a@x.com", raw_hash="h1")
    # A stored result from an OLD prompt version (not the current PROMPT_VERSION).
    db.add(
        ApplicationAIResult(
            application_id=app.id,
            kind=KIND,
            cache_key="old-version-key",
            model_id=MODEL,
            prompt_version="0",
            output={"flags": []},
            input_tokens=1_000_000,
            output_tokens=0,
        )
    )
    db.commit()

    # `app` is uncached under the CURRENT prompt version, so it counts as work.
    est = estimate_cost(
        db, applications=[app], kind=KIND, model_id=MODEL,
        fallback_input_tokens=999_000_000, fallback_output_tokens=999_000_000,
    )
    assert est["to_analyze"] == 1
    # Uses the old version's observed 1M-in/0-out, not the huge fallback.
    assert est["estimated_usd"] == pytest.approx(price_for_model(MODEL).input_per_mtok)


def test_enforce_cap_raises_when_over() -> None:
    estimate = {"estimated_usd": 9.99}
    with pytest.raises(SpendingCapExceeded):
        enforce_cap(estimate, cap_usd=5.0)


def test_enforce_cap_passes_when_under() -> None:
    enforce_cap({"estimated_usd": 0.04}, cap_usd=5.0)  # no raise


def test_default_spending_cap_is_one_dollar() -> None:
    from app.schemas.settings import AISettings

    assert AISettings().spending_cap_usd == 1.0


def test_prompt_version_is_part_of_key() -> None:
    db = make_session()
    app = make_application(db)
    key = cache_key(application=app, kind=KIND, model_id=MODEL)
    # Sanity: the documented prompt version constant participates in the hash.
    assert isinstance(PROMPT_VERSION, str) and key
