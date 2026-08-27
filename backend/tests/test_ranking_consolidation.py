
import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select

from app.ai.schemas import (
    ConsolidationReport,
    ConsolidationVerdict,
    DecomposedDimension,
    DecompositionReport,
    DimensionScore,
    DimensionScoringReport,
    PoolDimension,
    PoolDimensionReport,
    ScoreConfidence,
)
from app.db.models import User, UserRole
from tests.ranking_support import (
    _decomposition_of,
    add_eligible,
    setup_app,
    stream_events,
)


@pytest.mark.anyio
async def test_decomposition_merges_axes_and_records_the_merge() -> None:
    # Decomposition settles parallel discovery reports before scoring. Here discovery emits
    # three axes but decomposition merges
    # two into one, so the run must end with 2 settled dims (not 3), score against those,
    # and record the merge (source_keys + reasoning) in criteria.decompose_audit.
    from app.services.ranking.analysis import get_current_analysis

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

        # The decompose-audit endpoint surfaces the merge (the Observability panel's source).
        endpoint = (await client.get("/ranking/current/decompose-audit")).json()
        assert endpoint["mergeCount"] == 1
        assert endpoint["settledCount"] == 2
        merged_out = next(d for d in endpoint["settled"] if d["key"] == "commitment")
        assert set(merged_out["sourceKeys"]) == {"commitment_a", "commitment_b"}

    run = get_current_analysis(db)
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
    from app.services.ranking.analysis import get_current_analysis

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

    run = get_current_analysis(db)
    keys = {d["key"] for d in run.dimension_report["dimensions"]}
    # Collapsed 2 → 1: the newer key (financial_stewardship) is aliased into the older.
    assert keys == {"financial_literacy"}

    # merges isn't stored on the audit; the view derives it from the merged pairs.
    from app.services.ranking.audit import consolidate_audit_view
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
    from app.services.ranking.analysis import (
        apply_consolidation,
        create_analysis,
    )
    from app.services.ranking.member_state import (
        get_or_create_member_ranking,
        kept_keys,
        set_tiers,
    )

    _app, db, _ = setup_app(role=UserRole.MEMBER)
    user = db.scalar(select(User))
    report = PoolDimensionReport(dimensions=[
        PoolDimension(key="financial_literacy", name="Financial literacy",
                      definition="handles money", high_end="high", low_end="low", why_it_differentiates="v"),
        PoolDimension(key="financial_stewardship", name="Financial stewardship",
                      definition="bookkeeping", high_end="high", low_end="low", why_it_differentiates="v"),
    ])
    analysis = create_analysis(db, user=user, report=report, settings=AppSettings(), narrative=None)
    mr = get_or_create_member_ranking(db, analysis, user)
    # The committee places ONLY the key that will be merged away into a working tier —
    # the survivor sits in Ignore (unplaced).
    set_tiers(db, mr, [{"id": "tier-s", "label": "Critical",
                        "dimension_keys": ["financial_stewardship"]}])
    assert kept_keys(mr) == ["financial_stewardship"]

    apply_consolidation(
        db, analysis, mr,
        merges={"financial_stewardship": "financial_literacy"},
        audit=[{"keep": "financial_literacy", "drop": "financial_stewardship",
                "r": 0.94, "merged": True, "reason": "same concept"}],
        narrative=None,
    )
    # The survivor inherited the dropped twin's Critical placement, so it stays kept.
    assert kept_keys(mr) == ["financial_literacy"]
    keys = {d["key"] for d in analysis.dimension_report["dimensions"]}
    assert keys == {"financial_literacy"}
    assert mr.run_state["tiers"][0]["dimension_keys"] == ["financial_literacy"]


