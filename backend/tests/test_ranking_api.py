import json

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.mock_provider import MockProvider
from app.ai.schemas import (
    ConsolidationReport,
    ConsolidationVerdict,
    DecomposedDimension,
    DecompositionReport,
    DimensionMatch,
    DimensionMatchReport,
    DimensionScore,
    DimensionScoringReport,
    PoolDimension,
    PoolDimensionReport,
    ScoreConfidence,
)
from app.api.dependencies import get_ai_provider, require_current_user
from app.db.models import Application, ApplicationStatus, Base, User, UserRole
from app.db.session import get_db
from app.main import create_app
from app.services.cost_report import RANK_PASS_LABELS


def _decomposition_of(report: PoolDimensionReport) -> DecompositionReport:
    """A pass-through decomposition of a discovery report: each dimension becomes its
    own settled axis (one source key, no merge). Keeps the settled keys identical to the
    discovery keys, so the match/score/tier flow downstream is unchanged — the mock
    decomposition is a no-op reshaper, which is what these criteria/tier tests want."""
    return DecompositionReport(
        dimensions=[
            DecomposedDimension(
                key=d.key,
                name=d.name,
                definition=d.definition,
                high_end=d.high_end,
                low_end=d.low_end,
                source_keys=[d.key],
                from_committee_request=d.from_committee_request,
                decision="pass-through (test)",
            )
            for d in report.dimensions
        ],
    )


def route_criteria(provider: MockProvider, report: PoolDimensionReport) -> None:
    """Route the criteria-phase model calls from one discovery report: the K-parallel
    discovery (``<applicant_pool>``), the decomposition that settles them
    (``<discovery_reports>``, a pass-through of the same dims), and a keep-everything
    verdict for the post-score consolidation confirm (``<candidate_pairs>``) — routed
    only in case correlated mock scores nominate a pair, so the default full-chain test
    doesn't merge anything. Tests that want a merge route their own ConsolidationReport."""
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


