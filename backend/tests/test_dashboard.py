import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import require_current_user
from app.db.models import (
    Analysis,
    Application,
    ApplicationAIResult,
    Base,
    User,
    UserRole,
)
from app.db.session import get_db
from app.main import create_app


@pytest.mark.anyio
async def test_dashboard_requires_login() -> None:
    transport = ASGITransport(app=create_app())

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/dashboard")

    assert response.status_code == 401


def _logged_in_app() -> tuple:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    user = User(email="m@x.com", display_name="M", role=UserRole.MEMBER, is_active=True)
    db.add(user)
    db.commit()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_current_user] = lambda: user
    return app, db


@pytest.mark.anyio
async def test_workflow_flags_track_progress() -> None:
    """The dashboard reports which screening steps have run, derived from
    persisted data so the ordered-workflow gating survives a reload.
    """
    app, db = _logged_in_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Nothing synced yet: every step is not-done.
        workflow = (await client.get("/dashboard")).json()["workflow"]
        assert workflow == {
            "synced": False,
            "importCurrent": True,
            "screened": False,
            "patternsDiscovered": False,
            "candidatesScored": False,
            "rankingCurrent": False,
        }

        # An application exists -> synced.
        application = Application(
            primary_email="a@x.com", applicant_name="A", raw_row={}, raw_row_hash="h1",
            normalized={}, hard_filter_reasons=[],
        )
        db.add(application)
        db.commit()
        workflow = (await client.get("/dashboard")).json()["workflow"]
        assert workflow["synced"] is True
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
    from app.services.analysis import rank_inputs_fingerprint

    app, db = _logged_in_app()
    settings = AppSettings()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        db.add(Application(
            primary_email="a@x.com", applicant_name="A", raw_row={}, raw_row_hash="h1",
            normalized={}, hard_filter_reasons=[],
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
            normalized={}, hard_filter_reasons=[],
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


@pytest.mark.anyio
async def test_import_current_tracks_settings_fingerprint() -> None:
    """importCurrent is False once the import-relevant settings change.

    A SyncRun stamped with the settings at import time stays "current" until the
    live settings diverge; then Import flags amber so the operator re-imports to
    reclassify eligibility.
    """
    from app.db.models import SyncRun
    from app.schemas.settings import AppSettings
    from app.services.application_import import settings_fingerprint
    from app.services.settings import save_app_settings

    app, db = _logged_in_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        settings = AppSettings(google_sheet_id="sheet-1", min_children=1)
        save_app_settings(db, settings)
        db.add(SyncRun(
            source_sheet_id="sheet-1",
            settings_fingerprint=settings_fingerprint(settings),
        ))
        db.commit()
        workflow = (await client.get("/dashboard")).json()["workflow"]
        assert workflow["importCurrent"] is True

        # Change a hard-filter setting -> the latest sync's fingerprint no longer
        # matches -> Import is out of date.
        save_app_settings(db, AppSettings(google_sheet_id="sheet-1", min_children=2))
        workflow = (await client.get("/dashboard")).json()["workflow"]
        assert workflow["importCurrent"] is False


@pytest.mark.anyio
async def test_import_current_ignores_non_filter_settings() -> None:
    """Changing settings that don't affect eligibility (pet limits, AI cap) must
    NOT flag Import amber — only hard-filter inputs do."""
    from app.db.models import SyncRun
    from app.schemas.settings import AppSettings
    from app.services.application_import import settings_fingerprint
    from app.services.settings import save_app_settings

    app, db = _logged_in_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        settings = AppSettings(google_sheet_id="sheet-1", max_dogs=1)
        save_app_settings(db, settings)
        db.add(SyncRun(
            source_sheet_id="sheet-1",
            settings_fingerprint=settings_fingerprint(settings),
        ))
        db.commit()

        # Bump a pet limit and the AI cap — neither is a hard filter.
        changed = AppSettings(google_sheet_id="sheet-1", max_dogs=3)
        changed.ai.spending_cap_usd = 5.0
        save_app_settings(db, changed)
        workflow = (await client.get("/dashboard")).json()["workflow"]
        assert workflow["importCurrent"] is True


@pytest.mark.anyio
async def test_coverage_distinguishes_current_from_stale() -> None:
    """Coverage counts how many in-scope candidates have a CURRENT cached result.

    A result stored against a different content hash (e.g. the row was re-synced
    after analysis) does not count — that is exactly the staleness the workflow
    UI must surface instead of showing a misleading done-check.
    """
    from app.ai.analysis import cache_key
    from app.ai.screening import KIND as SCREENING_KIND
    from app.ai.screening import screening_prompt_version
    from app.schemas.settings import AppSettings

    app, db = _logged_in_app()
    model = AppSettings().ai.screening_model
    # Dashboard coverage derives the screening version from settings (it folds in the
    # pet policy), so match that here or the current-content rows won't be counted.
    SCREENING_VERSION = screening_prompt_version(AppSettings())

    # Two eligible applicants in screening scope.
    a = Application(
        primary_email="a@x.com", applicant_name="A", raw_row={"q": "1"}, raw_row_hash="ha",
        normalized={}, hard_filter_reasons=[],
    )
    b = Application(
        primary_email="b@x.com", applicant_name="B", raw_row={"q": "2"}, raw_row_hash="hb",
        normalized={}, hard_filter_reasons=[],
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

    app, db = _logged_in_app()
    model = AppSettings().ai.dimension_scoring_model

    a = Application(
        primary_email="a@x.com", applicant_name="A", raw_row={"q": "1"}, raw_row_hash="ha",
        normalized={}, hard_filter_reasons=[],
    )
    db.add(a)
    # A run with two dimensions.
    db.add(Analysis(dimension_report={
        "summary": "s",
        "dimensions": [
            {"key": "community", "name": "Community", "definition": "d",
             "high_end": "hi", "low_end": "lo", "why_it_differentiates": "w"},
            {"key": "skills", "name": "Skills", "definition": "d",
             "high_end": "hi", "low_end": "lo", "why_it_differentiates": "w"},
        ],
    }))
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

