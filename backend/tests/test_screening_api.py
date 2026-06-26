import json

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.mock_provider import MockProvider
from app.ai.schemas import (
    DimensionMatch,
    DimensionMatchReport,
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
        provider.route("<essays>", an_essay_report())
        provider.route("<applicant_pool>", a_pattern_report())
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


@pytest.mark.anyio
async def test_ranking_orders_pool_and_seeds_equal_weights() -> None:
    app, db, provider = setup_app(role=UserRole.MEMBER)
    weak = add_eligible(db, email="weak@x.com", raw_hash="h1")
    strong = add_eligible(db, email="strong@x.com", raw_hash="h2")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Drive the whole chain; bind each candidate's scores by the applicant_id
        # marker in the scoring prompt (scoring fans out concurrently).
        provider.route("<essays>", an_essay_report())
        provider.route("<applicant_pool>", a_pattern_report())
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

    # Route by prompt content: the essay prompt carries "<essays>", discovery
    # carries "<applicant_pool>", scoring carries "DIMENSIONS:". Scores are bound
    # to each applicant by the applicant_id marker in the scoring prompt.
    provider.route("<essays>", an_essay_report())
    provider.route("<applicant_pool>", a_pattern_report())
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
async def test_criteria_phase_streams_thinking_deltas() -> None:
    # The discovery (and match) call streams the model's reasoning as
    # criteria_thinking events, so the UI can show live "thinking" during the
    # otherwise-opaque multi-minute call. The MockProvider emits fixed deltas.
    app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    provider.route("<essays>", an_essay_report())
    provider.route("<applicant_pool>", a_pattern_report())
    provider.route("applicant_id", a_scoring_report())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        events = await stream_events(client, "/screening/rank/run")

        thinking = [e for e in events if e["type"] == "criteria_thinking"]
        assert thinking, "expected streamed criteria_thinking deltas"
        # Deltas arrive between the criteria phase announcement and its completion.
        types = [e["type"] for e in events]
        assert types.index("phase") < types.index("criteria_thinking")
        assert "".join(e["text"] for e in thinking)  # non-empty reasoning text


@pytest.mark.anyio
async def test_tiers_reweight_and_resort_the_ranking() -> None:
    app, db, provider = setup_app(role=UserRole.MEMBER)
    # Two candidates who each lead on a different dimension, so the weighting
    # decides the order: commitment-strong vs skills-strong.
    commit_lead = add_eligible(db, email="commit@x.com", raw_hash="h1")
    skills_lead = add_eligible(db, email="skills@x.com", raw_hash="h2")

    provider.route("<essays>", an_essay_report())
    provider.route("<applicant_pool>", a_pattern_report())
    provider.route(
        f'"applicant_id": {commit_lead.id}', _scoring_report(commitment=0.9, skills=0.1)
    )
    provider.route(
        f'"applicant_id": {skills_lead.id}', _scoring_report(commitment=0.1, skills=0.9)
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await stream_events(client, "/screening/rank/run")

        # Default layout: S / A / B working tiers (empty) + Ignore, with every
        # dimension starting in Ignore — the committee drags them out to weigh in.
        # Displayed layout: S / A / B working tiers (empty) + a synthesized Ignore
        # zone holding every dimension, since nothing is placed yet.
        default = (await client.get("/screening/tiers")).json()["tiers"]
        working = [t for t in default if not t.get("ignore")]
        assert [t["label"] for t in working] == ["S-Tier", "A-Tier", "B-Tier"]
        assert all(t["dimension_keys"] == [] for t in working)
        ignore = next(t for t in default if t.get("ignore"))
        assert set(ignore["dimension_keys"]) == {"participation_commitment", "skills_offered"}

        # Put skills above commitment: skills_lead should now top the ranking.
        layout = {
            "tiers": [
                {"id": "t1", "label": "Top", "dimension_keys": ["skills_offered"], "ignore": False},
                {"id": "t2", "label": "Lower", "dimension_keys": ["participation_commitment"], "ignore": False},
                {"id": "ignore", "label": "Ignore", "dimension_keys": [], "ignore": True},
            ]
        }
        ranking = (await client.put("/screening/tiers", json=layout)).json()
        assert ranking["candidates"][0]["application_id"] == skills_lead.id
        assert ranking["weights"] == {"skills_offered": 2.0, "participation_commitment": 1.0}


@pytest.mark.anyio
async def test_tiers_ignore_drops_then_revives_a_dimension() -> None:
    app, db, provider = setup_app(role=UserRole.MEMBER)
    commit_lead = add_eligible(db, email="commit@x.com", raw_hash="h1")
    skills_lead = add_eligible(db, email="skills@x.com", raw_hash="h2")
    provider.route("<essays>", an_essay_report())
    provider.route("<applicant_pool>", a_pattern_report())
    provider.route(
        f'"applicant_id": {commit_lead.id}', _scoring_report(commitment=0.9, skills=0.1)
    )
    provider.route(
        f'"applicant_id": {skills_lead.id}', _scoring_report(commitment=0.1, skills=0.9)
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await stream_events(client, "/screening/rank/run")

        # Ignore commitment entirely: only skills counts, so skills_lead leads on
        # fit 0.9 vs 0.1 — decisive, not a tiebreak.
        ignore_commit = {
            "tiers": [
                {"id": "t1", "label": "Top", "dimension_keys": ["skills_offered"], "ignore": False},
                {"id": "ignore", "label": "Ignore", "dimension_keys": ["participation_commitment"], "ignore": True},
            ]
        }
        ranking = (await client.put("/screening/tiers", json=ignore_commit)).json()
        assert ranking["candidates"][0]["application_id"] == skills_lead.id
        assert ranking["weights"]["participation_commitment"] == 0.0
        assert ranking["candidates"][0]["fit"] == 0.9

        # Revive it back into a tier: it counts again.
        revive = {
            "tiers": [
                {"id": "t1", "label": "Top", "dimension_keys": ["skills_offered", "participation_commitment"], "ignore": False},
                {"id": "ignore", "label": "Ignore", "dimension_keys": [], "ignore": True},
            ]
        }
        ranking2 = (await client.put("/screening/tiers", json=revive)).json()
        assert ranking2["weights"]["participation_commitment"] == 1.0


@pytest.mark.anyio
async def test_tiers_reject_unknown_dimension_key() -> None:
    app, db, provider = setup_app(role=UserRole.MEMBER)
    a = add_eligible(db, email="a@x.com", raw_hash="h1")
    provider.route("<essays>", an_essay_report())
    provider.route("<applicant_pool>", a_pattern_report())
    provider.route(f'"applicant_id": {a.id}', a_scoring_report())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await stream_events(client, "/screening/rank/run")
        bad = {
            "tiers": [
                {"id": "t1", "label": "Top", "dimension_keys": ["not_a_real_dimension"], "ignore": False},
                {"id": "ignore", "label": "Ignore", "dimension_keys": [], "ignore": True},
            ]
        }
        assert (await client.put("/screening/tiers", json=bad)).status_code == 400


def a_pattern_report_v2() -> PoolPatternReport:
    """A re-discovery: participation_commitment recurs (drifted key), skills_offered
    is gone, and a genuinely new dimension appears."""
    return PoolPatternReport(
        summary="Pool varies on commitment and finances.",
        dimensions=[
            PoolDimension(
                key="stated_participation",  # same concept, drifted key
                name="Stated participation",
                definition="Willingness to do shared work.",
                why_it_differentiates="Some eager, some vague.",
            ),
            PoolDimension(
                key="financial_stability",  # genuinely new
                name="Financial stability",
                definition="Income resilience and stability.",
                why_it_differentiates="Range of income security.",
            ),
        ],
    )


@pytest.mark.anyio
async def test_re_rank_carries_tiers_forward_and_flags_new() -> None:
    """Re-ranking matches new dimensions to prior ones (high bar) and carries the
    committee's tier placement forward; unmatched new dimensions land in Ignore,
    flagged 'new'. The committee's deliberation is not lost on a re-rank."""
    app, db, provider = setup_app(role=UserRole.ADMIN)
    add_eligible(db, email="a@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # First run: discover v1 dimensions, score, then the committee tiers
        # participation_commitment into S-Tier.
        provider.route("<essays>", an_essay_report())
        provider.route("<applicant_pool>", a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/screening/rank/run")
        await client.put(
            "/screening/tiers",
            json={
                "tiers": [
                    {"id": "tier-s", "label": "S-Tier", "dimension_keys": ["participation_commitment"], "ignore": False},
                    {"id": "tier-a", "label": "A-Tier", "dimension_keys": ["skills_offered"], "ignore": False},
                    {"id": "ignore", "label": "Ignore", "dimension_keys": [], "ignore": True},
                ]
            },
        )

        # Pool changes (new applicant) so re-rank is allowed; re-discovery returns
        # v2 dimensions. The match pass maps stated_participation -> the prior
        # participation_commitment (same concept); financial_stability is new.
        add_eligible(db, email="b@x.com", raw_hash="h2")
        provider.route("<essays>", an_essay_report())
        provider.route("<applicant_pool>", a_pattern_report_v2())
        provider.route(
            "<prior_dimensions>",
            DimensionMatchReport(
                matches=[DimensionMatch(new_key="stated_participation", old_key="participation_commitment")]
            ),
        )
        provider.route("applicant_id", _scoring_report_v2())
        events = await stream_events(client, "/screening/rank/run")

        criteria_done = next(e for e in events if e["type"] == "criteria_done")
        assert criteria_done["carriedForward"] == 1
        assert criteria_done["newDimensions"] == 1

        layout = (await client.get("/screening/tiers")).json()["tiers"]
        by_label = {t["label"]: t for t in layout}
        # The matched dimension ADOPTED the prior key and kept the prior S-Tier
        # placement — so the placement carries forward by key, no separate identity.
        assert by_label["S-Tier"]["dimension_keys"] == ["participation_commitment"]
        # The genuinely-new dimension is unplaced -> shows in the synthesized Ignore zone.
        ignore = next(t for t in layout if t.get("ignore"))
        assert "financial_stability" in ignore["dimension_keys"]

        current = (await client.get("/screening/current")).json()
        assert current["newDimensionKeys"] == ["financial_stability"]
        # Key adopted, but the NEW content is kept (fresh discovery wording).
        by_key = {d["key"]: d for d in current["dimensions"]}
        assert by_key["participation_commitment"]["name"] == "Stated participation"

        # Acknowledge the new dimension in place (badge ✕ / "mark all reviewed"):
        # keep the layout unchanged, send the key in acknowledged_keys. It drops
        # out of new_dimension_keys without being placed in a working tier.
        ack = await client.put(
            "/screening/tiers",
            json={"tiers": layout, "acknowledged_keys": ["financial_stability"]},
        )
        assert ack.status_code == 200
        assert ack.json()["newDimensionKeys"] == []
        # And it stuck: still unplaced (in Ignore), just no longer flagged.
        current = (await client.get("/screening/current")).json()
        assert current["newDimensionKeys"] == []
        layout2 = (await client.get("/screening/tiers")).json()["tiers"]
        ignore2 = next(t for t in layout2 if t.get("ignore"))
        assert "financial_stability" in ignore2["dimension_keys"]


def _scoring_report_v2() -> DimensionScoringReport:
    # After key adoption the matched dimension is scored under the prior key
    # (participation_commitment) — though in practice it is reused from the first
    # run's cache, so only financial_stability is actually sent to the model.
    return DimensionScoringReport(
        scores=[
            DimensionScore(
                dimension_key="participation_commitment", score=0.8, rationale="r",
                evidence="", confidence=ScoreConfidence.HIGH,
            ),
            DimensionScore(
                dimension_key="financial_stability", score=0.5, rationale="r",
                evidence="", confidence=ScoreConfidence.MEDIUM,
            ),
        ]
    )


@pytest.mark.anyio
async def test_tiers_without_ignore_zone_means_everything_ignored() -> None:
    """Ignore is the absence of a placement, not a stored tier: a layout with only
    a working tier is valid, and dimensions left out are weight 0 (ignored)."""
    app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    provider.route("<essays>", an_essay_report())
    provider.route("<applicant_pool>", a_pattern_report())
    provider.route("applicant_id", a_scoring_report())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await stream_events(client, "/screening/rank/run")
        only_working = {
            "tiers": [
                {"id": "t1", "label": "Top", "dimension_keys": ["participation_commitment"], "ignore": False},
            ]
        }
        ranking = (await client.put("/screening/tiers", json=only_working)).json()
        # commitment is placed (weight 1); skills is unplaced -> ignored (weight 0).
        assert ranking["weights"] == {"participation_commitment": 1.0, "skills_offered": 0.0}
        # The displayed layout synthesizes the Ignore zone with the unplaced dim.
        layout = (await client.get("/screening/tiers")).json()["tiers"]
        ignore = next(t for t in layout if t.get("ignore"))
        assert ignore["dimension_keys"] == ["skills_offered"]


@pytest.mark.anyio
async def test_tiers_before_run_is_409() -> None:
    app, db, _ = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/screening/tiers")).status_code == 409
        assert (
            await client.put("/screening/tiers", json={"tiers": []})
        ).status_code == 409


@pytest.mark.anyio
async def test_rank_flags_unchanged_pool_but_allows_rerun() -> None:
    # After a Rank run, the estimate flags an unchanged pool as already current (so
    # the UI can say nothing requires a re-run). But a re-run is NOT blocked:
    # categorization is non-deterministic, so a member may deliberately re-run for a
    # fresh set of criteria. The confirmation card is the gate, not the server.
    app, db, provider = setup_app(role=UserRole.MEMBER)
    a = add_eligible(db, email="a@x.com", raw_hash="h1")
    provider.route("<essays>", an_essay_report())
    provider.route("<applicant_pool>", a_pattern_report())
    provider.route(f'"applicant_id": {a.id}', a_scoring_report())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await stream_events(client, "/screening/rank/run")

        # Pool unchanged → estimate flags it current, but the re-run still succeeds.
        estimate = (await client.get("/screening/rank/estimate")).json()
        assert estimate["ranking_current"] is True
        assert (await client.post("/screening/rank/run")).status_code == 200


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


# --- Discovery seeds (favourites + proposed dimensions) ----------------------


def _pattern_report_with_requested() -> PoolPatternReport:
    """A discovery result where the model flagged one dimension as created from a
    committee request (the auto-favourite signal)."""
    return PoolPatternReport(
        summary="Pool varies on commitment and a requested axis.",
        dimensions=[
            PoolDimension(
                key="participation_commitment",
                name="Participation commitment",
                definition="Willingness to do shared work.",
                why_it_differentiates="Some eager, some vague.",
            ),
            PoolDimension(
                key="playground_age_children",
                name="Playground-age children",
                definition="Presence of school-age kids who'd use shared play space.",
                why_it_differentiates="Some households have young kids, some none.",
                from_committee_request=True,
            ),
        ],
    )


def test_build_prompt_unseeded_has_no_requested_section() -> None:
    # An un-seeded discovery prompt must not carry a REQUESTED AXES section, so the
    # default blind run is unchanged.
    from app.ai.pattern_discovery import DiscoverySeeds, build_prompt

    app, db, _ = setup_app(role=UserRole.MEMBER)
    a = add_eligible(db, email="a@x.com", raw_hash="h1")
    apps = [a]
    bare = build_prompt(db, apps)
    assert "<requested_axes>" not in bare
    # An empty seed set is equivalent to no seeds.
    assert build_prompt(db, apps, seeds=DiscoverySeeds()) == bare


def test_build_prompt_includes_favourited_and_proposed_seeds() -> None:
    from app.ai.pattern_discovery import DiscoverySeeds, build_prompt

    app, db, _ = setup_app(role=UserRole.MEMBER)
    a = add_eligible(db, email="a@x.com", raw_hash="h1")
    seeds = DiscoverySeeds(
        favourited=[{"name": "Conflict Mediation", "definition": "Resolves disputes."}],
        proposed=["school-age kids who'd use the playground"],
    )
    prompt = build_prompt(db, [a], seeds=seeds)
    assert "<requested_axes>" in prompt
    assert "Conflict Mediation: Resolves disputes." in prompt
    assert "school-age kids who'd use the playground" in prompt
    # The model is told to flag what it creates from a request.
    assert "from_committee_request" in prompt


@pytest.mark.anyio
async def test_proposed_dimension_seeds_discovery_then_clears_and_auto_favourites() -> None:
    # A proposed axis is fed to discovery; the model returns a dimension flagged
    # from_committee_request. After the run: the proposal is consumed (cleared) and
    # the flagged dimension is auto-favourited.
    app, db, provider = setup_app(role=UserRole.MEMBER)
    a = add_eligible(db, email="a@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # First blind run so a run exists to attach seeds to.
        provider.route("<essays>", an_essay_report())
        provider.route("<applicant_pool>", a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/screening/rank/run")

        # Propose an axis between runs.
        seeds = (await client.put(
            "/screening/seeds",
            json={"proposed_dimensions": ["school-age kids who'd use the playground"]},
        )).json()
        assert seeds["proposedDimensions"] == ["school-age kids who'd use the playground"]
        assert seeds["favouritedKeys"] == []

        # Re-run: discovery now returns a report flagging the requested dimension.
        provider.calls.clear()
        provider.route("<applicant_pool>", _pattern_report_with_requested())
        provider.route("<prior_dimensions>", DimensionMatchReport(matches=[]))  # match pass
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/screening/rank/run")

        # The proposal text reached the discovery prompt.
        discovery_prompt = next(c.prompt for c in provider.calls if "<applicant_pool>" in c.prompt)
        assert "school-age kids who'd use the playground" in discovery_prompt

        # After the run: proposal consumed (cleared); flagged dimension auto-favourited.
        current = (await client.get("/screening/current")).json()
        assert current["proposedDimensions"] == []
        assert current["favouritedKeys"] == ["playground_age_children"]


@pytest.mark.anyio
async def test_favourited_dimension_is_re_fed_to_discovery_and_persists() -> None:
    # A favourited dimension is sent back into the next discovery (by name +
    # definition) and stays favourited across the re-run.
    app, db, provider = setup_app(role=UserRole.MEMBER)
    a = add_eligible(db, email="a@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        provider.route("<essays>", an_essay_report())
        provider.route("<applicant_pool>", a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/screening/rank/run")

        # Favourite an existing dimension.
        seeds = (await client.put(
            "/screening/seeds", json={"favourited_keys": ["participation_commitment"]},
        )).json()
        assert seeds["favouritedKeys"] == ["participation_commitment"]

        # Re-run: the favourite recurs (match pass maps it back to its prior key).
        provider.calls.clear()
        provider.route("<applicant_pool>", a_pattern_report())
        provider.route(
            "<prior_dimensions>",
            DimensionMatchReport(matches=[]),  # same keys, so no rewrite needed
        )
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/screening/rank/run")

        # The favourite's name + definition were re-fed to discovery.
        discovery_prompt = next(c.prompt for c in provider.calls if "<applicant_pool>" in c.prompt)
        assert "<requested_axes>" in discovery_prompt
        assert "Participation commitment: Willingness to do shared work." in discovery_prompt

        # It is still favourited after the re-run.
        current = (await client.get("/screening/current")).json()
        assert "participation_commitment" in current["favouritedKeys"]


@pytest.mark.anyio
async def test_put_seeds_before_run_is_409() -> None:
    app, db, _ = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.put("/screening/seeds", json={"proposed_dimensions": ["x"]})
        assert resp.status_code == 409


@pytest.mark.anyio
async def test_put_seeds_rejects_unknown_favourite_key() -> None:
    # Favouriting a key that isn't a real dimension is silently dropped (validated
    # against the run's report), so a stale key can't poison the seed set.
    app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        provider.route("<essays>", an_essay_report())
        provider.route("<applicant_pool>", a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/screening/rank/run")

        seeds = (await client.put(
            "/screening/seeds",
            json={"favourited_keys": ["participation_commitment", "not_a_real_key"]},
        )).json()
        assert seeds["favouritedKeys"] == ["participation_commitment"]
