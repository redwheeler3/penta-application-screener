
import pytest
from httpx2 import ASGITransport, AsyncClient

from app.ai.schemas import (
    DimensionMatchReport,
)
from app.db.models import UserRole
from app.services.cost_report import RANK_PASS_LABELS
from tests.ranking_support import (
    _scoring_report,
    a_pattern_report,
    a_scoring_report,
    add_eligible,
    current_analysis_id,
    route_criteria,
    setup_app,
    stream_events,
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
                "analysisId": await current_analysis_id(client),
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
        assert trace["models"] == [
            {
                "modelId": "mock-model",
                "supportsReasoningEffort": False,
                "reasoningEffort": None,
            }
        ]
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
                "analysisId": before["analysisId"],
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
        assert after["analysisId"] == before["analysisId"]
        assert after["dimensions"] == before["dimensions"]
        tiers = (await client.get("/ranking/tiers")).json()["tiers"]
        assert tiers[0]["dimensionKeys"] == ["skills_offered"]
        assert (await client.get("/dashboard")).json()["workflow"]["rankingCurrent"] is True

        last_runs = (await client.get("/observability/last-runs")).json()
        assert last_runs["rankScores"]["kind"] == "rank_scores"
        assert [p["label"] for p in last_runs["rankScores"]["passes"]] == ["Dimension scoring"]
        metrics = (await client.get("/observability/metrics")).json()
        assert metrics["runs"][-1]["kind"] == "rank_scores"
        assert metrics["runs"][-1]["dimensions"] is None


@pytest.mark.anyio
async def test_score_current_requires_existing_criteria() -> None:
    app, db, _ = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/ranking/score-current/estimate")).status_code == 409
        assert (await client.post("/ranking/score-current")).status_code == 409


@pytest.mark.anyio
async def test_observability_cost_aggregates_by_pass() -> None:
    # After a rank, the cost report sums stored spend by pass: scoring from
    # ApplicationAIResult, discovery from the run. (Screening isn't run in this flow.)
    app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        route_criteria(provider, a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")

        report = (await client.get("/observability/cost")).json()
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

        first = (await client.get("/observability/last-runs")).json()
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

        second = (await client.get("/observability/last-runs")).json()["rank"]
        by_pass2 = {p["label"]: p for p in second["passes"]}
        # Scoring reused from cache → cached counts and a nonzero saving.
        # Dimension scoring persists one cache row per dimension, matching the
        # cumulative spend table's unit.
        assert by_pass2["Dimension scoring"]["cachedCount"] == 2
        assert by_pass2["Dimension scoring"]["cachedSavedUsd"] > 0.0
        assert second["cachedSavedUsd"] > 0.0


@pytest.mark.anyio
async def test_cost_surfaces_agree_on_rank_passes() -> None:
    # Both cost surfaces must cover the same pass labels despite reading different stores.
    app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        route_criteria(provider, a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")

        cumulative = (await client.get("/observability/cost")).json()
        rank_group = next(g for g in cumulative["groups"] if g["runLabel"] == "Discover criteria & rank")
        cumulative_labels = {p["passLabel"] for p in rank_group["passes"]}

        last = (await client.get("/observability/last-runs")).json()["rank"]
        ledger_labels = {p["label"] for p in last["passes"]}

    assert cumulative_labels == set(RANK_PASS_LABELS)
    assert ledger_labels == set(RANK_PASS_LABELS)


@pytest.mark.anyio
async def test_observability_metrics_trends_after_a_rank() -> None:
    # Metrics include run latency, live dimensions, and a per-pass breakdown.
    app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        route_criteria(provider, a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")

        metrics = (await client.get("/observability/metrics")).json()
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
        await client.put(f"/applications/{strong.id}/shortlist")

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
        assert candidates[0]["shortlisted"] is True
        assert candidates[1]["shortlisted"] is False


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
    # Rank persists every parallel discovery report for decomposition and audit. The mock
    # verifies call count and persistence; cross-call diversity requires a real model.
    from app.schemas.settings import AISettings
    from app.services.ranking.analysis import get_latest_analysis

    app, db, provider = setup_app(role=UserRole.MEMBER)
    a = add_eligible(db, email="a@x.com", raw_hash="h1")
    route_criteria(provider, a_pattern_report())
    provider.route(f'"applicant_id": {a.id}', _scoring_report(commitment=0.5, skills=0.5))

    k = AISettings().discovery_fan_out  # the shipped default
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await stream_events(client, "/ranking/run")

    run = get_latest_analysis(db)
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
