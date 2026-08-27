from datetime import UTC, datetime, timedelta

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import require_current_user
from app.core.time import pacific_today
from app.db.models import (
    Analysis,
    Application,
    ApplicationAIResult,
    ApplicationParticipation,
    Base,
    EmailDelivery,
    EmailDeliveryState,
    Opening,
    PasswordlessIdentityKind,
    User,
    UserRole,
)
from app.db.session import get_db
from app.main import create_app

SUBMITTED_AT = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.anyio
async def test_dashboard_requires_login() -> None:
    transport = ASGITransport(app=create_app())

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/dashboard")

    assert response.status_code == 401


def _logged_in_app(role: UserRole = UserRole.MEMBER) -> tuple:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    user = User(email="m@x.com", display_name="M", role=role, is_active=True)
    db.add(user)
    db.commit()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_current_user] = lambda: user
    return app, db


@pytest.mark.anyio
async def test_admin_dashboard_reports_quota_blocked_email_queue() -> None:
    app, db = _logged_in_app(UserRole.ADMIN)
    application = Application(
        primary_email="applicant@example.com",
        raw_row={},
        raw_row_hash="synthetic",
        normalized={},
    )
    db.add(application)
    db.flush()
    db.add_all(
        [
            EmailDelivery(
                message_kind="applicant_magic_link",
                recipient_kind=PasswordlessIdentityKind.APPLICANT,
                application_id=application.id,
                state=EmailDeliveryState.QUEUED,
                retry_intent={"type": "magic_link"},
                quota_blocked=True,
                attempt_count=1,
                created_at=datetime(2026, 8, 24, 10, tzinfo=UTC),
                last_attempt_at=datetime(2026, 8, 24, 11, tzinfo=UTC),
            ),
            EmailDelivery(
                message_kind="application_confirmation",
                recipient_kind=PasswordlessIdentityKind.APPLICANT,
                application_id=application.id,
                state=EmailDeliveryState.QUEUED,
                retry_intent={"type": "application_confirmation"},
                quota_blocked=False,
                attempt_count=2,
                created_at=datetime(2026, 8, 25, 12, tzinfo=UTC),
                last_attempt_at=datetime(2026, 8, 26, 13, tzinfo=UTC),
            ),
        ]
    )
    db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/dashboard")

    actions = response.json()["adminActions"]
    assert actions["queuedEmailCount"] == 2
    assert actions["quotaBlockedEmailCount"] == 1
    assert actions["oldestQueuedEmailAt"] == "2026-08-24T10:00:00Z"
    assert actions["newestQueuedEmailAt"] == "2026-08-25T12:00:00Z"
    assert actions["lastEmailAttemptAt"] == "2026-08-26T13:00:00Z"


@pytest.mark.anyio
async def test_admin_dashboard_flags_archived_opening_without_selection() -> None:
    app, db = _logged_in_app(UserRole.ADMIN)
    today = pacific_today()
    opening = Opening(
        unit_size_bedrooms=2,
        housing_charge_cents=125_000,
        application_open_date=today - timedelta(days=30),
        application_close_date=today - timedelta(days=10),
        move_in_date=today,
        published_at=datetime.now(UTC),
    )
    application = Application(
        primary_email="candidate@example.com",
        raw_row={},
        raw_row_hash="candidate",
        normalized={},
        submitted_at=datetime.now(UTC),
    )
    db.add_all([opening, application])
    db.flush()
    db.add(
        ApplicationParticipation(
            application_id=application.id,
            opening_id=opening.id,
            applied_at=datetime.now(UTC),
        )
    )
    db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/dashboard")

    actions = response.json()["adminActions"]["archivedOpeningsNeedingSelection"]
    assert actions == [
        {
            "openingId": opening.id,
            "unitSizeBedrooms": 2,
            "moveInDate": today.isoformat(),
        }
    ]

    opening.no_household_selected_at = datetime.now(UTC)
    opening.no_household_selected_by_user_id = db.query(User).one().id
    db.commit()
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        finalized = await client.get("/dashboard")
    assert finalized.json()["adminActions"]["archivedOpeningsNeedingSelection"] == []


