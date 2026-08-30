import json
from datetime import UTC, datetime

from httpx2 import AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.mock_provider import MockProvider
from app.ai.schemas import (
    ConsolidationReport,
    DecomposedDimension,
    DecompositionReport,
    DimensionScore,
    DimensionScoringReport,
    PoolDimension,
    PoolDimensionReport,
    ScoreConfidence,
)
from app.api.dependencies import get_ai_provider, require_current_user
from app.db.models import Application, Base, User, UserRole
from app.db.session import get_db
from app.services.run_lock import ensure_lock_row
from tests.app_support import shared_test_app
from tests.application_support import activate_application


def _decomposition_of(report: PoolDimensionReport) -> DecompositionReport:
    return DecompositionReport(
        dimensions=[
            DecomposedDimension(
                key=dimension.key,
                name=dimension.name,
                definition=dimension.definition,
                high_end=dimension.high_end,
                low_end=dimension.low_end,
                source_keys=[dimension.key],
                from_committee_request=dimension.from_committee_request,
                decision="pass-through (test)",
            )
            for dimension in report.dimensions
        ],
    )


def route_criteria(provider: MockProvider, report: PoolDimensionReport) -> None:
    provider.route("<applicant_pool>", report)
    provider.route("<discovery_reports>", _decomposition_of(report))
    provider.route("<candidate_pairs>", ConsolidationReport(verdicts=[]))


def setup_app(role: UserRole | None) -> tuple:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    ensure_lock_row(db)

    user = None
    if role is not None:
        user = User(email="member@x.com", display_name="Member", role=role, is_active=True)
        db.add(user)
        db.commit()

    app = shared_test_app()
    app.dependency_overrides[get_db] = lambda: db
    if user is not None:
        app.dependency_overrides[require_current_user] = lambda: user

    provider = MockProvider()
    app.dependency_overrides[get_ai_provider] = lambda: provider
    return app, db, provider


def add_eligible(db: Session, *, email: str, raw_hash: str) -> Application:
    application = Application(
        primary_email=email,
        applicant_name="Test",
        raw_row={"Why a co-op": "We want community and will pitch in."},
        raw_row_hash=raw_hash,
        normalized={},
        submitted_at=datetime.now(UTC),
    )
    return activate_application(db, application)


def a_pattern_report() -> PoolDimensionReport:
    return PoolDimensionReport(
        dimensions=[
            PoolDimension(
                key="participation_commitment",
                name="Participation commitment",
                definition="Willingness to do shared work.",
                high_end="high",
                low_end="low",
                why_it_differentiates="Some are eager, some vague.",
            ),
            PoolDimension(
                key="skills_offered",
                name="Skills offered",
                definition="Concrete maintenance skills.",
                high_end="high",
                low_end="low",
                why_it_differentiates="Range from none to specific trades.",
            ),
        ],
    )


def a_pattern_report_v2() -> PoolDimensionReport:
    return PoolDimensionReport(
        dimensions=[
            PoolDimension(
                key="stated_participation",
                name="Stated participation",
                definition="Willingness to do shared work.",
                high_end="high",
                low_end="low",
                why_it_differentiates="Some eager, some vague.",
            ),
            PoolDimension(
                key="financial_stability",
                name="Financial stability",
                definition="Income resilience and stability.",
                high_end="high",
                low_end="low",
                why_it_differentiates="Range of income security.",
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


def _scoring_report_v2() -> DimensionScoringReport:
    return DimensionScoringReport(
        scores=[
            DimensionScore(
                dimension_key="participation_commitment",
                score=0.8,
                rationale="r",
                evidence="",
                confidence=ScoreConfidence.HIGH,
            ),
            DimensionScore(
                dimension_key="financial_stability",
                score=0.5,
                rationale="r",
                evidence="",
                confidence=ScoreConfidence.MEDIUM,
            ),
        ]
    )


def _scoring_report(*, commitment: float, skills: float) -> DimensionScoringReport:
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


async def stream_events(client: AsyncClient, url: str) -> list[dict]:
    """Return all NDJSON events from a streaming POST, in order."""
    response = await client.post(url)
    assert response.status_code == 200
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


async def current_analysis_id(client: AsyncClient) -> int:
    """Return the current shared analysis id used to guard ranking writes."""
    return (await client.get("/ranking/current")).json()["analysisId"]
