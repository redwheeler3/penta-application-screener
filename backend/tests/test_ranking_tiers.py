
import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select

from app.ai.schemas import (
    DimensionMatch,
    DimensionMatchReport,
    PoolDimension,
    PoolDimensionReport,
)
from app.db.models import User, UserRole
from tests.ranking_support import (
    _scoring_report,
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
            "analysisId": await current_analysis_id(client),
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
async def test_tier_save_blocked_while_a_rank_run_is_in_flight() -> None:
    """A tier save is rejected (409 run_in_progress) while a full rank holds the lease: that
    run already snapshotted the committee kept-list and will supersede this analysis, so a late
    edit would neither reach it nor survive it — blocking prevents the silent vanish. Once the
    run finishes (lease released), the same save succeeds. Screen/score-current don't block."""
    from app.services.run_lock import acquire_run_lock, release_run_lock

    app, db, provider = setup_app(role=UserRole.MEMBER)
    applicant = add_eligible(db, email="a@x.com", raw_hash="h1")
    route_criteria(provider, a_pattern_report())
    provider.route(
        f'"applicant_id": {applicant.id}', _scoring_report(commitment=0.5, skills=0.5)
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await stream_events(client, "/ranking/run")
        analysis_id = await current_analysis_id(client)
        layout = {
            "analysisId": analysis_id,
            "tiers": [
                {"id": "t1", "label": "Top", "dimensionKeys": ["skills_offered"], "ignore": False},
                {"id": "ignore", "label": "Ignore", "dimensionKeys": [], "ignore": True},
            ],
        }
        member = db.scalar(select(User))

        # A screen run holds the lease but touches no dimensions — the save is allowed.
        acquire_run_lock(db, user_id=member.id, kind="screen")
        assert (await client.put("/ranking/tiers", json=layout)).status_code == 200
        release_run_lock(db, user_id=member.id)

        # A full rank in flight blocks the save.
        acquire_run_lock(db, user_id=member.id, kind="rank")
        blocked = await client.put("/ranking/tiers", json=layout)
        assert blocked.status_code == 409
        assert blocked.json()["code"] == "run_in_progress"

        # Once the run finishes, the save goes through.
        release_run_lock(db, user_id=member.id)
        assert (await client.put("/ranking/tiers", json=layout)).status_code == 200


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
            "analysisId": await current_analysis_id(client),
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
            "analysisId": await current_analysis_id(client),
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
            "analysisId": await current_analysis_id(client),
            "tiers": [
                {"id": "t1", "label": "Top", "dimensionKeys": ["not_a_real_dimension"], "ignore": False},
                {"id": "ignore", "label": "Ignore", "dimensionKeys": [], "ignore": True},
            ]
        }
        assert (await client.put("/ranking/tiers", json=bad)).status_code == 400  # unknown_dimension_key


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
                "analysisId": await current_analysis_id(client),
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

        # MOVING the new dimension into a working tier does NOT clear its flag — the
        # badge rides until an explicit dismissal or the next Rank (consistent with the
        # requested pill; a member weights it and still sees it flagged as newly-arrived).
        moved = await client.put(
            "/ranking/tiers",
            json={
                "analysisId": await current_analysis_id(client),
                "tiers": [
                    {"id": "tier-s", "label": "Critical", "dimensionKeys": ["participation_commitment"], "ignore": False},
                    {"id": "tier-a", "label": "Important", "dimensionKeys": ["financial_stability"], "ignore": False},
                ]
            },
        )
        assert moved.status_code == 200
        assert moved.json()["newDimensionKeys"] == ["financial_stability"]  # still flagged after the move

        # Acknowledge the new dimension in place (badge ✕ / "mark all reviewed"): send the
        # key in acknowledgedKeys, keeping its (now working-tier) placement. Only this
        # explicit action drops it out of new_dimension_keys.
        placed_layout = (await client.get("/ranking/tiers")).json()["tiers"]
        ack = await client.put(
            "/ranking/tiers",
            json={
                "analysisId": await current_analysis_id(client),
                "tiers": placed_layout,
                "acknowledgedKeys": ["financial_stability"],
            },
        )
        assert ack.status_code == 200
        assert ack.json()["newDimensionKeys"] == []
        # And it stuck: still placed in Important (the ✕ keeps placement), just no longer flagged.
        current = (await client.get("/ranking/current")).json()
        assert current["newDimensionKeys"] == []
        layout2 = (await client.get("/ranking/tiers")).json()["tiers"]
        by_label2 = {t["label"]: t for t in layout2}
        assert "financial_stability" in by_label2["Important"]["dimensionKeys"]


@pytest.mark.anyio
async def test_dropped_prior_dimension_is_not_revived() -> None:
    """A prior dimension omitted by discovery stays absent unless explicitly kept."""
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
                "analysisId": await current_analysis_id(client),
                "tiers": [
                    {"id": "tier-s", "label": "Critical", "dimensionKeys": ["participation_commitment"], "ignore": False},
                    {"id": "tier-a", "label": "Important", "dimensionKeys": [], "ignore": False},
                    {"id": "ignore", "label": "Ignore", "dimensionKeys": ["skills_offered"], "ignore": True},
                ]
            },
        )

        # Run 2 (pool changes): discovery returns ONLY participation_commitment —
        # skills_offered dropped out. Match maps participation_commitment to its prior
        # key; skills_offered stays gone because it was not kept.
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
                "analysisId": await current_analysis_id(client),
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

        # Run 3: discovery re-surfaces skills_offered after the gap. The badge is presence-driven and route-
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
            "analysisId": await current_analysis_id(client),
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
        # analysisId is required by the schema; supply a placeholder so validation
        # passes and the router's own 409 (no analysis discovered yet) is what's asserted.
        assert (
            await client.put("/ranking/tiers", json={"analysisId": 1, "tiers": []})
        ).status_code == 409
