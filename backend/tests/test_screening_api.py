import json

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.mock_provider import MockProvider
from app.ai.schemas import (
    DimensionScore,
    DimensionScoringReport,
    PoolDimension,
    PoolPatternReport,
    ScoreConfidence,
)
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
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()

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
        raw_row={"Why a co-op": "We want community and will pitch in."},
        raw_row_hash=raw_hash,
        normalized={},
        status=ApplicationStatus.ELIGIBLE,
        hard_filter_reasons=[],
    )
    db.add(app)
    db.commit()
    return app


def a_pattern_report() -> PoolPatternReport:
    return PoolPatternReport(
        summary="Pool varies on commitment and skills.",
        dimensions=[
            PoolDimension(
                key="participation_commitment",
                name="Participation commitment",
                definition="Willingness to do shared work.",
                why_it_differentiates="Some are eager, some vague.",
            ),
            PoolDimension(
                key="skills_offered",
                name="Skills offered",
                definition="Concrete maintenance skills.",
                why_it_differentiates="Range from none to specific trades.",
            ),
        ],
    )


def a_scoring_report() -> DimensionScoringReport:
    return DimensionScoringReport(
        scores=[
            DimensionScore(
                dimension_key="participation_commitment",
                score=0.8,
                rationale="Says they will pitch in.",
                evidence="will pitch in",
                confidence=ScoreConfidence.HIGH,
            ),
            DimensionScore(
                dimension_key="skills_offered",
                score=0.2,
                rationale="No concrete skills stated.",
                evidence="",
                confidence=ScoreConfidence.LOW,
            ),
        ]
    )


def _scoring_report(*, commitment: float, skills: float) -> DimensionScoringReport:
    """A scoring report with caller-chosen scores, for ranking-order tests."""
    return DimensionScoringReport(
        scores=[
            DimensionScore(
                dimension_key="participation_commitment",
                score=commitment,
                rationale="r",
                evidence="",
                confidence=ScoreConfidence.MEDIUM,
            ),
            DimensionScore(
                dimension_key="skills_offered",
                score=skills,
                rationale="r",
                evidence="",
                confidence=ScoreConfidence.MEDIUM,
            ),
        ]
    )


async def stream_summary(client: AsyncClient, url: str) -> dict:
    response = await client.post(url)
    assert response.status_code == 200
    summary = None
    for line in response.text.splitlines():
        if line.strip():
            event = json.loads(line)
            if event.get("type") == "summary":
                summary = event
    assert summary is not None
    return summary


@pytest.mark.anyio
async def test_discover_requires_login() -> None:
    app, _, _ = setup_app(role=None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.post("/screening/discover")).status_code == 401


@pytest.mark.anyio
async def test_discover_with_no_eligible_is_409() -> None:
    app, _, _ = setup_app(role=UserRole.MEMBER)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.post("/screening/discover")).status_code == 409


@pytest.mark.anyio
async def test_discover_maps_provider_failure_to_502() -> None:
    # An eligible applicant exists but the provider has no queued result, so the
    # synthesis call raises. The endpoint must wrap it as a readable 502, not let
    # it surface as a bare 500.
    app, db, _ = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/screening/discover")
    assert response.status_code == 502
    assert "Pattern discovery failed" in response.json()["detail"]


@pytest.mark.anyio
async def test_scoring_before_discovery_is_409() -> None:
    app, db, _ = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/screening/scoring/estimate")).status_code == 409
        assert (await client.post("/screening/scoring/run")).status_code == 409