@pytest.mark.anyio
async def test_workflow_flags_track_progress() -> None:
    """The dashboard reports which screening steps have run, derived from
    persisted data so the ordered-workflow gating survives a reload.
    """
    app, db = _logged_in_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # No submitted applications yet: every action is not done.
        workflow = (await client.get("/dashboard")).json()["workflow"]
        assert workflow == {
            "applicationsAvailable": False,
            "screened": False,
            "patternsDiscovered": False,
            "candidatesScored": False,
            "rankingCurrent": False,
        }

        # Private drafts are deliberately invisible to the committee and cannot
        # make Screen available before an application has been submitted.
        db.add(
            Application(
                primary_email="draft@x.com",
                applicant_name="Draft",
                raw_row={},
                raw_row_hash="draft-hash",
                normalized={},
            )
        )
        db.commit()
        workflow = (await client.get("/dashboard")).json()["workflow"]
        assert workflow["applicationsAvailable"] is False

        # A submitted application makes screening available.
        application = Application(
            primary_email="a@x.com", applicant_name="A", raw_row={}, raw_row_hash="h1",
            normalized={},
            submitted_at=SUBMITTED_AT,
        )
        db.add(application)
        db.commit()
        workflow = (await client.get("/dashboard")).json()["workflow"]
        assert workflow["applicationsAvailable"] is True
        assert workflow["screened"] is False

        # A quality-flag result exists -> that step is done; essays still not.
        db.add(ApplicationAIResult(
            application_id=application.id, kind="screening", cache_key="k1",
            model_id="m", prompt_version="v1", output={"flags": []},
        ))
        db.commit()
        workflow = (await client.get("/dashboard")).json()["workflow"]
        assert workflow["screened"] is True
        assert workflow["patternsDiscovered"] is False
        assert workflow["candidatesScored"] is False

        # A screening run exists -> patterns discovered (it's a run, not a result).
        db.add(Analysis(dimension_report={"dimensions": [
            {"key": "community", "name": "Community", "definition": "d",
             "high_end": "hi", "low_end": "lo", "why_it_differentiates": "w"},
        ]}))
        db.commit()
        workflow = (await client.get("/dashboard")).json()["workflow"]
        assert workflow["patternsDiscovered"] is True
        assert workflow["candidatesScored"] is False

        # A dimension-scoring result (per-run prefixed kind) -> scoring done.
        db.add(ApplicationAIResult(
            application_id=application.id, kind="dimension_scoring:abc123", cache_key="k3",
            model_id="m", prompt_version="v1", output={"scores": []},
        ))
        db.commit()
        workflow = (await client.get("/dashboard")).json()["workflow"]
        assert workflow["candidatesScored"] is True


@pytest.mark.anyio
async def test_ranking_current_tracks_rank_inputs() -> None:
    """rankingCurrent follows the rank-inputs fingerprint until the committee
    completes score-only coverage for the retained criteria.

    A pool or prompt change is amber until the committee either discovers new criteria
    or has every eligible applicant scored against the existing set.
    """
    from app.schemas.settings import AppSettings
    from app.services.ranking.freshness import rank_inputs_fingerprint

    app, db = _logged_in_app()
    settings = AppSettings()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        db.add(Application(
            primary_email="a@x.com", applicant_name="A", raw_row={}, raw_row_hash="h1",
            normalized={},
            submitted_at=SUBMITTED_AT,
        ))
        db.commit()

        # A run whose fingerprint matches the current pool + prompts + models -> current.
        run = Analysis(
            dimension_report={},
            rank_inputs_fingerprint=rank_inputs_fingerprint(db, settings),
        )
        db.add(run)
        db.commit()
        workflow = (await client.get("/dashboard")).json()["workflow"]
        assert workflow["rankingCurrent"] is True

        # A new eligible applicant changes the pool -> ranking no longer current,
        # even though we added no scores and removed nothing.
        db.add(Application(
            primary_email="b@x.com", applicant_name="B", raw_row={}, raw_row_hash="h2",
            normalized={},
            submitted_at=SUBMITTED_AT,
        ))
        db.commit()
        workflow = (await client.get("/dashboard")).json()["workflow"]
        assert workflow["rankingCurrent"] is False

        # Restore the pool, then prove a rank-chain PROMPT change alone also flips it:
        # re-stamp the run as current, then perturb the stored fingerprint as if a
        # prompt had changed. The dashboard recomputes from live prompts -> mismatch.
        db.delete(db.get(Application, 2))
        db.commit()
        run.rank_inputs_fingerprint = rank_inputs_fingerprint(db, settings)
        db.add(run)
        db.commit()
        assert (await client.get("/dashboard")).json()["workflow"]["rankingCurrent"] is True
        run.rank_inputs_fingerprint = "stale-prompt-version"
        db.add(run)
        db.commit()
        workflow = (await client.get("/dashboard")).json()["workflow"]
        assert workflow["rankingCurrent"] is False


