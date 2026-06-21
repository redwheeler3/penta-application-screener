import json

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.mock_provider import MockProvider
from app.ai.schemas import EssayAnalysisReport
from app.api.dependencies import get_ai_provider, require_current_user
from app.db.models import Application, ApplicationStatus, Base, User, UserRole
from app.db.session import get_db
from app.main import create_app


def setup_app(role: UserRole | None) -> tuple:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()

    user = None
    if role is not None:
        user = User(email="member@x.com", display_name="Member", role=role, is_active=True)
        db.add(user)
        db.commit()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    if user is not None:
        app.dependency_overrides[require_current_user] = lambda: user

    provider = MockProvider()
    app.dependency_overrides[get_ai_provider] = lambda: provider
    return app, db, provider


def add_eligible(db: Session, *, email: str, raw_hash: str) -> Application:
    app = Application(
        primary_email=email,
        applicant_name="Test",
        raw_row={
            "Please introduce yourself and your family, including your employment background, interests, and values.": "Two of us, both teachers.",
        },
        raw_row_hash=raw_hash,
        normalized={},
        status=ApplicationStatus.ELIGIBLE,
        hard_filter_reasons=[],
    )
    db.add(app)
    db.commit()
    return app


def a_report() -> EssayAnalysisReport:
    return EssayAnalysisReport(
        summary="Two teachers, new to co-op living.",
        skills_offered=["teaching"],
        stated_motivations=["community"],
    )


async def run_and_summarize(client: AsyncClient) -> dict:
    response = await client.post("/essay-analysis/run")
    assert response.status_code == 200
    summary = None
    for line in response.text.splitlines():
        if line.strip():
            event = json.loads(line)
            if event.get("type") == "summary":
                summary = event
    assert summary is not None, "stream did not include a summary line"
    return summary


@pytest.mark.anyio
async def test_run_requires_login() -> None:
    app, _, _ = setup_app(role=None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/essay-analysis/run")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_member_runs_and_summary_reports_counts() -> None:
    app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    add_eligible(db, email="b@x.com", raw_hash="h2")
    provider.queue(a_report())
    provider.queue(a_report())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        summary = await run_and_summarize(client)

    assert summary["analyzed"] == 2
    assert summary["cached"] == 0
    assert summary["failed"] == 0
    # Informational pass: no flagged field in the summary.
    assert "flagged" not in summary


@pytest.mark.anyio
async def test_run_does_not_change_status_and_surfaces_on_detail() -> None:
    app, db, provider = setup_app(role=UserRole.MEMBER)
    application = add_eligible(db, email="a@x.com", raw_hash="h1")
    provider.queue(a_report())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await run_and_summarize(client)

        detail = (await client.get(f"/applications/{application.id}")).json()["application"]
        # Status untouched by the essay pass.
        assert detail["status"] == "eligible"
        assert detail["statusSource"] == "untouched"
        # Analysis surfaced on the detail page.
        assert detail["essayAnalysis"]["summary"] == "Two teachers, new to co-op living."
        assert detail["essayAnalysis"]["skills_offered"] == ["teaching"]


@pytest.mark.anyio
async def test_detail_essay_analysis_null_before_run() -> None:
    app, db, _ = setup_app(role=UserRole.MEMBER)
    application = add_eligible(db, email="a@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        detail = (await client.get(f"/applications/{application.id}")).json()["application"]
    # Not yet run -> null (unknown), distinct from "ran and found nothing".
    assert detail["essayAnalysis"] is None
