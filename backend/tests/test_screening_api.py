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
    EssayAnalysisReport,
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




@pytest.mark.anyio
async def test_rank_requires_login() -> None:
    app, _, _ = setup_app(role=None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.post("/screening/rank/run")).status_code == 401


@pytest.mark.anyio
async def test_full_flow_rank_then_detail() -> None:
    app, db, provider = setup_app(role=UserRole.MEMBER)
    application = add_eligible(db, email="a@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # The Rank chain summarizes essays, finds criteria, then scores.
        provider.route("ESSAYS:", an_essay_report())
        provider.route("APPLICANT POOL:", a_pattern_report())
        provider.route(f'"applicant_id": {application.id}', a_scoring_report())
        summary = next(
            e
            for e in await stream_events(client, "/screening/rank/run")
            if e["type"] == "summary"
        )
        assert summary["dimensions"] == 2
        assert summary["scored"] == 1
        assert summary["failed"] == 0

        # The current run reflects the freshly found criteria.
        current = (await client.get("/screening/current")).json()
        assert len(current["dimensions"]) == 2

        # Scores surface on the candidate detail, joined to dimension names, and
        # status is untouched (the chain's passes never gate eligibility).
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
        # Drive the whole chain; bind each candidate's scores by the applicant_id
        # marker in the scoring prompt (scoring fans out concurrently).
        provider.route("ESSAYS:", an_essay_report())
        provider.route("APPLICANT POOL:", a_pattern_report())
        provider.route(f'"applicant_id": {weak.id}', _scoring_report(commitment=0.2, skills=0.2))
        provider.route(f'"applicant_id": {strong.id}', _scoring_report(commitment=0.9, skills=0.9))
        await stream_events(client, "/screening/rank/run")

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
        provider.route("ESSAYS:", an_essay_report())
        provider.route("APPLICANT POOL:", a_pattern_report())
        provider.route(f'"applicant_id": {high.id}', _scoring_report(commitment=0.8, skills=0.6))
        provider.route(f'"applicant_id": {low.id}', _scoring_report(commitment=0.5, skills=0.5))
        await stream_events(client, "/screening/rank/run")

        updated = (
            await client.put("/screening/shortlist-line", json={"shortlist_size": 1})
        ).json()
        assert updated["shortlistSize"] == 1

        ranking = (await client.get("/screening/ranking")).json()
        assert ranking["aboveLineCount"] == 1
        assert [c["above_line"] for c in ranking["candidates"]] == [True, False]


def an_essay_report() -> EssayAnalysisReport:
    return EssayAnalysisReport(summary="They want community and will pitch in.")


async def stream_events(client: AsyncClient, url: str) -> list[dict]:
    """All NDJSON events from a streaming POST, in order."""
    response = await client.post(url)
    assert response.status_code == 200
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


@pytest.mark.anyio
async def test_rank_chain_runs_essays_criteria_scores() -> None:
    app, db, provider = setup_app(role=UserRole.MEMBER)
    weak = add_eligible(db, email="weak@x.com", raw_hash="h1")
    strong = add_eligible(db, email="strong@x.com", raw_hash="h2")

    # Route by prompt content: the essay prompt carries "ESSAYS:", discovery
    # carries "APPLICANT POOL:", scoring carries "DIMENSIONS:". Scores are bound
    # to each applicant by the applicant_id marker in the scoring prompt.
    provider.route("ESSAYS:", an_essay_report())
    provider.route("APPLICANT POOL:", a_pattern_report())
    provider.route(
        f'"applicant_id": {weak.id}', _scoring_report(commitment=0.2, skills=0.2)
    )
    provider.route(
        f'"applicant_id": {strong.id}', _scoring_report(commitment=0.9, skills=0.9)
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        events = await stream_events(client, "/screening/rank/run")

        # The three phases are announced in order.
        phases = [e["phase"] for e in events if e["type"] == "phase"]
        assert phases == ["essays", "criteria", "scores"]

        summary = next(e for e in events if e["type"] == "summary")
        assert summary["dimensions"] == 2
        assert summary["scored"] == 2
        assert summary["failed"] == 0

        # The chain produced a current run and a full ranking, strong above weak.
        ranking = (await client.get("/screening/ranking")).json()
        assert [c["application_id"] for c in ranking["candidates"]] == [strong.id, weak.id]


@pytest.mark.anyio
async def test_rank_estimate_combines_three_passes() -> None:
    app, db, _ = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        estimate = (await client.get("/screening/rank/estimate")).json()
        b = estimate["breakdown"]
        # Total is the sum of the three pass projections, and flagged approximate.
        assert estimate["estimated_usd"] == pytest.approx(
            b["essays_usd"] + b["criteria_usd"] + b["scoring_usd"], abs=1e-4
        )
        assert estimate["approximate"] is True
        assert estimate["eligible"] == 1


@pytest.mark.anyio
async def test_rank_with_no_eligible_is_409() -> None:
    app, _, _ = setup_app(role=UserRole.MEMBER)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/screening/rank/estimate")).status_code == 409
        assert (await client.post("/screening/rank/run")).status_code == 409


@pytest.mark.anyio
async def test_rank_over_cap_fails_fast() -> None:
    app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")

    # Force the combined estimate over the cap by setting a tiny cap.
    from app.services.settings import get_app_settings, save_app_settings

    settings = get_app_settings(db)
    settings.ai.spending_cap_usd = 0.0
    save_app_settings(db, settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # No provider results queued: a 402 must come before any model call.
        assert (await client.post("/screening/rank/run")).status_code == 402


@pytest.mark.anyio
async def test_dimension_scores_null_before_run() -> None:
    app, db, _ = setup_app(role=UserRole.MEMBER)
    application = add_eligible(db, email="a@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # No run at all -> null (the candidate has no scores to surface yet).
        detail = (await client.get(f"/applications/{application.id}")).json()["application"]
        assert detail["dimensionScores"] is None
