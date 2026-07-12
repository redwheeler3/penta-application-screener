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

        # Scores surface on the candidate detail, joined to dimension names, and
        # status is untouched (the chain's passes never gate eligibility).
        detail = (await client.get(f"/applications/{application.id}")).json()["application"]
        assert detail["status"] == "eligible"
        assert detail["statusSource"] == "untouched"
        scores = detail["dimensionScores"]
        assert len(scores) == 2
        by_key = {s["dimensionKey"]: s for s in scores}
        assert by_key["participation_commitment"]["name"] == "Participation commitment"
        assert by_key["participation_commitment"]["score"] == 0.8
        assert by_key["skills_offered"]["confidence"] == "low"


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

        report = (await client.get("/ranking/insights/cost")).json()
        groups = {g["runLabel"]: g for g in report["groups"]}
        # Grouped by triggering run: Screen (screening) and Rank (discovery/
        # decomposition/matching/scoring).
        assert set(groups) == {"Screen", "Rank"}
        rank_passes = {p["passLabel"]: p for p in groups["Rank"]["passes"]}
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
        assert groups["Rank"]["subtotalUsd"] == pytest.approx(
            sum(p["costUsd"] for p in groups["Rank"]["passes"]), abs=1e-6
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

        first = (await client.get("/ranking/insights/last-runs")).json()
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

        # Re-rank the unchanged pool: scores are cache hits now.
        route_criteria(provider, a_pattern_report())
        provider.route("<prior_dimensions>", DimensionMatchReport(matches=[]))
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")

        second = (await client.get("/ranking/insights/last-runs")).json()["rank"]
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

        cumulative = (await client.get("/ranking/insights/cost")).json()
        rank_group = next(g for g in cumulative["groups"] if g["runLabel"] == "Rank")
        cumulative_labels = {p["passLabel"] for p in rank_group["passes"]}

        last = (await client.get("/ranking/insights/last-runs")).json()["rank"]
        ledger_labels = {p["label"] for p in last["passes"]}

    assert cumulative_labels == set(RANK_PASS_LABELS)
    assert ledger_labels == set(RANK_PASS_LABELS)


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
    audit = (run.criteria or {}).get("fan_out_audit")
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
                          why_it_differentiates="varies"),
            PoolDimension(key="commitment_b", name="Commitment B",
                          definition="willingness to show up for work days",
                          why_it_differentiates="varies"),
            PoolDimension(key="skills_offered", name="Skills offered",
                          definition="concrete skills", why_it_differentiates="varies"),
        ],
    )
    # Decomposition folds commitment_a + commitment_b into one settled axis; skills stays.
    settled = DecompositionReport(
        dimensions=[
            DecomposedDimension(
                key="commitment", name="Commitment",
                definition="willingness to do shared work",
                source_keys=["commitment_a", "commitment_b"],
                decision="commitment_a and commitment_b score the same applicant alike — one axis.",
            ),
            DecomposedDimension(
                key="skills_offered", name="Skills offered",
                definition="concrete skills",
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
    stored_dims = run.criteria["dimension_report"]["dimensions"]
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
    audit = run.criteria.get("decompose_audit")
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
                          definition="handles co-op money", why_it_differentiates="varies"),
            PoolDimension(key="financial_stewardship", name="Financial stewardship",
                          definition="bookkeeping and oversight", why_it_differentiates="varies"),
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
    keys = {d["key"] for d in run.criteria["dimension_report"]["dimensions"]}
    # Collapsed 2 → 1: the newer key (financial_stewardship) is aliased into the older.
    assert keys == {"financial_literacy"}

    audit = run.criteria["consolidate_audit"]
    assert audit["merges"] == {"financial_stewardship": "financial_literacy"}

    alias = db.scalar(select(DimensionAlias).where(DimensionAlias.alias_key == "financial_stewardship"))
    assert alias is not None
    assert alias.canonical_key == "financial_literacy"


def test_apply_consolidation_transfers_a_favourite_off_a_merged_key() -> None:
    # A merged-away key can't stay favourited (it no longer exists). If the committee
    # favourited the dropped key, the favourite transfers to the surviving canonical key.
    from app.schemas.settings import AppSettings
    from app.services.ranking_run import apply_consolidation, create_run

    _app, db, _ = setup_app(role=UserRole.MEMBER)
    report = PoolDimensionReport(dimensions=[
        PoolDimension(key="financial_literacy", name="Financial literacy",
                      definition="handles money", why_it_differentiates="v"),
        PoolDimension(key="financial_stewardship", name="Financial stewardship",
                      definition="bookkeeping", why_it_differentiates="v"),
    ])
    run = create_run(
        db, report=report, settings=AppSettings(), model_id="m",
        narrative=None, discovery_cost_usd=0.0,
        prior_favourited_keys=["financial_stewardship"],  # the key that will be merged away
    )
    assert run.criteria["favourited_keys"] == ["financial_stewardship"]

    apply_consolidation(
        db, run,
        merges={"financial_stewardship": "financial_literacy"},
        audit=[{"keep": "financial_literacy", "drop": "financial_stewardship",
                "r": 0.94, "merged": True, "reason": "same concept"}],
        narrative=None, cost_usd=0.01,
    )
    # The favourite moved to the survivor, not left dangling on the dropped key.
    assert run.criteria["favourited_keys"] == ["financial_literacy"]
    keys = {d["key"] for d in run.criteria["dimension_report"]["dimensions"]}
    assert keys == {"financial_literacy"}


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
                          definition="why they want in", why_it_differentiates="varies"),
            PoolDimension(key="followthrough", name="Follow-through",
                          definition="do they finish tasks", why_it_differentiates="varies"),
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
    keys = {d["key"] for d in run.criteria["dimension_report"]["dimensions"]}
    assert keys == {"motivation", "followthrough"}  # both kept
    assert run.criteria["consolidate_audit"]["merges"] == {}
    assert db.scalar(select(DimensionAlias)) is None


def _discovery_with_committee_request() -> PoolDimensionReport:
    """A discovery report with one committee-requested axis (playground) plus a sibling
    it could tempt a merge with (child_wellbeing)."""
    return PoolDimensionReport(
        dimensions=[
            PoolDimension(key="playground_use", name="Playground use",
                          definition="school-age kids who'd use the playground",
                          why_it_differentiates="varies", from_committee_request=True),
            PoolDimension(key="child_wellbeing", name="Child wellbeing",
                          definition="general child-centred motivation",
                          why_it_differentiates="varies"),
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
    audit = run.criteria["decompose_audit"]
    # The fold is surfaced: playground_use -> child_wellbeing.
    assert {"request_key": "playground_use", "into_key": "child_wellbeing"} in audit["folded_requests"]
    # The flag was repaired on the settled axis (drives auto-favourite + the badge).
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
    keys = {d["key"] for d in run.criteria["dimension_report"]["dimensions"]}
    # The dropped request was re-added, so both axes survive.
    assert keys == {"child_wellbeing", "playground_use"}
    readded = next(
        d for d in run.criteria["decompose_audit"]["settled"] if d["key"] == "playground_use"
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


def test_enforce_committee_requests_guarantees_an_unsurfaced_favourite() -> None:
    # A favourite that NO discovery report re-surfaced (so it's absent from the settled
    # set) must be re-added by the guard — a favourite is never dropped.
    from app.ai.dimension_decompose import enforce_committee_requests

    favourite = PoolDimension(
        key="participation_commitment", name="Participation commitment",
        definition="Willingness to do shared work.", why_it_differentiates="varies",
    )
    # Decomposition settled on an unrelated axis only.
    settled = DecompositionReport(
        dimensions=[
            DecomposedDimension(
                key="skills_offered", name="Skills offered", definition="trades",
                source_keys=["skills_offered"],
                decision="kept",
            ),
        ],
    )
    corrected, folded = enforce_committee_requests(settled, [], favourites=[favourite])
    keys = {d.key for d in corrected.dimensions}
    assert "participation_commitment" in keys  # re-added, not lost
    readded = next(d for d in corrected.dimensions if d.key == "participation_commitment")
    assert readded.from_committee_request is True
    assert folded == []  # kept standalone, not folded into another axis


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
                    why_it_differentiates="Applicants range from eager volunteers to vague.",
                ),
                PoolDimension(
                    key="commitment_b", name="Commitment B",
                    definition="willingness to show up for work days",
                    why_it_differentiates="secondary carving why",
                ),
            ],
        ),
    ]
    settled = DecompositionReport(
        dimensions=[
            DecomposedDimension(
                key="commitment", name="Commitment",
                definition="willingness to do shared work",
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
        # participation_commitment into the Critical tier.
        route_criteria(provider, a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")
        await client.put(
            "/ranking/tiers",
            json={
                "tiers": [
                    {"id": "tier-s", "label": "Critical", "dimensionKeys": ["participation_commitment"], "ignore": False},
                    {"id": "tier-a", "label": "Important", "dimensionKeys": ["skills_offered"], "ignore": False},
                    {"id": "ignore", "label": "Ignore", "dimensionKeys": [], "ignore": True},
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
        # committee tiers skills_offered into Critical (durable intent).
        route_criteria(provider, a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")
        await client.put(
            "/ranking/tiers",
            json={
                "tiers": [
                    {"id": "tier-s", "label": "Critical", "dimensionKeys": ["skills_offered"], "ignore": False},
                    {"id": "tier-a", "label": "Important", "dimensionKeys": ["participation_commitment"], "ignore": False},
                    {"id": "ignore", "label": "Ignore", "dimensionKeys": [], "ignore": True},
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
                        why_it_differentiates="Some eager, some vague.",
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
                why_it_differentiates="Some eager, some vague.",
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
        # Run 1: discover participation_commitment + skills_offered; tier skills_offered
        # into Critical (the committee's durable intent).
        route_criteria(provider, a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")
        await client.put(
            "/ranking/tiers",
            json={
                "tiers": [
                    {"id": "tier-s", "label": "Critical", "dimensionKeys": ["skills_offered"], "ignore": False},
                    {"id": "tier-a", "label": "Important", "dimensionKeys": ["participation_commitment"], "ignore": False},
                    {"id": "ignore", "label": "Ignore", "dimensionKeys": [], "ignore": True},
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
        # It restored its Critical placement across the gap (durable committee intent).
        layout = (await client.get("/ranking/tiers")).json()["tiers"]
        by_label = {t["label"]: t for t in layout}
        assert by_label["Critical"]["dimensionKeys"] == ["skills_offered"]

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
        estimate = (await client.get("/ranking/estimate")).json()
        assert estimate["rankingCurrent"] is True
        assert (await client.post("/ranking/run")).status_code == 200


@pytest.mark.anyio
async def test_rank_estimate_combines_three_passes() -> None:
    app, db, _ = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        estimate = (await client.get("/ranking/estimate")).json()
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
        assert (await client.get("/ranking/estimate")).status_code == 409
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


# --- Discovery seeds (favourites + proposed dimensions) ----------------------


def _pattern_report_with_requested() -> PoolDimensionReport:
    """A discovery result where the model flagged one dimension as created from a
    committee request (the auto-favourite signal)."""
    return PoolDimensionReport(
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
async def test_proposed_dimension_seeds_discovery_then_clears_and_auto_favourites() -> None:
    # A proposed axis is fed to discovery; the model returns a dimension flagged
    # from_committee_request. After the run: the proposal is consumed (cleared) and
    # the flagged dimension is auto-favourited.
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
        assert seeds["favouritedKeys"] == []

        # Re-run: discovery now returns a report flagging the requested dimension.
        provider.calls.clear()
        route_criteria(provider, _pattern_report_with_requested())
        provider.route("<prior_dimensions>", DimensionMatchReport(matches=[]))  # match pass
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")

        # The proposal text reached the discovery prompt.
        discovery_prompt = next(c.prompt for c in provider.calls if "<applicant_pool>" in c.prompt)
        assert "school-age kids who'd use the playground" in discovery_prompt

        # After the run: proposal consumed (cleared); flagged dimension auto-favourited.
        current = (await client.get("/ranking/current")).json()
        assert current["proposedDimensions"] == []
        assert current["favouritedKeys"] == ["playground_age_children"]


@pytest.mark.anyio
async def test_favourited_dimension_is_injected_at_decomposition_not_discovery() -> None:
    # A favourite is injected at DECOMPOSITION (by name + definition), NOT seeded into
    # discovery — so all K discoverers stay blind. It stays favourited across the re-run.
    app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        route_criteria(provider, a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")

        # Favourite an existing dimension.
        seeds = (await client.put(
            "/ranking/seeds", json={"favouritedKeys": ["participation_commitment"]},
        )).json()
        assert seeds["favouritedKeys"] == ["participation_commitment"]

        # Re-run: the favourite recurs (match pass maps it back to its prior key).
        provider.calls.clear()
        route_criteria(provider, a_pattern_report())
        provider.route(
            "<prior_dimensions>",
            DimensionMatchReport(matches=[]),  # same keys, so no rewrite needed
        )
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")

        # Discovery stays BLIND — the favourite is NOT in the discovery prompt.
        discovery_prompt = next(c.prompt for c in provider.calls if "<applicant_pool>" in c.prompt)
        assert "<requested_axes>" not in discovery_prompt
        assert "Willingness to do shared work." not in discovery_prompt

        # The favourite's name + definition reached the DECOMPOSITION prompt instead.
        decompose_prompt = next(c.prompt for c in provider.calls if "<discovery_reports>" in c.prompt)
        assert "<favourite_axes>" in decompose_prompt
        assert "Willingness to do shared work." in decompose_prompt

        # It is still favourited after the re-run.
        current = (await client.get("/ranking/current")).json()
        assert "participation_commitment" in current["favouritedKeys"]


@pytest.mark.anyio
async def test_put_seeds_before_run_is_409() -> None:
    app, db, _ = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.put("/ranking/seeds", json={"proposedDimensions": ["x"]})
        assert resp.status_code == 409


@pytest.mark.anyio
async def test_put_seeds_rejects_unknown_favourite_key() -> None:
    # Favouriting a key that isn't a real dimension is silently dropped (validated
    # against the run's report), so a stale key can't poison the seed set.
    app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        route_criteria(provider, a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        await stream_events(client, "/ranking/run")

        seeds = (await client.put(
            "/ranking/seeds",
            json={"favouritedKeys": ["participation_commitment", "not_a_real_key"]},
        )).json()
        assert seeds["favouritedKeys"] == ["participation_commitment"]


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