def test_rank_fingerprint_tracks_only_effective_reasoning() -> None:
    from app.schemas.settings import AppSettings
    from app.services.ranking.freshness import rank_inputs_fingerprint

    _app, db = _logged_in_app()
    settings = AppSettings()
    anthropic = rank_inputs_fingerprint(db, settings)
    settings.ai.discovery_reasoning_effort = "medium"
    assert rank_inputs_fingerprint(db, settings) == anthropic

    settings.ai.discovery_model = "openai.gpt-5.6-terra"
    low = rank_inputs_fingerprint(db, settings)
    settings.ai.discovery_reasoning_effort = "high"
    assert rank_inputs_fingerprint(db, settings) != low


def test_rank_fingerprint_can_reuse_an_already_loaded_pool() -> None:
    from app.schemas.settings import AppSettings
    from app.services.ranking.freshness import rank_inputs_fingerprint

    _app, db = _logged_in_app()
    db.add_all([
        Application(
            primary_email="a@x.com", applicant_name="A", raw_row={},
            raw_row_hash="h1", normalized={},
            submitted_at=SUBMITTED_AT,
        ),
        Application(
            primary_email="b@x.com", applicant_name="B", raw_row={},
            raw_row_hash="h2", normalized={},
            submitted_at=SUBMITTED_AT,
        ),
    ])
    db.commit()
    settings = AppSettings()
    expected = rank_inputs_fingerprint(db, settings)
    applications = list(db.scalars(select(Application).order_by(Application.id.desc())))

    # Caller-provided order is irrelevant, and avoids recomputing eligibility.
    assert rank_inputs_fingerprint(db, settings, applications=applications) == expected


def test_rank_fingerprint_ignores_provider_but_tracks_the_actual_model() -> None:
    from app.ai.model_catalog import MODEL_IDS_BY_ROUTE
    from app.schemas.settings import AppSettings
    from app.services.ranking.freshness import rank_inputs_fingerprint

    _app, db = _logged_in_app()
    settings = AppSettings()
    bedrock = rank_inputs_fingerprint(db, settings)

    settings.ai.discovery_model = MODEL_IDS_BY_ROUTE["direct"]["sonnet"]
    settings.ai.decompose_model = MODEL_IDS_BY_ROUTE["direct"]["sonnet"]
    settings.ai.match_model = MODEL_IDS_BY_ROUTE["direct"]["sonnet"]
    settings.ai.dimension_scoring_model = MODEL_IDS_BY_ROUTE["direct"]["haiku"]
    settings.ai.consolidate_model = MODEL_IDS_BY_ROUTE["direct"]["sonnet"]
    assert rank_inputs_fingerprint(db, settings) == bedrock

    settings.ai.discovery_model = MODEL_IDS_BY_ROUTE["direct"]["terra"]
    assert rank_inputs_fingerprint(db, settings) != bedrock


