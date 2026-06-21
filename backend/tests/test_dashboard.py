import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import require_current_user
from app.db.models import (
    Application,
    ApplicationAIResult,
    ApplicationStatus,
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
        assert workflow == {"synced": False, "qualityChecksRun": False, "essaysAnalyzed": False}

        # An application exists -> synced.
        application = Application(
            primary_email="a@x.com", applicant_name="A", raw_row={}, raw_row_hash="h1",
            normalized={}, status=ApplicationStatus.ELIGIBLE, hard_filter_reasons=[],
        )
        db.add(application)
        db.commit()
        workflow = (await client.get("/dashboard")).json()["workflow"]
        assert workflow["synced"] is True
        assert workflow["qualityChecksRun"] is False

        # A quality-flag result exists -> that step is done; essays still not.
        db.add(ApplicationAIResult(
            application_id=application.id, kind="quality_flags", cache_key="k1",
            model_id="m", output={"flags": []},
        ))
        db.commit()
        workflow = (await client.get("/dashboard")).json()["workflow"]
        assert workflow["qualityChecksRun"] is True
        assert workflow["essaysAnalyzed"] is False

        # An essay-analysis result exists -> all three done.
        db.add(ApplicationAIResult(
            application_id=application.id, kind="essay_analysis", cache_key="k2",
            model_id="m", output={"summary": "x"},
        ))
        db.commit()
        workflow = (await client.get("/dashboard")).json()["workflow"]
        assert workflow["essaysAnalyzed"] is True