def test_apply_consolidation_reconfirming_an_existing_alias_is_idempotent() -> None:
    # Re-confirming the same merge must upsert the alias without violating uniqueness.
    from sqlalchemy import select

    from app.db.models import DimensionAlias
    from app.schemas.settings import AppSettings
    from app.services.ranking.analysis import (
        apply_consolidation,
        create_analysis,
    )
    from app.services.ranking.member_state import (
        get_or_create_member_ranking,
    )

    _app, db, _ = setup_app(role=UserRole.MEMBER)
    user = db.scalar(select(User))

    def run_with_merge(reason: str) -> None:
        report = PoolDimensionReport(dimensions=[
            PoolDimension(key="financial_literacy", name="FL", definition="d", high_end="high", low_end="low", why_it_differentiates="v"),
            PoolDimension(key="financial_stewardship", name="FS", definition="d", high_end="high", low_end="low", why_it_differentiates="v"),
        ])
        analysis = create_analysis(db, user=user, report=report, settings=AppSettings(),
                                   narrative=None)
        mr = get_or_create_member_ranking(db, analysis, user)
        apply_consolidation(
            db, analysis, mr,
            merges={"financial_stewardship": "financial_literacy"},
            audit=[{"keep": "financial_literacy", "drop": "financial_stewardship",
                    "r": 0.94, "merged": True, "reason": reason}],
            narrative=None,
        )

    run_with_merge("first time")
    run_with_merge("re-minted and re-confirmed")

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
    from app.services.ranking.analysis import (
        apply_consolidation,
        create_analysis,
    )
    from app.services.ranking.member_state import (
        get_or_create_member_ranking,
        kept_keys,
        set_tiers,
    )

    _app, db, _ = setup_app(role=UserRole.MEMBER)
    user = db.scalar(select(User))
    report = PoolDimensionReport(dimensions=[
        PoolDimension(key="a_oldest", name="A", definition="d", high_end="high", low_end="low", why_it_differentiates="v"),
        PoolDimension(key="b_mid", name="B", definition="d", high_end="high", low_end="low", why_it_differentiates="v"),
        PoolDimension(key="c_newest", name="C", definition="d", high_end="high", low_end="low", why_it_differentiates="v"),
    ])
    analysis = create_analysis(db, user=user, report=report, settings=AppSettings(), narrative=None)
    mr = get_or_create_member_ranking(db, analysis, user)
    # Place ONLY the innermost link C in a working tier; A and B sit in Ignore.
    set_tiers(db, mr, [{"id": "tier-s", "label": "Critical", "dimension_keys": ["c_newest"]}])

    apply_consolidation(
        db, analysis, mr,
        merges={"c_newest": "b_mid", "b_mid": "a_oldest"},  # chain, not a flat map
        audit=[
            {"keep": "b_mid", "drop": "c_newest", "r": 0.95, "merged": True, "reason": "c=b"},
            {"keep": "a_oldest", "drop": "b_mid", "r": 0.88, "merged": True, "reason": "b=a"},
        ],
        narrative=None,
    )

    # Only the terminal survivor remains, and C's placement followed the full chain to it.
    keys = {d["key"] for d in analysis.dimension_report["dimensions"]}
    assert keys == {"a_oldest"}
    assert kept_keys(mr) == ["a_oldest"]
    assert mr.run_state["tiers"][0]["dimension_keys"] == ["a_oldest"]
    # Both aliases point straight at the survivor — no mid-chain key persisted.
    aliases = {a.alias_key: a.canonical_key for a in db.scalars(select(DimensionAlias))}
    assert aliases == {"c_newest": "a_oldest", "b_mid": "a_oldest"}


