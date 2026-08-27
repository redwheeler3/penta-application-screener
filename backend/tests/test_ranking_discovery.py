
import pytest
from httpx2 import ASGITransport, AsyncClient

from app.ai.schemas import (
    DimensionMatch,
    DimensionMatchReport,
    PoolDimension,
    PoolDimensionReport,
)
from app.db.models import UserRole
from tests.ranking_support import (
    _scoring_report_v2,
    a_pattern_report,
    a_pattern_report_v2,
    a_scoring_report,
    add_eligible,
    current_analysis_id,
    route_criteria,
    setup_app,
    stream_events,
)


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
    from app.ai.dimension_discovery import DiscoverySeeds, build_prompt

    _app, db, _ = setup_app(role=UserRole.MEMBER)
    a = add_eligible(db, email="a@x.com", raw_hash="h1")
    apps = [a]
    bare = build_prompt(apps)
    assert "<requested_axes>" not in bare
    # An empty seed set is equivalent to no seeds.
    assert build_prompt(apps, seeds=DiscoverySeeds()) == bare


def test_build_prompt_includes_proposed_seeds() -> None:
    # Only PROPOSALS seed discovery now; favourites inject at decomposition, not here.
    from app.ai.dimension_discovery import DiscoverySeeds, build_prompt

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
            json={
                "analysisId": await current_analysis_id(client),
                "proposedDimensions": ["school-age kids who'd use the playground"],
            },
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
        # The realized axis carries the "Requested" provenance flag this run — it drives
        # the chip pill.
        assert current["requestedDimensionKeys"] == ["playground_age_children"]

        # Dismissing the pill (its ✕) via the tiers PUT clears it in the same round-trip,
        # without moving the chip (provenance, not triage). The keep set is unchanged.
        ranking = (await client.put(
            "/ranking/tiers",
            json={
                "analysisId": await current_analysis_id(client),
                "tiers": [],
                "acknowledgedRequestedKeys": ["playground_age_children"],
            },
        )).json()
        assert ranking["requestedDimensionKeys"] == []
        # And it stays cleared on a fresh read (persisted, not just echoed).
        current = (await client.get("/ranking/current")).json()
        assert current["requestedDimensionKeys"] == []


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
            json={"analysisId": await current_analysis_id(client),
                  "tiers": [{"id": "tier-s", "label": "Critical",
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
        # analysisId is required by the schema; supply a placeholder so validation passes
        # and the router's own 409 (no analysis discovered yet) is what's asserted.
        resp = await client.put(
            "/ranking/seeds", json={"analysisId": 1, "proposedDimensions": ["x"]}
        )
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