@pytest.mark.anyio
async def test_coverage_distinguishes_current_from_stale() -> None:
    """Coverage counts how many in-scope candidates have a CURRENT cached result.

    A result stored against a different content hash (e.g. the applicant submitted an edit
    after analysis) does not count — that is exactly the staleness the workflow
    UI must surface instead of showing a misleading done-check.
    """
    from app.ai.analysis import cache_key
    from app.ai.screening import KIND as SCREENING_KIND
    from app.ai.screening import screening_prompt_version
    from app.schemas.settings import AppSettings

    app, db = _logged_in_app()
    model = AppSettings().ai.screening_model
    # Dashboard coverage derives the screening version from the prompt text alone (M15 1e:
    # pets left the prompt), so match that here or the current-content rows won't be counted.
    SCREENING_VERSION = screening_prompt_version()

    # Two eligible applicants in screening scope.
    a = Application(
        primary_email="a@x.com", applicant_name="A", raw_row={"q": "1"}, raw_row_hash="ha",
        normalized={},
        submitted_at=SUBMITTED_AT,
    )
    b = Application(
        primary_email="b@x.com", applicant_name="B", raw_row={"q": "2"}, raw_row_hash="hb",
        normalized={},
        submitted_at=SUBMITTED_AT,
    )
    db.add_all([a, b])
    db.commit()

    # a: current result (cache key computed from its present content + model).
    db.add(ApplicationAIResult(
        application_id=a.id, kind=SCREENING_KIND,
        cache_key=cache_key(application=a, kind=SCREENING_KIND, model_id=model, prompt_version=SCREENING_VERSION),
        model_id=model, prompt_version=SCREENING_VERSION, output={"flags": []},
    ))
    # b: a result keyed to OLD content -> does not match its current hash -> stale.
    db.add(ApplicationAIResult(
        application_id=b.id, kind=SCREENING_KIND, cache_key="stale-key",
        model_id=model, prompt_version=SCREENING_VERSION, output={"flags": []},
    ))
    db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        coverage = (await client.get("/dashboard")).json()["coverage"]

    # 2 in scope, only a is current.
    assert coverage["screened"] == {"cached": 1, "inScope": 2}
    # No screening run yet -> scoring coverage is absent, not zero.
    assert "candidatesScored" not in coverage


@pytest.mark.anyio
async def test_scoring_coverage_requires_every_dimension_key() -> None:
    """A candidate counts as scored only when it has a cached row for EVERY
    dimension key. Scores live per (candidate, dimension) now, so a candidate
    scored on some dimensions but not all (e.g. mid carry-forward) must read as
    not-yet-complete, not done."""
    from app.ai.analysis import cache_key
    from app.ai.dimension_scoring import PROMPT_VERSION as SCORING_VERSION
    from app.ai.dimension_scoring import kind_for_dimension
    from app.schemas.settings import AppSettings
    from app.services.ranking.freshness import rank_inputs_fingerprint

    app, db = _logged_in_app()
    settings = AppSettings()
    model = settings.ai.dimension_scoring_model

    a = Application(
        primary_email="a@x.com", applicant_name="A", raw_row={"q": "1"}, raw_row_hash="ha",
        normalized={},
        submitted_at=SUBMITTED_AT,
    )
    db.add(a)
    db.commit()
    # A run with two dimensions.
    db.add(Analysis(dimension_report={
        "summary": "s",
        "dimensions": [
            {"key": "community", "name": "Community", "definition": "d",
             "high_end": "hi", "low_end": "lo", "why_it_differentiates": "w"},
            {"key": "skills", "name": "Skills", "definition": "d",
             "high_end": "hi", "low_end": "lo", "why_it_differentiates": "w"},
        ],
    }, rank_inputs_fingerprint=rank_inputs_fingerprint(db, settings)))
    db.commit()

    # Score only ONE of the two dimensions -> incomplete.
    db.add(ApplicationAIResult(
        application_id=a.id, kind=kind_for_dimension("community"),
        cache_key=cache_key(application=a, kind=kind_for_dimension("community"), model_id=model, prompt_version=SCORING_VERSION),
        model_id=model, prompt_version=SCORING_VERSION, output={"score": 0.7, "confidence": "high", "rationale": "", "evidence": "", "dimension_key": "community"},
    ))
    db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        dashboard = (await client.get("/dashboard")).json()
    coverage = dashboard["coverage"]
    assert coverage["candidatesScored"] == {"cached": 0, "inScope": 1}  # partial = not done
    assert dashboard["workflow"]["rankingCurrent"] is False

    # Score the second dimension too -> complete.
    db.add(ApplicationAIResult(
        application_id=a.id, kind=kind_for_dimension("skills"),
        cache_key=cache_key(application=a, kind=kind_for_dimension("skills"), model_id=model, prompt_version=SCORING_VERSION),
        model_id=model, prompt_version=SCORING_VERSION, output={"score": 0.5, "confidence": "low", "rationale": "", "evidence": "", "dimension_key": "skills"},
    ))
    db.commit()

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        dashboard = (await client.get("/dashboard")).json()
    coverage = dashboard["coverage"]
    assert coverage["candidatesScored"] == {"cached": 1, "inScope": 1}
    assert dashboard["workflow"]["rankingCurrent"] is True