@pytest.mark.anyio
async def test_full_flow_discover_then_score_then_detail() -> None:
    app, db, provider = setup_app(role=UserRole.MEMBER)
    application = add_eligible(db, email="a@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Discover (one synthesis call over the pool).
        provider.queue(a_pattern_report())
        discovered = (await client.post("/screening/discover")).json()
        assert discovered["summary"].startswith("Pool varies")
        assert [d["key"] for d in discovered["dimensions"]] == [
            "participation_commitment",
            "skills_offered",
        ]

        # 2. Current run reflects the discovered dimensions.
        current = (await client.get("/screening/current")).json()
        assert current["runId"] == discovered["runId"]
        assert len(current["dimensions"]) == 2

        # 3. Score the pool.
        provider.queue(a_scoring_report())
        summary = await stream_summary(client, "/screening/scoring/run")
        assert summary["analyzed"] == 1
        assert summary["failed"] == 0

        # 4. Scores surface on the candidate detail, joined to dimension names,
        #    and status is untouched.
        detail = (await client.get(f"/applications/{application.id}")).json()["application"]
        assert detail["status"] == "eligible"
        assert detail["statusSource"] == "untouched"
        scores = detail["dimensionScores"]
        assert len(scores) == 2
        by_key = {s["dimension_key"]: s for s in scores}
        assert by_key["participation_commitment"]["name"] == "Participation commitment"
        assert by_key["participation_commitment"]["score"] == 0.8
        assert by_key["skills_offered"]["confidence"] == "low"


@pytest.mark.anyio
async def test_ranking_before_discovery_is_409() -> None:
    app, db, _ = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/screening/ranking")).status_code == 409
        assert (
            await client.put("/screening/shortlist-line", json={"shortlist_size": 5})
        ).status_code == 409


@pytest.mark.anyio
async def test_ranking_orders_pool_and_seeds_equal_weights() -> None:
    app, db, provider = setup_app(role=UserRole.MEMBER)
    weak = add_eligible(db, email="weak@x.com", raw_hash="h1")
    strong = add_eligible(db, email="strong@x.com", raw_hash="h2")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        provider.queue(a_pattern_report())
        await client.post("/screening/discover")

        # Scoring fans out concurrently, so bind each result to its application by
        # the applicant_id marker in the prompt rather than relying on queue order.
        provider.route(f'"applicant_id": {weak.id}', _scoring_report(commitment=0.2, skills=0.2))
        provider.route(f'"applicant_id": {strong.id}', _scoring_report(commitment=0.9, skills=0.9))
        await stream_summary(client, "/screening/scoring/run")

        ranking = (await client.get("/screening/ranking")).json()

        # Equal-weight baseline: both dimensions weight 1.0, no AI-proposed weight.
        assert ranking["weights"] == {
            "participation_commitment": 1.0,
            "skills_offered": 1.0,
        }
        # Strong candidate leads; fit is the plain average under equal weights.
        candidates = ranking["candidates"]
        assert [c["application_id"] for c in candidates] == [strong.id, weak.id]
        assert candidates[0]["fit"] == 0.9
        assert candidates[0]["band"] == "Strong fit"
        # Default shortlist line keeps everyone above it.
        assert ranking["shortlistSize"] == 20
        assert ranking["aboveLineCount"] == 2
        assert all(c["above_line"] for c in candidates)


@pytest.mark.anyio
async def test_shortlist_line_update_changes_above_count() -> None:
    app, db, provider = setup_app(role=UserRole.MEMBER)
    high = add_eligible(db, email="a@x.com", raw_hash="h1")
    low = add_eligible(db, email="b@x.com", raw_hash="h2")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        provider.queue(a_pattern_report())
        await client.post("/screening/discover")
        provider.route(f'"applicant_id": {high.id}', _scoring_report(commitment=0.8, skills=0.6))
        provider.route(f'"applicant_id": {low.id}', _scoring_report(commitment=0.5, skills=0.5))
        await stream_summary(client, "/screening/scoring/run")

        updated = (
            await client.put("/screening/shortlist-line", json={"shortlist_size": 1})
        ).json()
        assert updated["shortlistSize"] == 1

        ranking = (await client.get("/screening/ranking")).json()
        assert ranking["aboveLineCount"] == 1
        assert [c["above_line"] for c in ranking["candidates"]] == [True, False]


@pytest.mark.anyio
async def test_dimension_scores_null_before_run() -> None:
    app, db, provider = setup_app(role=UserRole.MEMBER)
    application = add_eligible(db, email="a@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # No run at all -> null.
        detail = (await client.get(f"/applications/{application.id}")).json()["application"]
        assert detail["dimensionScores"] is None

        # After discovery but before scoring -> still null (no scores yet).
        provider.queue(a_pattern_report())
        await client.post("/screening/discover")
        detail = (await client.get(f"/applications/{application.id}")).json()["application"]
        assert detail["dimensionScores"] is None