def a_pattern_report() -> PoolDimensionReport:
    return PoolDimensionReport(
        dimensions=[
            PoolDimension(
                key="participation_commitment",
                name="Participation commitment",
                definition="Willingness to do shared work.",
                high_end="high", low_end="low", why_it_differentiates="Some are eager, some vague.",
            ),
            PoolDimension(
                key="skills_offered",
                name="Skills offered",
                definition="Concrete maintenance skills.",
                high_end="high", low_end="low", why_it_differentiates="Range from none to specific trades.",
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
        assert (await client.post("/ranking/run")).status_code == 401


@pytest.mark.anyio
async def test_full_flow_rank_then_detail() -> None:
    app, db, provider = setup_app(role=UserRole.MEMBER)
    application = add_eligible(db, email="a@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # The Rank chain finds criteria, then scores.
        route_criteria(provider, a_pattern_report())
        provider.route(f'"applicant_id": {application.id}', a_scoring_report())
        summary = next(
            e
            for e in await stream_events(client, "/ranking/run")
            if e["type"] == "summary"
        )
        assert summary["dimensions"] == 2
        assert summary["scored"] == 1
        assert summary["failed"] == 0

        # The current run reflects the freshly found criteria.
        current = (await client.get("/ranking/current")).json()
        assert len(current["dimensions"]) == 2

        # With every dimension initially in Ignore, details do not present raw
        # scores as if the committee had selected them.
        detail = (await client.get(f"/applications/{application.id}")).json()["application"]
        assert detail["status"] == "eligible"
        assert detail["statusSource"] == "untouched"
        assert detail["dimensionScores"] == []
        assert detail["dimensionScoringTrace"]["dimensionCount"] == 2

        # Once the committee places dimensions in a working tier, their scores
        # surface on the candidate detail, joined to dimension names.
        await client.put(
            "/ranking/tiers",
            json={
                "tiers": [
                    {
                        "id": "tier-s",
                        "label": "Critical",
                        "dimensionKeys": ["participation_commitment", "skills_offered"],
                        "ignore": False,
                    },
                    {"id": "ignore", "label": "Ignore", "dimensionKeys": [], "ignore": True},
                ]
            },
        )
        detail = (await client.get(f"/applications/{application.id}")).json()["application"]
        scores = detail["dimensionScores"]
        assert len(scores) == 2
        by_key = {s["dimensionKey"]: s for s in scores}
        assert by_key["participation_commitment"]["name"] == "Participation commitment"
        assert by_key["participation_commitment"]["score"] == 0.8
        assert by_key["skills_offered"]["confidence"] == "low"
        trace = detail["dimensionScoringTrace"]
        assert trace["dimensionCount"] == 2
        assert trace["modelIds"] == ["mock-model"]
        assert len(trace["promptVersions"]) == 1
        assert trace["inputTokens"] == 100
        assert trace["outputTokens"] == 50
        assert trace["costUsd"] > 0


@pytest.mark.anyio
async def test_score_current_fills_only_missing_scores_without_replacing_run() -> None:
    app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        route_criteria(provider, a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")

        before = (await client.get("/ranking/current")).json()
        await client.put(
            "/ranking/tiers",
            json={
                "tiers": [
                    {"id": "critical", "label": "Critical", "dimensionKeys": ["skills_offered"], "ignore": False},
                    {"id": "ignore", "label": "Ignore", "dimensionKeys": ["participation_commitment"], "ignore": True},
                ]
            },
        )
        add_eligible(db, email="b@x.com", raw_hash="h2")

        estimate = (await client.get("/ranking/score-current/estimate")).json()
        assert estimate["toAnalyze"] == 1
        assert estimate["cached"] == 1
        assert estimate["dimensions"] == 2

        calls_before = len(provider.calls)
        summary = next(
            event
            for event in await stream_events(client, "/ranking/score-current")
            if event["type"] == "summary"
        )
        assert summary["scored"] == 1
        assert summary["dimensions"] == 2
        # Only the new applicant's scoring call ran: no discovery, decomposition,
        # matching, or consolidation call is part of this path.
        assert len(provider.calls) == calls_before + 1

        after = (await client.get("/ranking/current")).json()
        assert after["runId"] == before["runId"]
        assert after["dimensions"] == before["dimensions"]
        tiers = (await client.get("/ranking/tiers")).json()["tiers"]
        assert tiers[0]["dimensionKeys"] == ["skills_offered"]
        assert (await client.get("/dashboard")).json()["workflow"]["rankingCurrent"] is True

        last_runs = (await client.get("/insights/last-runs")).json()
        assert last_runs["rankScores"]["kind"] == "rank_scores"
        assert [p["label"] for p in last_runs["rankScores"]["passes"]] == ["Dimension scoring"]
        metrics = (await client.get("/insights/metrics")).json()
        assert metrics["runs"][-1]["kind"] == "rank_scores"
        assert metrics["runs"][-1]["dimensions"] is None


@pytest.mark.anyio
async def test_score_current_requires_existing_criteria() -> None:
    app, _, _ = setup_app(role=UserRole.MEMBER)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/ranking/score-current/estimate")).status_code == 409
        assert (await client.post("/ranking/score-current")).status_code == 409


@pytest.mark.anyio
async def test_insights_cost_aggregates_by_pass() -> None:
    # After a rank, the cost report sums stored spend by pass: scoring from
    # ApplicationAIResult, discovery from the run. (Screening isn't run in this flow.)
    app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        route_criteria(provider, a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")

        report = (await client.get("/insights/cost")).json()
        groups = {g["runLabel"]: g for g in report["groups"]}
        # Grouped by triggering run: Screen, full discovery-and-rank, and score-current.
        assert set(groups) == {"Screen", "Discover criteria & rank", "Score current criteria"}
        rank_passes = {p["passLabel"]: p for p in groups["Discover criteria & rank"]["passes"]}
        assert set(rank_passes) == set(RANK_PASS_LABELS)
        assert [p["passLabel"] for p in groups["Screen"]["passes"]] == ["Screening"]
        # Discovery, decomposition, and matching are separate passes (not summed into one).
        # First run (no prior report) → no match pass ran → 0 matching cost.
        assert rank_passes["Dimension matching"]["costUsd"] == 0.0
        assert rank_passes["Pattern discovery"]["costUsd"] > 0.0
        # Decomposition ran (K≥2 reports settled), so it recorded a cost.
        assert rank_passes["Dimension decomposition"]["costUsd"] > 0.0
        assert rank_passes["Dimension scoring"]["calls"] == 2  # 1 applicant × 2 dimensions
        # Cacheable passes are marked so; the always-fresh ones are not (UI shows "—").
        assert rank_passes["Dimension scoring"]["cacheable"] is True
        assert rank_passes["Pattern discovery"]["cacheable"] is False
        assert rank_passes["Dimension matching"]["cacheable"] is False
        # Subtotals and total reconcile.
        assert groups["Discover criteria & rank"]["subtotalUsd"] == pytest.approx(
            sum(p["costUsd"] for p in groups["Discover criteria & rank"]["passes"]), abs=1e-6
        )
        assert report["totalCostUsd"] == pytest.approx(
            sum(g["subtotalUsd"] for g in report["groups"]), abs=1e-6
        )
        assert report["totalSavedUsd"] == pytest.approx(
            sum(g["subtotalSavedUsd"] for g in report["groups"]), abs=1e-6
        )


@pytest.mark.anyio
async def test_last_runs_records_fresh_and_cached_cost() -> None:
    # A first Rank spends everything fresh; a second Rank on the SAME pool reuses the
    # scoring caches, so its ledger shows cached counts and a saved estimate.
    from app.schemas.settings import AISettings

    app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        route_criteria(provider, a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")

        first = (await client.get("/insights/last-runs")).json()
        assert first["screen"] is None  # no Screen run happened
        rank = first["rank"]
        by_pass = {p["label"]: p for p in rank["passes"]}
        assert set(by_pass) == set(RANK_PASS_LABELS)
        # First run: everything fresh, nothing cached.
        assert rank["freshUsd"] > 0
        assert rank["cachedSavedUsd"] == 0.0
        assert by_pass["Dimension scoring"]["freshCalls"] == 2
        # Discovery ran K parallel calls (the fan-out), not 1.
        assert by_pass["Pattern discovery"]["freshCalls"] == AISettings().discovery_fan_out
        # The per-pass token breakdown is now persisted, not discarded: each fresh pass
        # records the tokens behind its spend (MockProvider bills 100 in / 50 out a call).
        assert by_pass["Pattern discovery"]["inputTokens"] == 100 * AISettings().discovery_fan_out
        assert by_pass["Pattern discovery"]["outputTokens"] == 50 * AISettings().discovery_fan_out
        assert by_pass["Dimension scoring"]["inputTokens"] > 0

        # Re-rank the unchanged pool: scores are cache hits now.
        route_criteria(provider, a_pattern_report())
        provider.route("<prior_dimensions>", DimensionMatchReport(matches=[]))
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")

        second = (await client.get("/insights/last-runs")).json()["rank"]
        by_pass2 = {p["label"]: p for p in second["passes"]}
        # Scoring reused from cache → cached counts and a nonzero saving.
        # Dimension scoring persists one cache row per dimension, matching the
        # cumulative spend table's unit.
        assert by_pass2["Dimension scoring"]["cachedCount"] == 2
        assert by_pass2["Dimension scoring"]["cachedSavedUsd"] > 0.0
        assert second["cachedSavedUsd"] > 0.0


@pytest.mark.anyio
async def test_cost_surfaces_agree_on_rank_passes() -> None:
    # Drift guard: the two cost surfaces read from different stores (cumulative from
    # RankingRun/ApplicationAIResult, last-run from the ledger) and are easy to update
    # in one but not the other — the bug that once let consolidation show in last-run
    # but not cumulative. After a real Rank, both must cover exactly RANK_PASS_LABELS.
    app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        route_criteria(provider, a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")

        cumulative = (await client.get("/insights/cost")).json()
        rank_group = next(g for g in cumulative["groups"] if g["runLabel"] == "Discover criteria & rank")
        cumulative_labels = {p["passLabel"] for p in rank_group["passes"]}

        last = (await client.get("/insights/last-runs")).json()["rank"]
        ledger_labels = {p["label"] for p in last["passes"]}

    assert cumulative_labels == set(RANK_PASS_LABELS)
    assert ledger_labels == set(RANK_PASS_LABELS)


@pytest.mark.anyio
async def test_insights_metrics_trends_after_a_rank() -> None:
    # Pillar 3: after a Rank, the metrics endpoint reports a per-run trend point with
    # captured latency, the live dimension count, and a per-pass breakdown.
    app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        route_criteria(provider, a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")

        metrics = (await client.get("/insights/metrics")).json()
        assert len(metrics["runs"]) == 1
        run = metrics["runs"][0]
        assert run["kind"] == "rank"
        assert run["costUsd"] > 0
        # Latency is measured (wall-clock ms); a real pass takes nonzero time.
        assert run["durationMs"] >= 0
        assert run["failedCalls"] == 0
        # a_pattern_report has 2 dimensions; the live count carries through.
        assert run["dimensions"] == 2
        # Per-pass series covers this run's passes, each with its own duration slot.
        labels = {p["label"] for p in metrics["passes"]}
        assert labels == set(RANK_PASS_LABELS)


@pytest.mark.anyio
async def test_ranking_before_discovery_is_409() -> None:
    app, db, _ = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/ranking")).status_code == 409


@pytest.mark.anyio
async def test_ranking_orders_pool_and_seeds_equal_weights() -> None:
    app, db, provider = setup_app(role=UserRole.MEMBER)
    weak = add_eligible(db, email="weak@x.com", raw_hash="h1")
    strong = add_eligible(db, email="strong@x.com", raw_hash="h2")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Drive the whole chain; bind each candidate's scores by the applicant_id
        # marker in the scoring prompt (scoring fans out concurrently).
        route_criteria(provider, a_pattern_report())
        provider.route(f'"applicant_id": {weak.id}', _scoring_report(commitment=0.2, skills=0.2))
        provider.route(f'"applicant_id": {strong.id}', _scoring_report(commitment=0.9, skills=0.9))
        await stream_events(client, "/ranking/run")

        ranking = (await client.get("/ranking")).json()

        # Equal-weight baseline: both dimensions weight 1.0, no AI-proposed weight.
        assert ranking["weights"] == {
            "participation_commitment": 1.0,
            "skills_offered": 1.0,
        }
        # Strong candidate leads; fit is the plain average under equal weights.
        candidates = ranking["candidates"]
        assert [c["applicationId"] for c in candidates] == [strong.id, weak.id]
        assert candidates[0]["fit"] == 0.9
        assert candidates[0]["band"] == "Strong fit"


async def stream_events(client: AsyncClient, url: str) -> list[dict]:
    """All NDJSON events from a streaming POST, in order."""
    response = await client.post(url)
    assert response.status_code == 200
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


@pytest.mark.anyio
async def test_rank_chain_runs_criteria_scores() -> None:
    app, db, provider = setup_app(role=UserRole.MEMBER)
    weak = add_eligible(db, email="weak@x.com", raw_hash="h1")
    strong = add_eligible(db, email="strong@x.com", raw_hash="h2")

    # Route by prompt content: discovery carries "<applicant_pool>", scoring is
    # bound to each applicant by the applicant_id marker.
    route_criteria(provider, a_pattern_report())
    provider.route(
        f'"applicant_id": {weak.id}', _scoring_report(commitment=0.2, skills=0.2)
    )
    provider.route(
        f'"applicant_id": {strong.id}', _scoring_report(commitment=0.9, skills=0.9)
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        events = await stream_events(client, "/ranking/run")

        # The phases are announced in order (consolidation runs post-score, always
        # emitting its phase even when it merges nothing).
        phases = [e["phase"] for e in events if e["type"] == "phase"]
        assert phases == ["criteria", "scores", "consolidate"]

        summary = next(e for e in events if e["type"] == "summary")
        assert summary["dimensions"] == 2
        assert summary["scored"] == 2
        assert summary["failed"] == 0

        # The chain produced a current run and a full ranking, strong above weak.
        ranking = (await client.get("/ranking")).json()
        assert [c["applicationId"] for c in ranking["candidates"]] == [strong.id, weak.id]


@pytest.mark.anyio
async def test_rank_criteria_failure_aborts_before_scoring() -> None:
    # A fatal criteria failure (here: no discovery result routed → every fan-out worker
    # raises → discover_patterns_fanout re-raises) must emit an `error` on the criteria
    # phase and stop the stream — no scores/consolidate phase, no summary. Guards the
    # criteria-phase abort path (a fatal criteria error returns None to rank_run, which
    # returns immediately rather than scoring against nonexistent criteria).
    app, db, _provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    # Deliberately route nothing: the discovery call has no queued result and raises.

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        events = await stream_events(client, "/ranking/run")

    kinds = [e["type"] for e in events]
    assert "error" in kinds
    error = next(e for e in events if e["type"] == "error")
    assert error["phase"] == "criteria"
    # The chain aborted at criteria: scoring never started, no summary was emitted.
    assert "summary" not in kinds
    assert "scores" not in [e.get("phase") for e in events if e["type"] == "phase"]


@pytest.mark.anyio
async def test_rank_runs_k_parallel_discoveries_and_persists_reports() -> None:
    # Fan-Out Redesign Phase 2: a Rank runs K (default 4) parallel discovery calls and
    # persists all K raw reports under criteria.fan_out_audit — the input Phase 3's
    # decomposition step consumes. MockProvider returns the routed report for every
    # discovery call (same prompt), so we verify the COUNT and persistence here;
    # cross-call diversity needs real Bedrock (the Phase 3 bake-off).
    from app.schemas.settings import AISettings
    from app.services.ranking_run import get_current_run

    app, db, provider = setup_app(role=UserRole.MEMBER)
    a = add_eligible(db, email="a@x.com", raw_hash="h1")
    route_criteria(provider, a_pattern_report())
    provider.route(f'"applicant_id": {a.id}', _scoring_report(commitment=0.5, skills=0.5))

    k = AISettings().discovery_fan_out  # the shipped default
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await stream_events(client, "/ranking/run")

    run = get_current_run(db)
    audit = (run.audit.fan_out if run.audit else None)
    assert audit is not None, "fan_out_audit must be persisted"
    assert audit["k"] == k
    assert len(audit["passes"]) == k
    # Each persisted pass carries its report (with dimensions) AND its own narrative
    # key — all K discoverers are kept, not just the one that streamed live.
    assert all(p["report"]["dimensions"] for p in audit["passes"])
    assert all("narrative" in p for p in audit["passes"])
    # K discovery calls actually hit the provider (K + scoring). Discovery
    # calls carry the pool block; count them to prove the fan-out really fanned out.
    discovery_calls = [c for c in provider.calls if "<applicant_pool>" in c.prompt]
    assert len(discovery_calls) == k


@pytest.mark.anyio
async def test_decomposition_merges_axes_and_records_the_merge() -> None:
    # Fan-Out Redesign Phase 4a: the decomposition step settles the K discovery reports
    # into one set BEFORE scoring. Here discovery emits 3 axes but decomposition merges
    # two into one, so the run must end with 2 settled dims (not 3), score against those,
    # and record the merge (source_keys + reasoning) in criteria.decompose_audit.
    from app.services.ranking_run import get_current_run

    app, db, provider = setup_app(role=UserRole.MEMBER)
    a = add_eligible(db, email="a@x.com", raw_hash="h1")

    discovered = PoolDimensionReport(
        dimensions=[
            PoolDimension(key="commitment_a", name="Commitment A",
                          definition="willingness to do shared work",
                          high_end="high", low_end="low", why_it_differentiates="varies"),
            PoolDimension(key="commitment_b", name="Commitment B",
                          definition="willingness to show up for work days",
                          high_end="high", low_end="low", why_it_differentiates="varies"),
            PoolDimension(key="skills_offered", name="Skills offered",
                          definition="concrete skills", high_end="high", low_end="low", why_it_differentiates="varies"),
        ],
    )
    # Decomposition folds commitment_a + commitment_b into one settled axis; skills stays.
    settled = DecompositionReport(
        dimensions=[
            DecomposedDimension(
                key="commitment", name="Commitment",
                definition="willingness to do shared work",
                high_end="high", low_end="low",
                source_keys=["commitment_a", "commitment_b"],
                decision="commitment_a and commitment_b score the same applicant alike — one axis.",
            ),
            DecomposedDimension(
                key="skills_offered", name="Skills offered",
                definition="concrete skills",
                high_end="high", low_end="low",
                source_keys=["skills_offered"], decision="distinct — kept.",
            ),
        ],
    )
    provider.route("<applicant_pool>", discovered)
    provider.route("<discovery_reports>", settled)
    provider.route(
        f'"applicant_id": {a.id}',
        DimensionScoringReport(scores=[
            DimensionScore(dimension_key="commitment", score=0.7, rationale="r",
                           evidence="", confidence=ScoreConfidence.MEDIUM),
            DimensionScore(dimension_key="skills_offered", score=0.3, rationale="r",
                           evidence="", confidence=ScoreConfidence.MEDIUM),
        ]),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        summary = next(
            e for e in await stream_events(client, "/ranking/run") if e["type"] == "summary"
        )
        # The run settled to 2 dims (the merge collapsed 3 → 2), not the 3 discovered.
        assert summary["dimensions"] == 2

        # The decompose-audit endpoint surfaces the merge (the Insights panel's source).
        endpoint = (await client.get("/ranking/current/decompose-audit")).json()
        assert endpoint["mergeCount"] == 1
        assert endpoint["settledCount"] == 2
        merged_out = next(d for d in endpoint["settled"] if d["key"] == "commitment")
        assert set(merged_out["sourceKeys"]) == {"commitment_a", "commitment_b"}

    run = get_current_run(db)
    stored_dims = run.dimension_report["dimensions"]
    settled_keys = {d["key"] for d in stored_dims}
    assert settled_keys == {"commitment", "skills_offered"}

    # The settled 'commitment' axis carries the pool-grounded why from its PRIMARY
    # source discoverer (commitment_a), not a decomposer-written one — the decomposer
    # never saw the pool. (discovered's commitment_a why is "varies" here.)
    commitment = next(d for d in stored_dims if d["key"] == "commitment")
    commitment_a_why = next(
        d.why_it_differentiates for d in discovered.dimensions if d.key == "commitment_a"
    )
    assert commitment["why_it_differentiates"] == commitment_a_why

    # The merge is recorded for audit: the settled 'commitment' lists both source keys.
    audit = (run.audit.decompose if run.audit else None)
    assert audit is not None
    assert audit["merge_count"] == 1
    merged = next(d for d in audit["settled"] if d["key"] == "commitment")
    assert set(merged["source_keys"]) == {"commitment_a", "commitment_b"}


@pytest.mark.anyio
async def test_post_score_consolidation_merges_correlated_duplicate() -> None:
    # The consolidation pass runs AFTER scoring: two dimensions whose per-applicant
    # scores correlate are nominated, the confirm call says same_concept, and the run
    # collapses to one dim + writes a DimensionAlias so future matches adopt the winner.
    from sqlalchemy import select

    from app.db.models import DimensionAlias
    from app.services.ranking_run import get_current_run

    app, db, provider = setup_app(role=UserRole.MEMBER)
    apps = [add_eligible(db, email=f"a{i}@x.com", raw_hash=f"h{i}") for i in range(4)]

    discovered = PoolDimensionReport(
        dimensions=[
            PoolDimension(key="financial_literacy", name="Financial literacy",
                          definition="handles co-op money", high_end="high", low_end="low", why_it_differentiates="varies"),
            PoolDimension(key="financial_stewardship", name="Financial stewardship",
                          definition="bookkeeping and oversight", high_end="high", low_end="low", why_it_differentiates="varies"),
        ],
    )
    provider.route("<applicant_pool>", discovered)
    provider.route("<discovery_reports>", _decomposition_of(discovered))
    # Give the two dims near-identical per-applicant scores so they correlate ≥ 0.85.
    scores = [0.1, 0.4, 0.7, 0.95]
    for a, s in zip(apps, scores):
        provider.route(
            f'"applicant_id": {a.id}',
            DimensionScoringReport(scores=[
                DimensionScore(dimension_key="financial_literacy", score=s, rationale="r",
                               evidence="", confidence=ScoreConfidence.MEDIUM),
                DimensionScore(dimension_key="financial_stewardship", score=s, rationale="r",
                               evidence="", confidence=ScoreConfidence.MEDIUM),
            ]),
        )
    # The confirm call: these two are the same concept → merge.
    provider.route(
        "<candidate_pairs>",
        ConsolidationReport(verdicts=[
            ConsolidationVerdict(
                key_a="financial_literacy", key_b="financial_stewardship",
                same_concept=True, reason="both measure handling co-op finances",
            ),
        ]),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await stream_events(client, "/ranking/run")

    run = get_current_run(db)
    keys = {d["key"] for d in run.dimension_report["dimensions"]}
    # Collapsed 2 → 1: the newer key (financial_stewardship) is aliased into the older.
    assert keys == {"financial_literacy"}

    # merges isn't stored on the audit; the view derives it from the merged pairs.
    from app.services.ranking_run import consolidate_audit_view
    view = consolidate_audit_view(db, run)
    assert view["merges"] == {"financial_stewardship": "financial_literacy"}

    alias = db.scalar(select(DimensionAlias).where(DimensionAlias.alias_key == "financial_stewardship"))
    assert alias is not None
    assert alias.canonical_key == "financial_literacy"


@pytest.mark.anyio
async def test_consolidation_streams_thinking_deltas() -> None:
    # The confirm call is opaque (no per-item progress), so — like the criteria phase —
    # it streams the model's reasoning as thinking events tagged with the consolidate
    # phase, and they arrive AFTER the consolidate phase announcement. The UI appends
    # these to the same reasoning box the criteria phase filled.
    app, db, provider = setup_app(role=UserRole.MEMBER)
    apps = [add_eligible(db, email=f"a{i}@x.com", raw_hash=f"h{i}") for i in range(4)]

    discovered = PoolDimensionReport(
        dimensions=[
            PoolDimension(key="financial_literacy", name="Financial literacy",
                          definition="handles co-op money", high_end="high", low_end="low", why_it_differentiates="varies"),
            PoolDimension(key="financial_stewardship", name="Financial stewardship",
                          definition="bookkeeping and oversight", high_end="high", low_end="low", why_it_differentiates="varies"),
        ],
    )
    provider.route("<applicant_pool>", discovered)
    provider.route("<discovery_reports>", _decomposition_of(discovered))
    # Correlated scores → the confirm call fires (a no-op consolidation makes no call
    # and would stream nothing).
    scores = [0.1, 0.4, 0.7, 0.95]
    for a, s in zip(apps, scores):
        provider.route(
            f'"applicant_id": {a.id}',
            DimensionScoringReport(scores=[
                DimensionScore(dimension_key="financial_literacy", score=s, rationale="r",
                               evidence="", confidence=ScoreConfidence.MEDIUM),
                DimensionScore(dimension_key="financial_stewardship", score=s, rationale="r",
                               evidence="", confidence=ScoreConfidence.MEDIUM),
            ]),
        )
    provider.route(
        "<candidate_pairs>",
        ConsolidationReport(verdicts=[
            ConsolidationVerdict(
                key_a="financial_literacy", key_b="financial_stewardship",
                same_concept=True, reason="both measure handling co-op finances",
            ),
        ]),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        events = await stream_events(client, "/ranking/run")

    consolidate_thinking = [
        e for e in events if e["type"] == "thinking" and e["phase"] == "consolidate"
    ]
    assert consolidate_thinking, "expected streamed consolidation thinking deltas"
    # The section opens with a horizontal rule to separate it from the criteria
    # reasoning already in the box, then streams real reasoning text.
    assert consolidate_thinking[0]["text"] == "\n\n---\n\n"
    assert "".join(e["text"] for e in consolidate_thinking[1:])  # non-empty reasoning text

    # The deltas arrive after the consolidate phase is announced (not before it).
    consolidate_phase_idx = next(
        i for i, e in enumerate(events) if e["type"] == "phase" and e["phase"] == "consolidate"
    )
    first_consolidate_thinking_idx = next(
        i for i, e in enumerate(events)
        if e["type"] == "thinking" and e["phase"] == "consolidate"
    )
    assert consolidate_phase_idx < first_consolidate_thinking_idx


def test_apply_consolidation_transfers_tier_placement_off_a_merged_key() -> None:
    # "Kept" is derived from tier placement, so a merge must carry the committee's tier
    # intent from the dropped twin to the survivor — otherwise a member's placement (and
    # the keep guarantee it confers) would silently vanish with the dropped key.
    from app.schemas.settings import AppSettings
    from app.services.ranking_run import (
        apply_consolidation,
        create_run,
        kept_keys,
        set_tiers,
    )

    _app, db, _ = setup_app(role=UserRole.MEMBER)
    report = PoolDimensionReport(dimensions=[
        PoolDimension(key="financial_literacy", name="Financial literacy",
                      definition="handles money", high_end="high", low_end="low", why_it_differentiates="v"),
        PoolDimension(key="financial_stewardship", name="Financial stewardship",
                      definition="bookkeeping", high_end="high", low_end="low", why_it_differentiates="v"),
    ])
    run = create_run(db, report=report, settings=AppSettings(), narrative=None)
    # The committee places ONLY the key that will be merged away into a working tier —
    # the survivor sits in Ignore (unplaced).
    set_tiers(db, run, [{"id": "tier-s", "label": "Critical",
                         "dimension_keys": ["financial_stewardship"]}])
    assert kept_keys(run) == ["financial_stewardship"]

    apply_consolidation(
        db, run,
        merges={"financial_stewardship": "financial_literacy"},
        audit=[{"keep": "financial_literacy", "drop": "financial_stewardship",
                "r": 0.94, "merged": True, "reason": "same concept"}],
        narrative=None,
    )
    # The survivor inherited the dropped twin's Critical placement, so it stays kept.
    assert kept_keys(run) == ["financial_literacy"]
    keys = {d["key"] for d in run.dimension_report["dimensions"]}
    assert keys == {"financial_literacy"}
    assert run.run_state["tiers"][0]["dimension_keys"] == ["financial_literacy"]


def test_apply_consolidation_reconfirming_an_existing_alias_is_idempotent() -> None:
    # Matching is high-bar, so a merged key can be re-minted and re-nominated on a later
    # run. Re-confirming the SAME merge must upsert the alias, not crash on the UNIQUE
    # constraint (the bug that 500'd a real rank).
    from sqlalchemy import select

    from app.db.models import DimensionAlias
    from app.schemas.settings import AppSettings
    from app.services.ranking_run import apply_consolidation, create_run

    _app, db, _ = setup_app(role=UserRole.MEMBER)

    def run_with_merge(reason: str) -> None:
        report = PoolDimensionReport(dimensions=[
            PoolDimension(key="financial_literacy", name="FL", definition="d", high_end="high", low_end="low", why_it_differentiates="v"),
            PoolDimension(key="financial_stewardship", name="FS", definition="d", high_end="high", low_end="low", why_it_differentiates="v"),
        ])
        run = create_run(db, report=report, settings=AppSettings(),
                         narrative=None)
        apply_consolidation(
            db, run,
            merges={"financial_stewardship": "financial_literacy"},
            audit=[{"keep": "financial_literacy", "drop": "financial_stewardship",
                    "r": 0.94, "merged": True, "reason": reason}],
            narrative=None,
        )

    run_with_merge("first time")
    run_with_merge("re-minted and re-confirmed")  # would UNIQUE-crash before the upsert fix

    aliases = list(db.scalars(select(DimensionAlias).where(
        DimensionAlias.alias_key == "financial_stewardship")))
    assert len(aliases) == 1  # upserted, not duplicated
    assert aliases[0].canonical_key == "financial_literacy"
    assert aliases[0].reason == "re-minted and re-confirmed"  # latest reason kept


def test_apply_consolidation_flattens_an_in_run_chain() -> None:
    # A single run can confirm a chain: {C: B, B: A} when C↔B correlates higher than
    # B↔A. Every drop must resolve to the terminal survivor A — including the tier
    # placement on the innermost key C, which would otherwise land on B, itself dropped
    # from the run.
    from sqlalchemy import select

    from app.db.models import DimensionAlias
    from app.schemas.settings import AppSettings
    from app.services.ranking_run import (
        apply_consolidation,
        create_run,
        kept_keys,
        set_tiers,
    )

    _app, db, _ = setup_app(role=UserRole.MEMBER)
    report = PoolDimensionReport(dimensions=[
        PoolDimension(key="a_oldest", name="A", definition="d", high_end="high", low_end="low", why_it_differentiates="v"),
        PoolDimension(key="b_mid", name="B", definition="d", high_end="high", low_end="low", why_it_differentiates="v"),
        PoolDimension(key="c_newest", name="C", definition="d", high_end="high", low_end="low", why_it_differentiates="v"),
    ])
    run = create_run(db, report=report, settings=AppSettings(), narrative=None)
    # Place ONLY the innermost link C in a working tier; A and B sit in Ignore.
    set_tiers(db, run, [{"id": "tier-s", "label": "Critical", "dimension_keys": ["c_newest"]}])

    apply_consolidation(
        db, run,
        merges={"c_newest": "b_mid", "b_mid": "a_oldest"},  # chain, not a flat map
        audit=[
            {"keep": "b_mid", "drop": "c_newest", "r": 0.95, "merged": True, "reason": "c=b"},
            {"keep": "a_oldest", "drop": "b_mid", "r": 0.88, "merged": True, "reason": "b=a"},
        ],
        narrative=None,
    )

    # Only the terminal survivor remains, and C's placement followed the full chain to it.
    keys = {d["key"] for d in run.dimension_report["dimensions"]}
    assert keys == {"a_oldest"}
    assert kept_keys(run) == ["a_oldest"]
    assert run.run_state["tiers"][0]["dimension_keys"] == ["a_oldest"]
    # Both aliases point straight at the survivor — no mid-chain key persisted.
    aliases = {a.alias_key: a.canonical_key for a in db.scalars(select(DimensionAlias))}
    assert aliases == {"c_newest": "a_oldest", "b_mid": "a_oldest"}


def test_apply_consolidation_surfaces_a_prior_key_on_a_cross_run_heal() -> None:
    # Cross-run fork heal: this run discovered only the NEWER twin (child_age_profile);
    # the definition-match pass missed the fork, so the surviving canonical key
    # (child_age_profile_community_fit, a PRIOR-run key) is NOT in this run's report.
    # Consolidation must drop the newer twin AND surface the canonical prior key with its
    # frozen MINT record, restored to the tier the committee last placed it in — never
    # rename the twin (keys must not be mixed up). Regression for the bug where the axis
    # vanished from the report entirely while the Insights panel showed the merge.
    from sqlalchemy import select

    from app.db.models import DimensionAlias
    from app.schemas.settings import AppSettings
    from app.services.ranking_run import (
        apply_consolidation,
        create_run,
        dimension_weights,
    )

    _app, db, _ = setup_app(role=UserRole.MEMBER)
    canonical_def = "Ages of children, reflecting shared-space interaction and supervision load."

    # Run 1: mint the canonical key and place it in the Important tier.
    create_run(
        db,
        report=PoolDimensionReport(dimensions=[
            PoolDimension(key="child_age_profile_community_fit", name="Children's Age Profile",
                          definition=canonical_def, high_end="school-age+", low_end="all under 3",
                          why_it_differentiates="ages span the pool"),
        ]),
        settings=AppSettings(), narrative=None,
        tier_layout=[
            {"id": "tier-s", "label": "Critical", "dimension_keys": []},
            {"id": "tier-a", "label": "Important", "dimension_keys": ["child_age_profile_community_fit"]},
            {"id": "tier-b", "label": "Minor", "dimension_keys": []},
        ],
    )

    # Run 2: only the NEWER twin surfaces (match missed the fork). Its wording differs —
    # if the heal renamed it, that re-worded text would ride under the canonical key.
    run2 = create_run(
        db,
        report=PoolDimensionReport(dimensions=[
            PoolDimension(key="child_age_profile", name="Household Children's Ages",
                          definition="A re-worded, differently-scoped take on child ages.",
                          high_end="teens", low_end="infants", why_it_differentiates="v"),
        ]),
        settings=AppSettings(), narrative=None,
    )

    apply_consolidation(
        db, run2,
        merges={"child_age_profile": "child_age_profile_community_fit"},
        audit=[{"keep": "child_age_profile_community_fit", "drop": "child_age_profile",
                "r": 0.803, "merged": True, "reason": "same age axis"}],
        narrative=None,
    )

    dims = {d["key"]: d for d in run2.dimension_report["dimensions"]}
    # The newer twin is gone; the canonical prior key is surfaced in its place.
    assert set(dims) == {"child_age_profile_community_fit"}
    # Surfaced with its FROZEN MINT record — never the twin's re-worded text.
    assert dims["child_age_profile_community_fit"]["definition"] == canonical_def
    # Restored to the working tier the committee last placed it in (Important).
    tiers = {t["id"]: t["dimension_keys"] for t in run2.run_state["tiers"]}
    assert tiers["tier-a"] == ["child_age_profile_community_fit"]
    # Weight is derived for the surfaced key, not the dropped twin.
    weights = dimension_weights(run2)
    assert "child_age_profile_community_fit" in weights
    assert "child_age_profile" not in weights
    # The alias still points the newer twin at the canonical key for future matches.
    aliases = {a.alias_key: a.canonical_key for a in db.scalars(select(DimensionAlias))}
    assert aliases == {"child_age_profile": "child_age_profile_community_fit"}


def test_consolidate_audit_view_resolves_pair_names() -> None:
    # The view labels each pair by name. It prefers the snapshotted name, then falls back
    # to a resolved name so a pair written BEFORE name capture (no name_keep/name_drop in
    # the stored audit) still shows names: a key present in a report resolves via history,
    # and a key minted-and-retired within this run (never in any report) resolves via the
    # run's own decompose artifacts. Only a truly traceless key stays a bare key.
    from app.schemas.settings import AppSettings
    from app.services.ranking_run import consolidate_audit_view, create_run

    _app, db, _ = setup_app(role=UserRole.MEMBER)

    def _dim(key: str, name: str) -> PoolDimension:
        return PoolDimension(key=key, name=name, definition="d",
                             high_end="hi", low_end="lo", why_it_differentiates="v")

    # A run whose report has the survivor key, whose decompose audit names a key that was
    # retired within the run (so it's in no report), and whose consolidate_audit pairs
    # carry NO snapshotted names (the pre-capture shape).
    run = create_run(
        db,
        report=PoolDimensionReport(dimensions=[_dim("survivor", "Survivor Axis")]),
        settings=AppSettings(), narrative=None,
    )
    run.audit.decompose = {
        "settled": [{"key": "retired_within_run", "name": "Retired Within Run", "source_keys": []}],
    }
    run.audit.consolidate = {
        "pairs": [
            # No name_keep/name_drop — the old audit shape.
            {"keep": "survivor", "drop": "retired_within_run", "r": 0.9, "merged": True, "reason": "same"},
            {"keep": "survivor", "drop": "traceless", "r": 0.87, "merged": False, "reason": "confound"},
        ],
        "narrative": None,
    }
    db.commit()

    view = consolidate_audit_view(db, run)
    by_drop = {p["drop"]: p for p in view["pairs"]}
    # Survivor resolves from its report (via history); retired-within-run from the run's
    # own decompose names; a key with no trace anywhere stays "" (UI → bare key).
    assert by_drop["retired_within_run"]["keep_name"] == "Survivor Axis"
    assert by_drop["retired_within_run"]["drop_name"] == "Retired Within Run"
    assert by_drop["traceless"]["drop_name"] == ""
    # merges is derived from the merged pairs (dimension_aliases is the truth).
    assert view["merges"] == {"retired_within_run": "survivor"}


def test_consolidate_audit_view_prefers_the_snapshotted_name() -> None:
    # When a pair DOES carry a snapshotted name (the current write path), the view uses it
    # verbatim — the snapshot is the frozen mint name and must win over any later re-name.
    from app.schemas.settings import AppSettings
    from app.services.ranking_run import consolidate_audit_view, create_run

    _app, db, _ = setup_app(role=UserRole.MEMBER)
    run = create_run(
        db,
        report=PoolDimensionReport(dimensions=[PoolDimension(
            key="survivor", name="Later Renamed", definition="d",
            high_end="hi", low_end="lo", why_it_differentiates="v")]),
        settings=AppSettings(), narrative=None,
    )
    run.audit.consolidate = {
        "pairs": [{
            "keep": "survivor", "drop": "gone", "r": 0.9, "merged": False, "reason": "r",
            "name_keep": "Snapshot Keep Name", "name_drop": "Snapshot Drop Name",
        }],
        "narrative": None,
    }
    db.commit()

    view = consolidate_audit_view(db, run)
    p = view["pairs"][0]
    assert p["keep_name"] == "Snapshot Keep Name"  # snapshot wins over the report's "Later Renamed"
    assert p["drop_name"] == "Snapshot Drop Name"


def test_merged_alias_does_not_donate_its_definition_to_the_canonical_key() -> None:
    # Key/text immutability: a key's descriptive text is frozen at mint, because the
    # score cache is keyed by key and scores were computed against that text. Regression
    # for the real leak: a broad hands_on_trade was aliased onto narrow licensed_trade,
    # then a LATER run re-surfaced only the broad concept — so history built newest-first
    # (and keyed by mint definition oldest-first) must still report licensed_trade with
    # its NARROW mint text, never the broad donation, else the definition divorces from
    # the narrow-computed cached scores. Both history builders (all_known_dimensions for
    # match, key_history for consolidation) must hold the invariant.
    from app.schemas.settings import AppSettings
    from app.services.ranking_run import (
        all_known_dimensions,
        apply_consolidation,
        create_run,
        key_history,
    )

    _app, db, _ = setup_app(role=UserRole.MEMBER)
    narrow = "Formal licensed trade qualifications only (legally-regulated work)."
    broad = "Any licensed OR practised hands-on trade skill, incl. unlicensed crafts."

    def _dim(key: str, definition: str) -> PoolDimension:
        return PoolDimension(key=key, name=key, definition=definition,
                             high_end="hi", low_end="lo", why_it_differentiates="v")

    # Run 1: mint the narrow key. Its cached scores (not modelled here) belong to THIS text.
    create_run(db, report=PoolDimensionReport(dimensions=[_dim("licensed_trade", narrow)]),
               settings=AppSettings(), narrative=None)
    # Run 2: a broader duplicate appears alongside, and is merged INTO the narrow key
    # (older key wins the merge). This writes the alias hands_on_trade -> licensed_trade.
    run2 = create_run(db, report=PoolDimensionReport(dimensions=[
        _dim("licensed_trade", narrow), _dim("hands_on_trade", broad),
    ]), settings=AppSettings(), narrative=None)
    apply_consolidation(
        db, run2,
        merges={"hands_on_trade": "licensed_trade"},
        audit=[{"keep": "licensed_trade", "drop": "hands_on_trade", "r": 0.93,
                "merged": True, "reason": "same axis"}],
        narrative=None,
    )
    # Run 3: the broad concept re-surfaces under its OWN key, and the canonical narrow key
    # does NOT appear on its own. This is the trigger: a newest-first history builder would
    # reach the broad re-discovery (resolved via alias to licensed_trade) BEFORE the narrow
    # canonical's own mint, and donate the broad text to the narrow key.
    create_run(db, report=PoolDimensionReport(dimensions=[_dim("hands_on_trade", broad)]),
               settings=AppSettings(), narrative=None)

    # all_known_dimensions (match target set) must report the NARROW mint.
    known = all_known_dimensions(db)
    lt = next(d for d in known.dimensions if d.key == "licensed_trade")
    assert lt.definition == narrow, "match history donated the broad def onto the narrow key"
    assert not any(d.key == "hands_on_trade" for d in known.dimensions), "alias key re-entered"

    # key_history (consolidation confirm input) must ALSO report the NARROW mint.
    _rank, defs, _names = key_history(db)
    assert defs["licensed_trade"] == narrow, "key_history donated/drifted the broad def"


@pytest.mark.anyio
async def test_post_score_consolidation_keeps_confound_apart() -> None:
    # A nominated pair the confirm call rejects (a confound) is NOT merged: both dims
    # survive and no alias is written, even though their scores correlate.
    from sqlalchemy import select

    from app.db.models import DimensionAlias
    from app.services.ranking_run import get_current_run

    app, db, provider = setup_app(role=UserRole.MEMBER)
    apps = [add_eligible(db, email=f"b{i}@x.com", raw_hash=f"hb{i}") for i in range(4)]

    discovered = PoolDimensionReport(
        dimensions=[
            PoolDimension(key="motivation", name="Motivation",
                          definition="why they want in", high_end="high", low_end="low", why_it_differentiates="varies"),
            PoolDimension(key="followthrough", name="Follow-through",
                          definition="do they finish tasks", high_end="high", low_end="low", why_it_differentiates="varies"),
        ],
    )
    provider.route("<applicant_pool>", discovered)
    provider.route("<discovery_reports>", _decomposition_of(discovered))
    for a, s in zip(apps, [0.2, 0.5, 0.8, 0.9]):
        provider.route(
            f'"applicant_id": {a.id}',
            DimensionScoringReport(scores=[
                DimensionScore(dimension_key="motivation", score=s, rationale="r",
                               evidence="", confidence=ScoreConfidence.MEDIUM),
                DimensionScore(dimension_key="followthrough", score=s, rationale="r",
                               evidence="", confidence=ScoreConfidence.MEDIUM),
            ]),
        )
    provider.route(
        "<candidate_pairs>",
        ConsolidationReport(verdicts=[
            ConsolidationVerdict(
                key_a="motivation", key_b="followthrough",
                same_concept=False, reason="an eager applicant who never finishes splits them",
            ),
        ]),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await stream_events(client, "/ranking/run")

    run = get_current_run(db)
    keys = {d["key"] for d in run.dimension_report["dimensions"]}
    assert keys == {"motivation", "followthrough"}  # both kept
    # No pair merged (merges is derived from merged pairs — dimension_aliases is the truth).
    assert not any(p.get("merged") for p in run.audit.consolidate["pairs"])
    assert db.scalar(select(DimensionAlias)) is None


def _discovery_with_committee_request() -> PoolDimensionReport:
    """A discovery report with one committee-requested axis (playground) plus a sibling
    it could tempt a merge with (child_wellbeing)."""
    return PoolDimensionReport(
        dimensions=[
            PoolDimension(key="playground_use", name="Playground use",
                          definition="school-age kids who'd use the playground",
                          high_end="high", low_end="low", why_it_differentiates="varies", from_committee_request=True),
            PoolDimension(key="child_wellbeing", name="Child wellbeing",
                          definition="general child-centred motivation",
                          high_end="high", low_end="low", why_it_differentiates="varies"),
        ],
    )


@pytest.mark.anyio
async def test_d9_committee_request_folded_into_merge_is_surfaced_not_lost() -> None:
    # D9: if decomposition MERGES a committee-requested axis into another and (as models
    # do) drops the from_committee_request flag, the guard restores the flag AND records
    # the fold in decompose_audit.folded_requests — surfaced to the committee, never a
    # silent disappearance.
    from app.services.ranking_run import get_current_run

    app, db, provider = setup_app(role=UserRole.MEMBER)
    a = add_eligible(db, email="a@x.com", raw_hash="h1")
    # Decomposition folds the requested playground_use into child_wellbeing AND (the
    # failure the guard must catch) returns the merged axis with the flag false.
    settled = DecompositionReport(
        dimensions=[
            DecomposedDimension(
                key="child_wellbeing", name="Child wellbeing",
                definition="child-centred motivation incl. playground",
                high_end="high", low_end="low",
                source_keys=["child_wellbeing", "playground_use"],
                from_committee_request=False,  # model dropped it — guard must repair
                decision="folded playground_use in — same underlying concept",
            ),
        ],
    )
    provider.route("<applicant_pool>", _discovery_with_committee_request())
    provider.route("<discovery_reports>", settled)
    provider.route(
        f'"applicant_id": {a.id}',
        DimensionScoringReport(scores=[
            DimensionScore(dimension_key="child_wellbeing", score=0.5, rationale="r",
                           evidence="", confidence=ScoreConfidence.MEDIUM),
        ]),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await stream_events(client, "/ranking/run")

    run = get_current_run(db)
    audit = run.audit.decompose
    # The fold is surfaced: playground_use -> child_wellbeing.
    assert {"request_key": "playground_use", "into_key": "child_wellbeing"} in audit["folded_requests"]
    # The flag was repaired on the settled axis (drives the D9 trail + the badge).
    settled_axis = next(d for d in audit["settled"] if d["key"] == "child_wellbeing")
    assert settled_axis["from_committee_request"] is True


@pytest.mark.anyio
async def test_d9_silently_dropped_committee_request_is_re_added() -> None:
    # D9: if decomposition drops a committee-requested axis entirely (its key appears in
    # NO settled source_keys), the guard re-adds it as its own settled axis so it cannot
    # vanish.
    from app.services.ranking_run import get_current_run

    app, db, provider = setup_app(role=UserRole.MEMBER)
    a = add_eligible(db, email="a@x.com", raw_hash="h1")
    # Decomposition returns ONLY child_wellbeing — playground_use (requested) is gone.
    settled = DecompositionReport(
        dimensions=[
            DecomposedDimension(
                key="child_wellbeing", name="Child wellbeing",
                definition="child-centred motivation",
                high_end="high", low_end="low",
                source_keys=["child_wellbeing"], decision="kept",
            ),
        ],
    )
    provider.route("<applicant_pool>", _discovery_with_committee_request())
    provider.route("<discovery_reports>", settled)
    provider.route(
        f'"applicant_id": {a.id}',
        DimensionScoringReport(scores=[
            DimensionScore(dimension_key="child_wellbeing", score=0.5, rationale="r",
                           evidence="", confidence=ScoreConfidence.MEDIUM),
            DimensionScore(dimension_key="playground_use", score=0.6, rationale="r",
                           evidence="", confidence=ScoreConfidence.MEDIUM),
        ]),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await stream_events(client, "/ranking/run")

    run = get_current_run(db)
    keys = {d["key"] for d in run.dimension_report["dimensions"]}
    # The dropped request was re-added, so both axes survive.
    assert keys == {"child_wellbeing", "playground_use"}
    readded = next(
        d for d in run.audit.decompose["settled"] if d["key"] == "playground_use"
    )
    assert readded["from_committee_request"] is True


def test_fan_out_seeds_only_worker_0_the_rest_stay_blind() -> None:
    # Proposals steer ONE discoverer (worker 0); workers 1..K-1 stay blind, preserving
    # K-1 independent samples. Assert exactly one of K prompts carries the proposal.
    from app.ai.pattern_discovery import DiscoverySeeds, discover_patterns_fanout

    _app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    from app.ai.pattern_discovery import eligible_applications

    pool = eligible_applications(db)
    k = 4
    for _ in range(k):
        provider.queue(a_pattern_report())

    from app.schemas.settings import AppSettings

    seeds = DiscoverySeeds(proposed=["families who'd use the playground"])
    discover_patterns_fanout(
        provider, applications=pool, settings=AppSettings(), k=k, seeds=seeds,
    )
    discovery_calls = [c for c in provider.calls if "<applicant_pool>" in c.prompt]
    assert len(discovery_calls) == k
    seeded = [c for c in discovery_calls if "families who'd use the playground" in c.prompt]
    assert len(seeded) == 1, "exactly one discoverer should carry the proposal"


def test_enforce_committee_requests_guarantees_an_unsurfaced_kept_axis() -> None:
    # A kept axis that NO discovery report re-surfaced (so it's absent from the settled
    # set) must be re-added by the guard — a kept axis is never dropped.
    from app.ai.dimension_decompose import enforce_committee_requests

    kept_axis = PoolDimension(
        key="participation_commitment", name="Participation commitment",
        definition="Willingness to do shared work.", high_end="high", low_end="low", why_it_differentiates="varies",
    )
    # Decomposition settled on an unrelated axis only.
    settled = DecompositionReport(
        dimensions=[
            DecomposedDimension(
                key="skills_offered", name="Skills offered", definition="trades",
                high_end="high", low_end="low",
                source_keys=["skills_offered"],
                decision="kept",
            ),
        ],
    )
    corrected, folded = enforce_committee_requests(settled, [], kept=[kept_axis])
    keys = {d.key for d in corrected.dimensions}
    assert "participation_commitment" in keys  # re-added, not lost
    readded = next(d for d in corrected.dimensions if d.key == "participation_commitment")
    assert readded.from_committee_request is True
    assert folded == []  # kept standalone, not folded into another axis


def test_adopt_matched_keys_dedupes_a_d9_readd_colliding_with_a_matched_key() -> None:
    # A kept axis re-added by the D9 guard under its canonical key can collide with a
    # DRIFTED re-discovery of the same concept that ALSO matches back to that key. A key
    # must be unique (cache identity), so the matched dimension wins and the redundant
    # re-add is dropped — never two dims sharing a key (which would 500 on the cache's
    # UNIQUE constraint).
    from app.services.ranking_run import adopt_matched_keys

    prior = PoolDimensionReport(dimensions=[
        PoolDimension(key="participation_commitment", name="Participation commitment",
                      definition="prior text", high_end="high", low_end="low", why_it_differentiates="v"),
    ])
    # This run: a drifted re-discovery of the same axis + the D9-re-added canonical key.
    report = PoolDimensionReport(dimensions=[
        PoolDimension(key="stated_participation", name="Stated participation",
                      definition="fresh text", high_end="high", low_end="low", why_it_differentiates="v"),
        PoolDimension(key="participation_commitment", name="Participation commitment",
                      definition="re-added", high_end="high", low_end="low", why_it_differentiates="v",
                      from_committee_request=True),
    ])
    adopted = adopt_matched_keys(
        report, {"stated_participation": "participation_commitment"}, prior
    )
    keys = [d.key for d in adopted.dimensions]
    assert keys == ["participation_commitment"]  # de-duped to one
    # The MATCHED dimension won — it carries the prior text the cached score pairs with.
    assert adopted.dimensions[0].definition == "prior text"


def test_adopt_matched_keys_collapses_two_twins_onto_one_prior() -> None:
    # Many-to-one: discovery re-carved ONE prior axis into TWO twins this run, and the
    # matcher recognized both as that prior concept. They must collapse into a SINGLE
    # dimension under the prior key (reusing its cached score), not survive as two axes
    # that double-weight one concept.
    from app.services.ranking_run import adopt_matched_keys

    prior = PoolDimensionReport(dimensions=[
        PoolDimension(key="participation_commitment", name="Participation commitment",
                      definition="prior text", high_end="high", low_end="low", why_it_differentiates="v"),
    ])
    report = PoolDimensionReport(dimensions=[
        PoolDimension(key="committee_participation", name="Committee participation",
                      definition="fresh a", high_end="high", low_end="low", why_it_differentiates="v"),
        PoolDimension(key="workday_participation", name="Workday participation",
                      definition="fresh b", high_end="high", low_end="low", why_it_differentiates="v"),
    ])
    # BOTH twins map to the same prior key (the sanitizer now allows this).
    adopted = adopt_matched_keys(
        report,
        {"committee_participation": "participation_commitment",
         "workday_participation": "participation_commitment"},
        prior,
    )
    keys = [d.key for d in adopted.dimensions]
    assert keys == ["participation_commitment"]  # collapsed to one
    # The prior text (and its cached score) is what survives — not either fresh carving.
    assert adopted.dimensions[0].definition == "prior text"


def test_match_dimensions_allows_many_new_onto_one_prior() -> None:
    # The sanitizer keeps several new->same-old pairs (a re-carved prior axis), dropping
    # only a repeated NEW key or an unknown key. (Previously it forced strict one-to-one,
    # silently discarding the second twin -> a double-counted concept downstream.)
    from unittest.mock import MagicMock

    from app.ai.dimension_matching import match_dimensions
    from app.ai.schemas import DimensionMatch, DimensionMatchReport
    from app.schemas.settings import AppSettings

    old = PoolDimensionReport(dimensions=[
        PoolDimension(key="participation_commitment", name="P", definition="d",
                      high_end="h", low_end="l", why_it_differentiates="v"),
    ])
    new = PoolDimensionReport(dimensions=[
        PoolDimension(key="committee_participation", name="A", definition="d",
                      high_end="h", low_end="l", why_it_differentiates="v"),
        PoolDimension(key="workday_participation", name="B", definition="d",
                      high_end="h", low_end="l", why_it_differentiates="v"),
    ])
    provider = MagicMock()
    provider.structured_output.return_value = MagicMock(
        output=DimensionMatchReport(matches=[
            DimensionMatch(new_key="committee_participation", old_key="participation_commitment"),
            DimensionMatch(new_key="workday_participation", old_key="participation_commitment"),
        ]),
        narrative=None,
        model_id="m",
        usage=MagicMock(input_tokens=1, output_tokens=1),
    )
    mapping, _narrative, _cost = match_dimensions(
        provider, old=old, new=new, settings=AppSettings()
    )
    assert mapping == {
        "committee_participation": "participation_commitment",
        "workday_participation": "participation_commitment",
    }


def test_match_dimensions_forces_self_match_over_a_wrong_llm_match() -> None:
    # A key present in BOTH lists (e.g. a committee-kept axis, injected at decomposition
    # under its exact prior key) IS its own prior axis by the frozen-key invariant. If the
    # LLM wrongly maps it onto a DIFFERENT prior key, the sanitizer overrides that to a
    # self-match — so the kept axis can never be matched away from itself and vanish.
    from unittest.mock import MagicMock

    from app.ai.dimension_matching import match_dimensions
    from app.ai.schemas import DimensionMatch, DimensionMatchReport
    from app.schemas.settings import AppSettings

    old = PoolDimensionReport(dimensions=[
        PoolDimension(key="participation_commitment", name="P", definition="d",
                      high_end="h", low_end="l", why_it_differentiates="v"),
        PoolDimension(key="financial_stability", name="F", definition="d",
                      high_end="h", low_end="l", why_it_differentiates="v"),
    ])
    # The kept axis recurs under its exact key; a fresh axis is genuinely new.
    new = PoolDimensionReport(dimensions=[
        PoolDimension(key="participation_commitment", name="P", definition="d",
                      high_end="h", low_end="l", why_it_differentiates="v"),
    ])
    provider = MagicMock()
    provider.structured_output.return_value = MagicMock(
        # The model wrongly maps the kept key onto a DIFFERENT prior key.
        output=DimensionMatchReport(matches=[
            DimensionMatch(new_key="participation_commitment", old_key="financial_stability"),
        ]),
        narrative=None,
        model_id="m",
        usage=MagicMock(input_tokens=1, output_tokens=1),
    )
    mapping, _narrative, _cost = match_dimensions(
        provider, old=old, new=new, settings=AppSettings()
    )
    # Overridden to a self-match — NOT the wrong financial_stability mapping.
    assert mapping == {"participation_commitment": "participation_commitment"}


def test_adopt_self_matched_key_restores_frozen_prior_text() -> None:
    # A scored key the decomposer reworded (new text under the same key) must adopt its
    # FROZEN prior text wholesale — the cached score was computed against the prior text,
    # so name/definition/poles must all revert. (Self-match => adopt_matched_keys pulls the
    # prior dimension entirely; the decomposer's rewording is discarded.)
    from app.services.ranking_run import adopt_matched_keys

    prior = PoolDimensionReport(dimensions=[
        PoolDimension(key="participation_commitment", name="Participation commitment",
                      definition="prior def", high_end="prior hi", low_end="prior lo",
                      why_it_differentiates="prior why"),
    ])
    # Same key, but the decomposer reworded everything.
    new = PoolDimensionReport(dimensions=[
        PoolDimension(key="participation_commitment", name="Reworded",
                      definition="reworded def", high_end="new hi", low_end="new lo",
                      why_it_differentiates="reworded why"),
    ])
    # match_dimensions would force the self-match; pass it explicitly here.
    adopted = adopt_matched_keys(
        new, {"participation_commitment": "participation_commitment"}, prior
    )
    dim = adopted.dimensions[0]
    assert dim.key == "participation_commitment"
    assert dim.name == "Participation commitment"  # frozen prior text, not "Reworded"
    assert dim.definition == "prior def"
    assert dim.high_end == "prior hi"
    assert dim.low_end == "prior lo"
    assert dim.why_it_differentiates == "prior why"


def test_settled_why_is_carried_from_source_not_decomposer() -> None:
    # The decomposer never sees the pool, so it does not write why_it_differentiates;
    # to_pool_report carries the real, pool-grounded why forward from the PRIMARY source
    # discovery axis (first source_key that resolves), including across a merge.
    from app.ai.dimension_decompose import to_pool_report

    reports = [
        PoolDimensionReport(
            dimensions=[
                PoolDimension(
                    key="commitment_a", name="Commitment A",
                    definition="willingness to do shared work",
                    high_end="high", low_end="low", why_it_differentiates="Applicants range from eager volunteers to vague.",
                ),
                PoolDimension(
                    key="commitment_b", name="Commitment B",
                    definition="willingness to show up for work days",
                    high_end="high", low_end="low", why_it_differentiates="secondary carving why",
                ),
            ],
        ),
    ]
    settled = DecompositionReport(
        dimensions=[
            DecomposedDimension(
                key="commitment", name="Commitment",
                definition="willingness to do shared work",
                high_end="high", low_end="low",
                source_keys=["commitment_a", "commitment_b"],
                decision="merged",
            ),
        ],
    )
    out = to_pool_report(settled, reports)
    dim = out.dimensions[0]
    # The primary source's real why is carried forward — NOT an empty/decomposer string.
    assert dim.why_it_differentiates == "Applicants range from eager volunteers to vague."


@pytest.mark.anyio
async def test_criteria_phase_streams_thinking_deltas() -> None:
    # The discovery (and match) call streams the model's reasoning as
    # criteria_thinking events, so the UI can show live "thinking" during the
    # otherwise-opaque multi-minute call. The MockProvider emits fixed deltas.
    app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    route_criteria(provider, a_pattern_report())
    provider.route("applicant_id", a_scoring_report())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        events = await stream_events(client, "/ranking/run")

        thinking = [e for e in events if e["type"] == "thinking"]
        assert thinking, "expected streamed thinking deltas"
        # Deltas arrive between the criteria phase announcement and its completion.
        types = [e["type"] for e in events]
        assert types.index("phase") < types.index("thinking")
        assert "".join(e["text"] for e in thinking)  # non-empty reasoning text

        # The criteria phase also emits sub-stage markers so the UI can name the step.
        # This is a FIRST run (no prior history), so the match pass is skipped — only
        # discovery and decomposition fire, in order.
        stages = [e["stage"] for e in events if e["type"] == "stage"]
        assert stages == ["discovering", "settling"]

        # A horizontal rule separates each sub-stage's reasoning — one here, between the
        # two stages — but none opens the box before the first stage.
        separators = [e for e in thinking if e["text"] == "\n\n---\n\n"]
        assert len(separators) == 1
        first_sep_idx = next(i for i, e in enumerate(events) if e.get("text") == "\n\n---\n\n")
        settling_idx = next(i for i, e in enumerate(events) if e.get("stage") == "settling")
        assert first_sep_idx < settling_idx  # rule precedes the stage label it introduces


@pytest.mark.anyio
async def test_tiers_reweight_and_resort_the_ranking() -> None:
    app, db, provider = setup_app(role=UserRole.MEMBER)
    # Two candidates who each lead on a different dimension, so the weighting
    # decides the order: commitment-strong vs skills-strong.
    commit_lead = add_eligible(db, email="commit@x.com", raw_hash="h1")
    skills_lead = add_eligible(db, email="skills@x.com", raw_hash="h2")

    route_criteria(provider, a_pattern_report())
    provider.route(
        f'"applicant_id": {commit_lead.id}', _scoring_report(commitment=0.9, skills=0.1)
    )
    provider.route(
        f'"applicant_id": {skills_lead.id}', _scoring_report(commitment=0.1, skills=0.9)
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await stream_events(client, "/ranking/run")

        # Default layout: Critical / Important / Minor working tiers (empty) + Ignore,
        # with every dimension starting in Ignore — the committee drags them out to
        # weigh in. Displayed layout: Critical / Important / Minor working tiers (empty)
        # + a synthesized Ignore zone holding every dimension, since nothing is placed yet.
        default = (await client.get("/ranking/tiers")).json()["tiers"]
        working = [t for t in default if not t.get("ignore")]
        assert [t["label"] for t in working] == ["Critical", "Important", "Minor"]
        assert all(t["dimensionKeys"] == [] for t in working)
        ignore = next(t for t in default if t.get("ignore"))
        assert set(ignore["dimensionKeys"]) == {"participation_commitment", "skills_offered"}

        # Put skills above commitment: skills_lead should now top the ranking.
        layout = {
            "tiers": [
                {"id": "t1", "label": "Top", "dimensionKeys": ["skills_offered"], "ignore": False},
                {"id": "t2", "label": "Lower", "dimensionKeys": ["participation_commitment"], "ignore": False},
                {"id": "ignore", "label": "Ignore", "dimensionKeys": [], "ignore": True},
            ]
        }
        ranking = (await client.put("/ranking/tiers", json=layout)).json()
        assert ranking["candidates"][0]["applicationId"] == skills_lead.id
        assert ranking["weights"] == {"skills_offered": 2.0, "participation_commitment": 1.0}


@pytest.mark.anyio
async def test_tiers_ignore_drops_then_revives_a_dimension() -> None:
    app, db, provider = setup_app(role=UserRole.MEMBER)
    commit_lead = add_eligible(db, email="commit@x.com", raw_hash="h1")
    skills_lead = add_eligible(db, email="skills@x.com", raw_hash="h2")
    route_criteria(provider, a_pattern_report())
    provider.route(
        f'"applicant_id": {commit_lead.id}', _scoring_report(commitment=0.9, skills=0.1)
    )
    provider.route(
        f'"applicant_id": {skills_lead.id}', _scoring_report(commitment=0.1, skills=0.9)
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await stream_events(client, "/ranking/run")

        # Ignore commitment entirely: only skills counts, so skills_lead leads on
        # fit 0.9 vs 0.1 — decisive, not a tiebreak.
        ignore_commit = {
            "tiers": [
                {"id": "t1", "label": "Top", "dimensionKeys": ["skills_offered"], "ignore": False},
                {"id": "ignore", "label": "Ignore", "dimensionKeys": ["participation_commitment"], "ignore": True},
            ]
        }
        ranking = (await client.put("/ranking/tiers", json=ignore_commit)).json()
        assert ranking["candidates"][0]["applicationId"] == skills_lead.id
        assert ranking["weights"]["participation_commitment"] == 0.0
        assert ranking["candidates"][0]["fit"] == 0.9

        # Revive it back into a tier: it counts again.
        revive = {
            "tiers": [
                {"id": "t1", "label": "Top", "dimensionKeys": ["skills_offered", "participation_commitment"], "ignore": False},
                {"id": "ignore", "label": "Ignore", "dimensionKeys": [], "ignore": True},
            ]
        }
        ranking2 = (await client.put("/ranking/tiers", json=revive)).json()
        assert ranking2["weights"]["participation_commitment"] == 1.0


@pytest.mark.anyio
async def test_tiers_reject_unknown_dimension_key() -> None:
    app, db, provider = setup_app(role=UserRole.MEMBER)
    a = add_eligible(db, email="a@x.com", raw_hash="h1")
    route_criteria(provider, a_pattern_report())
    provider.route(f'"applicant_id": {a.id}', a_scoring_report())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await stream_events(client, "/ranking/run")
        bad = {
            "tiers": [
                {"id": "t1", "label": "Top", "dimensionKeys": ["not_a_real_dimension"], "ignore": False},
                {"id": "ignore", "label": "Ignore", "dimensionKeys": [], "ignore": True},
            ]
        }
        assert (await client.put("/ranking/tiers", json=bad)).status_code == 400  # unknown_dimension_key


def a_pattern_report_v2() -> PoolDimensionReport:
    """A re-discovery: participation_commitment recurs (drifted key), skills_offered
    is gone, and a genuinely new dimension appears."""
    return PoolDimensionReport(
        dimensions=[
            PoolDimension(
                key="stated_participation",  # same concept, drifted key
                name="Stated participation",
                definition="Willingness to do shared work.",
                high_end="high", low_end="low", why_it_differentiates="Some eager, some vague.",
            ),
            PoolDimension(
                key="financial_stability",  # genuinely new
                name="Financial stability",
                definition="Income resilience and stability.",
                high_end="high", low_end="low", why_it_differentiates="Range of income security.",
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
        # participation_commitment into the Critical tier.
        route_criteria(provider, a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")
        # Tier participation_commitment into Critical; leave skills_offered in Ignore
        # (unplaced) so discovery is free to drop it — a KEPT (tiered) dimension can no
        # longer be dropped (it's injected at decomposition), so only an Ignored one can
        # exercise the drop path this test relies on.
        await client.put(
            "/ranking/tiers",
            json={
                "tiers": [
                    {"id": "tier-s", "label": "Critical", "dimensionKeys": ["participation_commitment"], "ignore": False},
                    {"id": "tier-a", "label": "Important", "dimensionKeys": [], "ignore": False},
                    {"id": "ignore", "label": "Ignore", "dimensionKeys": ["skills_offered"], "ignore": True},
                ]
            },
        )

        # Pool changes (new applicant) so re-rank is allowed; re-discovery returns
        # v2 dimensions. The match pass maps stated_participation -> the prior
        # participation_commitment (same concept); financial_stability is new.
        add_eligible(db, email="b@x.com", raw_hash="h2")
        route_criteria(provider, a_pattern_report_v2())
        provider.route(
            "<prior_dimensions>",
            DimensionMatchReport(
                matches=[DimensionMatch(new_key="stated_participation", old_key="participation_commitment")]
            ),
        )
        provider.route("applicant_id", _scoring_report_v2())
        events = await stream_events(client, "/ranking/run")

        criteria_done = next(e for e in events if e["type"] == "notice")
        assert criteria_done["carriedForward"] == 1
        assert criteria_done["newDimensions"] == 1

        layout = (await client.get("/ranking/tiers")).json()["tiers"]
        by_label = {t["label"]: t for t in layout}
        # The matched dimension ADOPTED the prior key and kept the prior Critical
        # placement — so the placement carries forward by key, no separate identity.
        assert by_label["Critical"]["dimensionKeys"] == ["participation_commitment"]
        # The genuinely-new dimension is unplaced -> shows in the synthesized Ignore zone.
        ignore = next(t for t in layout if t.get("ignore"))
        assert "financial_stability" in ignore["dimensionKeys"]

        current = (await client.get("/ranking/current")).json()
        assert current["newDimensionKeys"] == ["financial_stability"]
        # A match adopts the prior dimension WHOLESALE — prior key AND prior text —
        # because it reuses the prior cached score, computed against the prior
        # definition. So the fresh re-discovered wording ("Stated participation") is
        # discarded in favour of the prior "Participation commitment".
        by_key = {d["key"]: d for d in current["dimensions"]}
        assert by_key["participation_commitment"]["name"] == "Participation commitment"

        # Acknowledge the new dimension in place (badge ✕ / "mark all reviewed"):
        # keep the layout unchanged, send the key in acknowledgedKeys. It drops
        # out of new_dimension_keys without being placed in a working tier.
        ack = await client.put(
            "/ranking/tiers",
            json={"tiers": layout, "acknowledgedKeys": ["financial_stability"]},
        )
        assert ack.status_code == 200
        assert ack.json()["newDimensionKeys"] == []
        # And it stuck: still unplaced (in Ignore), just no longer flagged.
        current = (await client.get("/ranking/current")).json()
        assert current["newDimensionKeys"] == []
        layout2 = (await client.get("/ranking/tiers")).json()["tiers"]
        ignore2 = next(t for t in layout2 if t.get("ignore"))
        assert "financial_stability" in ignore2["dimensionKeys"]


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
async def test_dropped_prior_dimension_is_not_revived() -> None:
    """Reconcile was REMOVED in the fan-out redesign (SPEC D2/D8): a prior dimension the
    latest discovery drops is NOT dragged back. A valued axis that still varies is
    expected to re-surface in one of the K fresh discoveries and survive the
    decomposition, not be revived from history by a separate pass. So a dropped prior
    stays gone."""
    app, db, provider = setup_app(role=UserRole.ADMIN)
    add_eligible(db, email="a@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Run 1: discover participation_commitment + skills_offered; score; then the
        # committee tiers participation_commitment into Critical and leaves skills_offered
        # in Ignore (unplaced) — only an Ignored dimension can be dropped by discovery now
        # (a kept/tiered one is injected at decomposition and can't vanish).
        route_criteria(provider, a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")
        await client.put(
            "/ranking/tiers",
            json={
                "tiers": [
                    {"id": "tier-s", "label": "Critical", "dimensionKeys": ["participation_commitment"], "ignore": False},
                    {"id": "tier-a", "label": "Important", "dimensionKeys": [], "ignore": False},
                    {"id": "ignore", "label": "Ignore", "dimensionKeys": ["skills_offered"], "ignore": True},
                ]
            },
        )

        # Run 2 (pool changes): discovery returns ONLY participation_commitment —
        # skills_offered dropped out. Match maps participation_commitment to its prior
        # key; skills_offered is the dropped prior. With reconcile disabled it stays gone.
        # route_criteria re-routes BOTH discovery and the decomposition (a pass-through of
        # the same single dim), overriding run 1's routes so the run-2 settled set is
        # participation-only.
        add_eligible(db, email="b@x.com", raw_hash="h2")
        route_criteria(
            provider,
            PoolDimensionReport(
                dimensions=[
                    PoolDimension(
                        key="participation_commitment",
                        name="Participation commitment",
                        definition="Willingness to do shared work.",
                        high_end="high", low_end="low", why_it_differentiates="Some eager, some vague.",
                    ),
                ],
            ),
        )
        provider.route(
            "<prior_dimensions>",
            DimensionMatchReport(
                matches=[DimensionMatch(new_key="participation_commitment", old_key="participation_commitment")]
            ),
        )
        provider.route("applicant_id", a_scoring_report())
        run2_events = await stream_events(client, "/ranking/run")

        # This IS a re-run (prior history exists), so all three criteria sub-stages fire
        # in order — including matching, which a first run skips.
        stages = [e["stage"] for e in run2_events if e["type"] == "stage"]
        assert stages == ["discovering", "settling", "matching"]

        # skills_offered was dropped by discovery and is NOT revived — the run holds only
        # what decomposition settled (participation_commitment), not the historical prior.
        current = (await client.get("/ranking/current")).json()
        keys = {d["key"] for d in current["dimensions"]}
        assert "skills_offered" not in keys
        assert keys == {"participation_commitment"}


def _only_participation() -> PoolDimensionReport:
    """A re-discovery that surfaces only participation_commitment (skills_offered is
    absent) — used across the 3-run revival test to force a presence gap."""
    return PoolDimensionReport(
        dimensions=[
            PoolDimension(
                key="participation_commitment",
                name="Participation commitment",
                definition="Willingness to do shared work.",
                high_end="high", low_end="low", why_it_differentiates="Some eager, some vague.",
            ),
        ],
    )


@pytest.mark.anyio
async def test_three_run_gap_flags_dimension_as_revived_not_new() -> None:
    """The full 'revived' path through the live /run chain: a dimension present in run
    1, GONE in run 2 (a real gap the committee lived through), then reconciled back in
    run 3 — must badge blue 'Revived' (not amber 'New'), restore its placement, and
    read as revived in the API response. Closes the seam between the 3-run label logic
    and the streaming chain (the 2-run test can only prove 'recovered, not revived')."""
    app, db, provider = setup_app(role=UserRole.ADMIN)
    add_eligible(db, email="a@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Run 1: discover participation_commitment + skills_offered; tier
        # participation_commitment into Critical and leave skills_offered in Ignore
        # (unplaced) — only an Ignored dimension can be dropped by discovery now, so the
        # gap this test needs must be on an Ignored key.
        route_criteria(provider, a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")
        await client.put(
            "/ranking/tiers",
            json={
                "tiers": [
                    {"id": "tier-s", "label": "Critical", "dimensionKeys": ["participation_commitment"], "ignore": False},
                    {"id": "tier-a", "label": "Important", "dimensionKeys": [], "ignore": False},
                    {"id": "ignore", "label": "Ignore", "dimensionKeys": ["skills_offered"], "ignore": True},
                ]
            },
        )

        # Run 2 (pool changes): discovery drops skills_offered and it genuinely leaves the
        # run — the gap the committee lives through. (No reconcile to salvage it; with the
        # pass disabled, a dropped prior stays gone.) match maps participation forward.
        add_eligible(db, email="b@x.com", raw_hash="h2")
        route_criteria(provider, _only_participation())
        provider.route(
            "<prior_dimensions>",
            DimensionMatchReport(
                matches=[DimensionMatch(new_key="participation_commitment", old_key="participation_commitment")]
            ),
        )
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")

        # After run 2: skills_offered is gone from the run entirely — the gap.
        current2 = (await client.get("/ranking/current")).json()
        assert "skills_offered" not in {d["key"] for d in current2["dimensions"]}

        # Run 3 (pool changes again): DISCOVERY itself re-surfaces skills_offered after
        # the gap (the fan-out route to revival now that reconcile is gone — a fresh
        # discovery names it again). The "revived" badge is presence-driven and route-
        # agnostic: seen in run 1, absent run 2, back run 3 → revived, not new.
        add_eligible(db, email="c@x.com", raw_hash="h3")
        route_criteria(provider, a_pattern_report())  # both dims — skills_offered returns
        provider.route(
            "<prior_dimensions>",
            DimensionMatchReport(
                matches=[
                    DimensionMatch(new_key="participation_commitment", old_key="participation_commitment"),
                    DimensionMatch(new_key="skills_offered", old_key="skills_offered"),
                ]
            ),
        )
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")

        # skills_offered is back, flagged, and labelled REVIVED (seen in run 1, before
        # the run-2 gap) — NOT new. participation_commitment stayed continuous → unflagged.
        current = (await client.get("/ranking/current")).json()
        assert "skills_offered" in {d["key"] for d in current["dimensions"]}
        assert current["revivedDimensionKeys"] == ["skills_offered"]
        assert current["newDimensionKeys"] == ["skills_offered"]  # flagged set holds it
        # It restored its LAST placement across the gap (durable committee intent): it was
        # in Ignore before the gap, so it returns to Ignore — while participation_commitment
        # keeps its Critical placement.
        layout = (await client.get("/ranking/tiers")).json()["tiers"]
        by_label = {t["label"]: t for t in layout}
        assert by_label["Critical"]["dimensionKeys"] == ["participation_commitment"]
        ignore = next(t for t in layout if t.get("ignore"))
        assert "skills_offered" in ignore["dimensionKeys"]

        # The ranking payload (what the tier-list UI reads) agrees, so the blue badge
        # renders: revived on a working-tier chip, not gated to Ignore.
        ranking = (await client.get("/ranking")).json()
        assert ranking["revivedDimensionKeys"] == ["skills_offered"]


@pytest.mark.anyio
async def test_tiers_without_ignore_zone_means_everything_ignored() -> None:
    """Ignore is the absence of a placement, not a stored tier: a layout with only
    a working tier is valid, and dimensions left out are weight 0 (ignored)."""
    app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    route_criteria(provider, a_pattern_report())
    provider.route("applicant_id", a_scoring_report())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await stream_events(client, "/ranking/run")
        only_working = {
            "tiers": [
                {"id": "t1", "label": "Top", "dimensionKeys": ["participation_commitment"], "ignore": False},
            ]
        }
        ranking = (await client.put("/ranking/tiers", json=only_working)).json()
        # commitment is placed (weight 1); skills is unplaced -> ignored (weight 0).
        assert ranking["weights"] == {"participation_commitment": 1.0, "skills_offered": 0.0}
        # The displayed layout synthesizes the Ignore zone with the unplaced dim.
        layout = (await client.get("/ranking/tiers")).json()["tiers"]
        ignore = next(t for t in layout if t.get("ignore"))
        assert ignore["dimensionKeys"] == ["skills_offered"]


@pytest.mark.anyio
async def test_tiers_before_run_is_409() -> None:
    app, db, _ = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/ranking/tiers")).status_code == 409
        assert (
            await client.put("/ranking/tiers", json={"tiers": []})
        ).status_code == 409


@pytest.mark.anyio
async def test_rank_flags_unchanged_pool_but_allows_rerun() -> None:
    # After a Rank run, the estimate flags an unchanged pool as already current (so
    # the UI can say nothing requires a re-run). But a re-run is NOT blocked:
    # categorization is non-deterministic, so a member may deliberately re-run for a
    # fresh set of criteria. The confirmation card is the gate, not the server.
    app, db, provider = setup_app(role=UserRole.MEMBER)
    a = add_eligible(db, email="a@x.com", raw_hash="h1")
    route_criteria(provider, a_pattern_report())
    provider.route(f'"applicant_id": {a.id}', a_scoring_report())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await stream_events(client, "/ranking/run")

        # Pool unchanged → estimate flags it current, but the re-run still succeeds.
        estimate = (await client.get("/ranking/run/estimate")).json()
        assert estimate["rankingCurrent"] is True
        assert (await client.post("/ranking/run")).status_code == 200


@pytest.mark.anyio
async def test_rank_estimate_combines_three_passes() -> None:
    app, db, _ = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        estimate = (await client.get("/ranking/run/estimate")).json()
        b = estimate["breakdown"]
        # Total is the sum of the pass projections, and flagged approximate.
        assert estimate["estimatedUsd"] == pytest.approx(
            b["criteriaUsd"] + b["scoringUsd"], abs=1e-4
        )
        assert estimate["approximate"] is True
        assert estimate["eligible"] == 1


@pytest.mark.anyio
async def test_rank_with_no_eligible_is_409() -> None:
    app, _, _ = setup_app(role=UserRole.MEMBER)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/ranking/run/estimate")).status_code == 409
        assert (await client.post("/ranking/run")).status_code == 409


@pytest.mark.anyio
async def test_rank_over_cap_fails_fast() -> None:
    app, db, _provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")

    # Force the combined estimate over the cap by setting a tiny cap.
    from app.services.settings import get_app_settings, save_app_settings

    settings = get_app_settings(db)
    settings.ai.spending_cap_usd = 0.0
    save_app_settings(db, settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # No provider results queued: a 402 must come before any model call.
        assert (await client.post("/ranking/run")).status_code == 402


@pytest.mark.anyio
async def test_dimension_scores_null_before_run() -> None:
    app, db, _ = setup_app(role=UserRole.MEMBER)
    application = add_eligible(db, email="a@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # No run at all -> null (the candidate has no scores to surface yet).
        detail = (await client.get(f"/applications/{application.id}")).json()["application"]
        assert detail["dimensionScores"] is None


# --- Discovery seeds (proposed dimensions) + kept-axis injection -------------


def _pattern_report_with_requested() -> PoolDimensionReport:
    """A discovery result where the model flagged one dimension as created from a
    committee proposal (the D9 never-vanish signal)."""
    return PoolDimensionReport(
        dimensions=[
            PoolDimension(
                key="participation_commitment",
                name="Participation commitment",
                definition="Willingness to do shared work.",
                high_end="high", low_end="low", why_it_differentiates="Some eager, some vague.",
            ),
            PoolDimension(
                key="playground_age_children",
                name="Playground-age children",
                definition="Presence of school-age kids who'd use shared play space.",
                high_end="high", low_end="low", why_it_differentiates="Some households have young kids, some none.",
                from_committee_request=True,
            ),
        ],
    )


def test_build_prompt_unseeded_has_no_requested_section() -> None:
    # An un-seeded discovery prompt must not carry a REQUESTED AXES section, so the
    # default blind run is unchanged.
    from app.ai.pattern_discovery import DiscoverySeeds, build_prompt

    _app, db, _ = setup_app(role=UserRole.MEMBER)
    a = add_eligible(db, email="a@x.com", raw_hash="h1")
    apps = [a]
    bare = build_prompt(apps)
    assert "<requested_axes>" not in bare
    # An empty seed set is equivalent to no seeds.
    assert build_prompt(apps, seeds=DiscoverySeeds()) == bare


def test_build_prompt_includes_proposed_seeds() -> None:
    # Only PROPOSALS seed discovery now; favourites inject at decomposition, not here.
    from app.ai.pattern_discovery import DiscoverySeeds, build_prompt

    _app, db, _ = setup_app(role=UserRole.MEMBER)
    a = add_eligible(db, email="a@x.com", raw_hash="h1")
    seeds = DiscoverySeeds(proposed=["school-age kids who'd use the playground"])
    prompt = build_prompt([a], seeds=seeds)
    assert "<requested_axes>" in prompt
    assert "school-age kids who'd use the playground" in prompt
    # The model is told to flag what it creates from a request.
    assert "from_committee_request" in prompt


@pytest.mark.anyio
async def test_proposed_dimension_seeds_discovery_then_clears() -> None:
    # A proposed axis is fed to discovery; the model returns a dimension flagged
    # from_committee_request. After the run: the proposal is consumed (cleared). It is
    # NOT auto-kept — a brand-new proposal lands in Ignore for the committee to tier
    # (tiers-only keep rule); it survives THIS run via the within-run D9 guard.
    app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # First blind run so a run exists to attach seeds to.
        route_criteria(provider, a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")

        # Propose an axis between runs.
        seeds = (await client.put(
            "/ranking/seeds",
            json={"proposedDimensions": ["school-age kids who'd use the playground"]},
        )).json()
        assert seeds["proposedDimensions"] == ["school-age kids who'd use the playground"]

        # Re-run: discovery now returns a report flagging the requested dimension.
        provider.calls.clear()
        route_criteria(provider, _pattern_report_with_requested())
        provider.route("<prior_dimensions>", DimensionMatchReport(matches=[]))  # match pass
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")

        # The proposal text reached the discovery prompt.
        discovery_prompt = next(c.prompt for c in provider.calls if "<applicant_pool>" in c.prompt)
        assert "school-age kids who'd use the playground" in discovery_prompt

        # After the run: proposal consumed (cleared). The new axis is present but NOT
        # kept — it lands unplaced (Ignore) awaiting a tier, so kept_keys excludes it.
        current = (await client.get("/ranking/current")).json()
        assert current["proposedDimensions"] == []
        assert "playground_age_children" not in current["keptKeys"]
        assert current["keptKeys"] == []


@pytest.mark.anyio
async def test_tiered_dimension_is_kept_and_injected_at_decomposition_not_discovery() -> None:
    # Placing a dimension in a working tier KEEPS it: on re-run it's injected at
    # DECOMPOSITION (by name + definition), NOT seeded into discovery — so all K
    # discoverers stay blind. It stays kept (tiered) across the re-run.
    app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        route_criteria(provider, a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")

        # Keep an existing dimension by tiering it (Critical).
        ranking = (await client.put(
            "/ranking/tiers",
            json={"tiers": [{"id": "tier-s", "label": "Critical",
                             "dimensionKeys": ["participation_commitment"], "ignore": False}]},
        )).json()
        assert ranking["keptKeys"] == ["participation_commitment"]

        # Re-run: the kept axis recurs (match pass maps it back to its prior key).
        provider.calls.clear()
        route_criteria(provider, a_pattern_report())
        provider.route(
            "<prior_dimensions>",
            DimensionMatchReport(matches=[]),  # same keys, so no rewrite needed
        )
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")

        # Discovery stays BLIND — the kept axis is NOT in the discovery prompt.
        discovery_prompt = next(c.prompt for c in provider.calls if "<applicant_pool>" in c.prompt)
        assert "<requested_axes>" not in discovery_prompt
        assert "Willingness to do shared work." not in discovery_prompt

        # The kept axis's name + definition reached the DECOMPOSITION prompt instead.
        decompose_prompt = next(c.prompt for c in provider.calls if "<discovery_reports>" in c.prompt)
        assert "<kept_axes>" in decompose_prompt
        assert "Willingness to do shared work." in decompose_prompt

        # It is still kept (its Critical placement carried forward) after the re-run.
        current = (await client.get("/ranking/current")).json()
        assert "participation_commitment" in current["keptKeys"]


@pytest.mark.anyio
async def test_put_seeds_before_run_is_409() -> None:
    app, db, _ = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.put("/ranking/seeds", json={"proposedDimensions": ["x"]})
        assert resp.status_code == 409


@pytest.mark.anyio
async def test_match_audit_is_null_before_any_run() -> None:
    app, _, _ = setup_app(role=UserRole.MEMBER)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/ranking/current/match-audit")
        assert resp.status_code == 200
        assert resp.json() is None


@pytest.mark.anyio
async def test_match_audit_first_run_has_null_carry_forward_rate() -> None:
    # A first run has no prior dimensions to match against, so carry-forward is
    # undefined (null), not 0 — every dimension is genuinely new.
    app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        route_criteria(provider, a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")

        audit = (await client.get("/ranking/current/match-audit")).json()
        assert audit["priorDimensionCount"] == 0
        assert audit["discoveredCount"] == 2
        assert audit["matchedCount"] == 0
        assert audit["newCount"] == 2
        assert audit["carryForwardRate"] is None
        assert audit["newToOld"] == {}


@pytest.mark.anyio
async def test_match_audit_reports_carry_forward_rate_on_rerun() -> None:
    # On a re-run the match pass maps one of two new dimensions onto a prior one,
    # so the carry-forward rate is 1/2 and the audit exposes the raw discovery keys
    # and the new->old map — the over-matching signal M13 exists to surface.
    app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        route_criteria(provider, a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")

        # Pool changes so a re-rank is allowed; v2 re-discovery, match pass maps
        # stated_participation -> participation_commitment (financial_stability is new).
        add_eligible(db, email="b@x.com", raw_hash="h2")
        route_criteria(provider, a_pattern_report_v2())
        provider.route(
            "<prior_dimensions>",
            DimensionMatchReport(
                matches=[DimensionMatch(new_key="stated_participation", old_key="participation_commitment")]
            ),
        )
        provider.route("applicant_id", _scoring_report_v2())
        await stream_events(client, "/ranking/run")

        audit = (await client.get("/ranking/current/match-audit")).json()
        assert audit["priorDimensionCount"] == 2
        assert audit["discoveredCount"] == 2
        assert audit["matchedCount"] == 1
        assert audit["newCount"] == 1
        assert audit["carryForwardRate"] == 0.5
        # new_to_old resolves each matched new-key to the prior dimension's key AND its
        # user-facing name (so the viewer shows the prior title, not just the key).
        assert audit["newToOld"] == {
            "stated_participation": {"key": "participation_commitment", "name": "Participation commitment"}
        }
        # Raw discovery keys are pre-adoption (what discovery actually emitted).
        raw_keys = {d["key"] for d in audit["rawDiscoveryDimensions"]}
        assert raw_keys == {"stated_participation", "financial_stability"}