def test_apply_consolidation_surfaces_a_prior_key_on_a_cross_run_heal() -> None:
    # Cross-run fork heal: this run discovered only the NEWER twin (child_age_profile);
    # the definition-match pass missed the fork, so the surviving canonical key
    # (child_age_profile_community_fit, a PRIOR-run key) is NOT in this run's report.
    # Consolidation must drop the newer twin AND surface the canonical prior key with its
    # frozen mint record, restored to the tier the committee last placed it in.
    from sqlalchemy import select

    from app.db.models import DimensionAlias
    from app.schemas.settings import AppSettings
    from app.services.ranking.analysis import (
        apply_consolidation,
        create_analysis,
    )
    from app.services.ranking.member_state import (
        dimension_weights,
        get_or_create_member_ranking,
    )

    _app, db, _ = setup_app(role=UserRole.MEMBER)
    user = db.scalar(select(User))
    canonical_def = "Ages of children, reflecting shared-space interaction and supervision load."

    # Run 1: mint the canonical key and place it in the Important tier.
    create_analysis(
        db,
        user=user,
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
    analysis2 = create_analysis(
        db,
        user=user,
        report=PoolDimensionReport(dimensions=[
            PoolDimension(key="child_age_profile", name="Household Children's Ages",
                          definition="A re-worded, differently-scoped take on child ages.",
                          high_end="teens", low_end="infants", why_it_differentiates="v"),
        ]),
        settings=AppSettings(), narrative=None,
    )
    mr2 = get_or_create_member_ranking(db, analysis2, user)

    apply_consolidation(
        db, analysis2, mr2,
        merges={"child_age_profile": "child_age_profile_community_fit"},
        audit=[{"keep": "child_age_profile_community_fit", "drop": "child_age_profile",
                "r": 0.803, "merged": True, "reason": "same age axis"}],
        narrative=None,
    )

    dims = {d["key"]: d for d in analysis2.dimension_report["dimensions"]}
    # The newer twin is gone; the canonical prior key is surfaced in its place.
    assert set(dims) == {"child_age_profile_community_fit"}
    # Surfaced with its FROZEN MINT record — never the twin's re-worded text.
    assert dims["child_age_profile_community_fit"]["definition"] == canonical_def
    # Restored to the working tier the committee last placed it in (Important).
    tiers = {t["id"]: t["dimension_keys"] for t in mr2.run_state["tiers"]}
    assert tiers["tier-a"] == ["child_age_profile_community_fit"]
    # Weight is derived for the surfaced key, not the dropped twin.
    weights = dimension_weights(mr2)
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
    from app.services.ranking.analysis import create_analysis
    from app.services.ranking.audit import consolidate_audit_view

    _app, db, _ = setup_app(role=UserRole.MEMBER)

    def _dim(key: str, name: str) -> PoolDimension:
        return PoolDimension(key=key, name=name, definition="d",
                             high_end="hi", low_end="lo", why_it_differentiates="v")

    # A run whose report has the survivor key, whose decompose audit names a key that was
    # retired within the run (so it's in no report), and whose consolidate_audit pairs
    # carry NO snapshotted names (the pre-capture shape).
    run = create_analysis(
        db,
        user=db.scalar(select(User)),
        report=PoolDimensionReport(dimensions=[_dim("survivor", "Survivor Axis")]),
        settings=AppSettings(), narrative=None,
    )
    run.audit.decompose = {
        "settled": [{"key": "retired_within_run", "name": "Retired Within Run", "source_keys": []}],
    }
    run.audit.consolidate = {
        "pairs": [
            # Stored audit without captured names.
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
    from app.services.ranking.analysis import create_analysis
    from app.services.ranking.audit import consolidate_audit_view

    _app, db, _ = setup_app(role=UserRole.MEMBER)
    run = create_analysis(
        db,
        user=db.scalar(select(User)),
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
    # Key text is frozen at mint because cached scores were computed against it. Aliases
    # must not donate differently scoped text to the canonical key.
    from app.schemas.settings import AppSettings
    from app.services.ranking.analysis import (
        all_known_dimensions,
        apply_consolidation,
        create_analysis,
        key_history,
    )
    from app.services.ranking.member_state import (
        get_or_create_member_ranking,
    )

    _app, db, _ = setup_app(role=UserRole.MEMBER)
    user = db.scalar(select(User))
    narrow = "Formal licensed trade qualifications only (legally-regulated work)."
    broad = "Any licensed OR practised hands-on trade skill, incl. unlicensed crafts."

    def _dim(key: str, definition: str) -> PoolDimension:
        return PoolDimension(key=key, name=key, definition=definition,
                             high_end="hi", low_end="lo", why_it_differentiates="v")

    # Run 1: mint the narrow key. Its cached scores (not modelled here) belong to THIS text.
    create_analysis(db, user=user, report=PoolDimensionReport(dimensions=[_dim("licensed_trade", narrow)]),
                    settings=AppSettings(), narrative=None)
    # Run 2: a broader duplicate appears alongside, and is merged INTO the narrow key
    # (older key wins the merge). This writes the alias hands_on_trade -> licensed_trade.
    analysis2 = create_analysis(db, user=user, report=PoolDimensionReport(dimensions=[
        _dim("licensed_trade", narrow), _dim("hands_on_trade", broad),
    ]), settings=AppSettings(), narrative=None)
    mr2 = get_or_create_member_ranking(db, analysis2, user)
    apply_consolidation(
        db, analysis2, mr2,
        merges={"hands_on_trade": "licensed_trade"},
        audit=[{"keep": "licensed_trade", "drop": "hands_on_trade", "r": 0.93,
                "merged": True, "reason": "same axis"}],
        narrative=None,
    )
    # Run 3: the broad concept re-surfaces under its OWN key, and the canonical narrow key
    # does NOT appear on its own. This is the trigger: a newest-first history builder would
    # reach the broad re-discovery (resolved via alias to licensed_trade) BEFORE the narrow
    # canonical's own mint, and donate the broad text to the narrow key.
    create_analysis(db, user=user, report=PoolDimensionReport(dimensions=[_dim("hands_on_trade", broad)]),
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
    from app.services.ranking.analysis import get_current_analysis

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

    run = get_current_analysis(db)
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
    from app.services.ranking.analysis import get_current_analysis

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

    run = get_current_analysis(db)
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
    from app.services.ranking.analysis import get_current_analysis

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

    run = get_current_analysis(db)
    keys = {d["key"] for d in run.dimension_report["dimensions"]}
    # The dropped request was re-added, so both axes survive.
    assert keys == {"child_wellbeing", "playground_use"}
    readded = next(
        d for d in run.audit.decompose["settled"] if d["key"] == "playground_use"
    )
    assert readded["from_committee_request"] is True
