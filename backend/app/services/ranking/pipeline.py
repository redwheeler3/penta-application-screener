"""Streaming criteria, scoring, and consolidation pipeline for a full Rank run."""

import time
from collections.abc import Callable, Generator, Iterator
from dataclasses import dataclass, replace

from sqlalchemy.orm import Session

from app.ai.analysis import (
    PassResult,
    exception_type_name,
    log,
)
from app.ai.dimension_consolidation import Consolidation, consolidate_dimensions
from app.ai.dimension_discovery import DiscoverySeeds, eligible_applications
from app.ai.dimension_scoring import applications_to_score, score_dimensions
from app.ai.pricing import MeasuredProvider, PassCost
from app.ai.provider import AIProvider
from app.ai.schemas import PoolDimensionReport
from app.core.work_cancellation import WorkCancelled
from app.db.models import Analysis, MemberRanking, User
from app.schemas.events import (
    CriteriaPhaseEvent,
    NoticeEvent,
    PhaseEvent,
    ProgressEvent,
    RankSummary,
    StageEvent,
    ThinkingEvent,
    WarningEvent,
    emit,
)
from app.schemas.events import ErrorEvent as StreamErrorEvent
from app.schemas.settings import AppSettings
from app.services.cost_report import RANK_PASS_LABELS, record_run_cost
from app.services.ranking.analysis import (
    all_known_dimensions,
    apply_consolidation,
    committee_kept_keys,
    committee_proposed_dimensions,
    create_analysis,
    get_current_analysis,
    key_history,
)
from app.services.ranking.criteria import (
    CriteriaFailure,
    CriteriaPassResult,
    CriteriaStageChange,
    run_criteria_passes,
)
from app.services.ranking.dimensions import current_dimension_report
from app.services.ranking.identity import adopt_matched_keys
from app.services.ranking.member_state import (
    carry_forward_layout,
    get_or_reconcile_member_ranking,
    tier_history,
)
from app.services.ranking.provenance import rank_configuration, rank_inputs_fingerprint
from app.services.run_lock import RunLeaseLost
from app.services.stream_worker import StreamWorker

# Phase names for the rank stream (every event carries one, so the client's
# stream switch is uniform across this job and the screening job).
CRITERIA, SCORES, CONSOLIDATE = "criteria", "scores", "consolidate"

# Separate streamed reasoning from successive criteria stages and consolidation.
THINKING_SEPARATOR = "\n\n---\n\n"


@dataclass
class ScoreTally:
    """Running totals for a scoring run, emitted as the final summary line. (Distinct from
    ``api.screening.RunTally``, which tallies a screening run's flag counts.)"""

    analyzed: int = 0
    cached: int = 0
    failed: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    # Estimated cost of regenerating reused results on the currently selected route.
    cached_saved_usd: float = 0.0
    # Count of candidates (one PassResult each) that succeeded — distinct from
    # analyzed/cached, which count per-dimension UNITS for scoring (a candidate has
    # N dimensions). "N candidates scored" in the UI reads this, not the unit sum.
    processed: int = 0
    # Completed provider replies, distinct from analyzed per-dimension cache units.
    fresh_calls: int = 0
    failed_units: int = 0

    @property
    def fresh_units(self) -> int:
        return self.analyzed + self.failed_units

    def add(self, result: PassResult) -> None:
        if result.failed:
            self.failed += 1
            self.failed_units += result.fresh_units or 0
            self.cached += result.cached_units or 0
            self.cached_saved_usd += result.cached_saved_usd or 0.0
            if result.failure_cost is not None:
                self.fresh_calls += result.failure_cost.calls
                self.cost_usd += result.failure_cost.cost_usd
                self.input_tokens += result.failure_cost.input_tokens
                self.output_tokens += result.failure_cost.output_tokens
            return
        self.processed += 1
        if not result.outcome.cached:
            self.fresh_calls += result.fresh_calls if result.fresh_calls is not None else 1
        self.input_tokens += result.outcome.input_tokens if result.outcome else 0
        self.output_tokens += result.outcome.output_tokens if result.outcome else 0
        if result.fresh_units is not None or result.cached_units is not None:
            self.analyzed += result.fresh_units or 0
            self.cached += result.cached_units or 0
            self.cached_saved_usd += result.cached_saved_usd or 0.0
            self.cost_usd += result.outcome.cost_usd
            return
        if result.outcome.cached:
            # A cache hit made no model call, so it spent nothing on THIS run. Its
            # outcome reprices the stored tokens on the selected route to estimate
            # what regeneration would have cost.
            self.cached += 1
            self.cached_saved_usd += result.outcome.cost_usd
            return
        self.analyzed += 1
        self.cost_usd += result.outcome.cost_usd

    def as_pass_cost(self, model_id: str) -> PassCost:
        """The scoring pass's spend in the shared shape (fresh tokens + cost, cache side)."""
        cost = PassCost.from_tally(self, model_id)
        return replace(cost, calls=self.fresh_calls,
            model_id=model_id if self.fresh_calls else "")


@dataclass
class _CriteriaResult:
    """What the criteria phase hands the rest of the chain: the created shared analysis and the
    triggering member's ranking of it (consolidation transfers that member's tiers), the
    dimension report, the three sub-pass costs (for the ledger), and their wall-clocks."""

    analysis: Analysis
    member_ranking: MemberRanking
    report: PoolDimensionReport
    discovery_cost: PassCost
    decompose_cost: PassCost
    match_cost: PassCost
    durations: dict[str, int]


def _stream_criteria(
    db: Session, provider: AIProvider, settings: AppSettings, user: User, opening_id: int, estimated_usd: float
) -> Generator[str, None, _CriteriaResult | None]:
    """Load prior state, stream the criteria worker, then persist the completed result.

    The worker computes AI passes and audits; database writes stay on this request
    thread. A fatal worker error emits an error event and ends the run.
    """
    # Capture prior state before discovery. Matching looks across ALL prior analyses (shared
    # dimension history); tier carry-forward looks across the TRIGGERING member's prior
    # rankings — a concept that fell out and re-surfaces should re-adopt its existing key
    # (reusing its cached scores) and restore that member's last tier placement.
    prior_analysis = get_current_analysis(db, opening_id)
    prior_report = current_dimension_report(prior_analysis) if prior_analysis else None
    match_history = all_known_dimensions(db)  # every dimension ever, one per key
    scaffold_tiers, tier_by_key = tier_history(db, user, opening_id)
    # The immediately-prior run's keys: a dimension present here is continuous in
    # the committee's view (never flagged); one absent-then-present is a presence
    # gap to flag (new or revived). See carry_forward_layout.
    immediately_prior_keys = {d.key for d in prior_report.dimensions} if prior_report else set()
    # Committee asks split by what each needs. Proposals are untested free-text hypotheses,
    # so they are seeded into discovery
    # (worker 0 only) so it grounds them in the pool and gates on variance. KEPT axes
    # (those the committee placed in a working tier) are prior dimensions already
    # grounded + scored → injected at DECOMPOSITION, not discovery, so all K
    # discoverers stay blind (seeding them would correlate the samples and cost
    # coverage). An empty set leaves discovery fully blind (first-run).
    #
    # Both are the committee union, not just the triggering member: an
    # axis survives if ANY member tiered it, and every member's proposals steer the one shared
    # discovery — so one member's re-rank can't drop another's kept axis or ignore their ask.
    # Tier carry-forward below stays per-member (the triggering member's own placements).
    committee_kept = committee_kept_keys(db, opening_id, prior_report)
    kept_dims = [
        d
        for d in (prior_report.dimensions if prior_report else [])
        if d.key in committee_kept
    ]
    seeds = DiscoverySeeds(
        proposed=committee_proposed_dimensions(db, prior_analysis),
    )

    yield emit(CriteriaPhaseEvent(discovery_workers=settings.ai.discovery_fan_out))
    pool = eligible_applications(db, opening_id)
    inputs_fingerprint = rank_inputs_fingerprint(db, opening_id, settings, applications=pool)
    configuration = rank_configuration(settings)
    worker: StreamWorker[str | CriteriaStageChange, CriteriaPassResult] = StreamWorker()
    worker.start(lambda put: run_criteria_passes(
        provider, applications=pool, settings=settings, seeds=seeds,
        kept=kept_dims, match_history=match_history, on_delta=put,
    ))
    # Separate each sub-stage's reasoning with a rule — but not before the first, so
    # the box doesn't open with a stray divider. The drain injects a keepalive during any
    # >HEARTBEAT_SECONDS silence (an opaque pass streaming no token) so the stream survives
    # a proxy idle timeout; the ping line is pre-serialized, so we just re-yield it.
    first_stage = True
    for is_ping, item in worker.drain(CRITERIA):
        if is_ping:
            yield item
            continue
        if item is None:
            break
        if isinstance(item, CriteriaStageChange):
            if not first_stage:
                yield emit(ThinkingEvent(phase=CRITERIA, text=THINKING_SEPARATOR))
            first_stage = False
            yield emit(StageEvent(phase=CRITERIA, stage=item.name))
        else:
            yield emit(ThinkingEvent(phase=CRITERIA, text=item))
    worker.join()

    if worker.error is not None:
        failure = worker.error
        exc = failure.cause if isinstance(failure, CriteriaFailure) else failure
        if isinstance(failure, CriteriaFailure):
            record_run_cost(db, kind="rank", status="failed", failed_pass=failure.failed_pass,
                failure_type=exception_type_name(exc)[:120],
                passes={label: failure.costs.get(label, PassCost()) for label in RANK_PASS_LABELS},
                durations_ms=failure.durations, estimated_usd=estimated_usd,
                triggered_by_user_id=user.id, opening_id=opening_id)
        log.warning(
            "Rank criteria phase failed: %s",
            exception_type_name(exc),
        )
        yield emit(
            StreamErrorEvent(
                phase=CRITERIA,
                message=f"Finding criteria failed: {type(exc).__name__}: {exc}",
            )
        )
        return None
    work = worker.result
    # Some (not all) fan-out discovery workers failed — the run proceeded on the
    # survivors (see discover_patterns_fanout). Warn the committee it ran degraded:
    # amber, non-fatal. All-fail already aborted upstream as a fatal criteria error.
    _failed = work.fan_out_audit.get("failed_count", 0)
    if _failed:
        _survived = work.fan_out_audit["k"]
        yield emit(
            WarningEvent(
                phase=CRITERIA,
                message=(
                    f"{_failed} of {_failed + _survived} discovery workers failed; "
                    f"continued on the {_survived} that "
                    f"succeeded. Criteria may be slightly less diverse — re-rank to retry."
                ),
            )
        )
    # For every matched dimension, adopt the prior dimension wholesale (key + text)
    # from match_history — the same history the match pass matched against — so its
    # tier placement AND cached score carry forward, and the displayed text stays
    # the wording that score was computed against.
    try:
        report = adopt_matched_keys(work.report, work.new_to_old, match_history)
        # Carry committee intent forward across ALL runs: restore each key's most-recent
        # tier placement, and flag every dimension absent from the immediately-prior run
        # (new OR revived) for triage — the new-vs-revived label is derived at read time.
        layout, new_dimension_keys = carry_forward_layout(
            new_report=report,
            scaffold_tiers=scaffold_tiers,
            most_recent_tier_by_key=tier_by_key,
            immediately_prior_keys=immediately_prior_keys,
        )
        # Create the shared analysis and seed THIS member's ranking of it (tier placements
        # carried forward above ARE their kept set — no separate field to thread through;
        # create_analysis clears the consumed proposals on the new ranking).
        analysis = create_analysis(
            db, user=user, opening_id=opening_id, report=report, inputs_fingerprint=inputs_fingerprint,
            narrative=work.narrative,
            tier_layout=layout, new_dimension_keys=new_dimension_keys,
            match_audit=work.match_audit,
            fan_out_audit=work.fan_out_audit,
            decompose_audit=work.decompose_audit,
            configuration=configuration,
        )
        member_ranking = get_or_reconcile_member_ranking(db, analysis, user)
    except (WorkCancelled, RunLeaseLost):
        raise
    except Exception as error:
        db.rollback()
        known = {"Pattern discovery": work.discovery_cost, "Dimension decomposition": work.decompose_cost,
            "Dimension matching": work.match_cost}
        record_run_cost(db, kind="rank", status="failed", failed_pass="Criteria persistence",
            failure_type=exception_type_name(error)[:120],
            passes={label: known.get(label, PassCost()) for label in RANK_PASS_LABELS},
            durations_ms=work.durations, estimated_usd=estimated_usd, triggered_by_user_id=user.id, opening_id=opening_id)
        yield emit(StreamErrorEvent(phase=CRITERIA,
            message="Saving ranking criteria failed. Previously saved results remain available."))
        return None
    yield emit(
        NoticeEvent(
            phase=CRITERIA,
            dimensions=len(report.dimensions),
            # Distinct prior dimensions reused, not mapping entries: when discovery
            # re-carves one prior axis into several twins they all map to the same
            # prior key and collapse to ONE dimension, so counting entries would
            # overcount against the (collapsed) `dimensions` shown alongside.
            carried_forward=len(set(work.new_to_old.values())),
            new_dimensions=len(new_dimension_keys),
        )
    )
    return _CriteriaResult(
        analysis=analysis, member_ranking=member_ranking, report=report,
        discovery_cost=work.discovery_cost, decompose_cost=work.decompose_cost,
        match_cost=work.match_cost, durations=work.durations,
    )


def _stream_scoring(
    db: Session, provider: AIProvider, settings: AppSettings,
    opening_id: int, report: PoolDimensionReport, tally: ScoreTally | None = None
) -> Generator[str, None, tuple[ScoreTally, int]]:
    """Phase 2 — score every eligible candidate against the new dimensions, emitting
    per-candidate progress. Returns the run's scoring tally + the pass's wall-clock (ms)."""
    to_score = applications_to_score(db, opening_id)
    yield emit(PhaseEvent(phase=SCORES, total=len(to_score)))
    tally = tally if tally is not None else ScoreTally()
    _t0 = time.perf_counter()
    for processed, result in enumerate(
        score_dimensions(
            db, provider, applications=to_score, report=report,
            settings=settings, max_workers=settings.ai.max_workers,
        ),
        start=1,
    ):
        tally.add(result)
        yield emit(ProgressEvent(phase=SCORES, processed=processed, total=len(to_score)))
    return tally, round((time.perf_counter() - _t0) * 1000)


def _stream_consolidate(
    db: Session, provider: MeasuredProvider, settings: AppSettings,
    analysis: Analysis, member_ranking: MemberRanking, report: PoolDimensionReport,
) -> Generator[str, None, tuple[Consolidation, int]]:
    """Phase 2b — consolidate duplicate dimensions.
    Now that every dimension is scored, score-vector correlation can nominate duplicates
    the definition-only match pass missed; one LLM call confirms by definition and merges
    genuine duplicates (loser aliased to the older key, which heals the fork on future
    matches too). Runs post-score because it needs the vectors. The model call runs ONCE over
    the shared pool; ``apply_consolidation`` then rewrites the shared analysis (collapse merged
    keys, write aliases) and transfers the triggering member's tiers to the survivor (other
    members heal via carry-forward on next open). Usually a no-op (correlation nominates
    nothing → $0). Returns the consolidation + its wall-clock (ms)."""
    from app.ai.score_vectors import load_score_vectors

    # One opaque model call (only when correlation nominates a pair) → an
    # indeterminate-bar phase of its own, so the UI stops showing stale scoring
    # progress while it runs. total omitted (no per-item fraction). Like the
    # criteria call it has no per-item progress, so we stream its reasoning as
    # live "thinking" too — same worker-thread/queue bridge, since a generator
    # can't yield from the provider's on_delta callback. The frontend appends
    # these deltas to the SAME reasoning box the criteria phase filled.
    yield emit(PhaseEvent(phase=CONSOLIDATE))
    _t0 = time.perf_counter()
    configuration = rank_configuration(settings)
    canonical_rank, known_defs, known_names = key_history(db)
    vectors = load_score_vectors(db)

    worker: StreamWorker[str, Consolidation] = StreamWorker()

    def run_consolidate_pass(put: Callable[[str], None]) -> Consolidation:
        return consolidate_dimensions(
            provider,
            report=report,
            canonical_rank=canonical_rank,
            vectors=vectors,
            definitions=known_defs,
            names=known_names,
            settings=settings,
            on_delta=put,
        )

    worker.start(run_consolidate_pass)
    # Criteria always ran first and left text in the box, so consolidation's reasoning
    # needs a leading rule. Emit it lazily — only once real deltas arrive — so a no-op
    # consolidation (correlation nominated nothing → no call) leaves no stray divider.
    # Same heartbeat as the criteria drain: keepalive during any long silent stretch.
    first_delta = True
    for is_ping, item in worker.drain(CONSOLIDATE):
        if is_ping:
            yield item
            continue
        if item is None:
            break
        if first_delta:
            yield emit(ThinkingEvent(phase=CONSOLIDATE, text=THINKING_SEPARATOR))
            first_delta = False
        yield emit(ThinkingEvent(phase=CONSOLIDATE, text=item))
    worker.join()

    # A consolidation failure is non-fatal — the run's scores are already saved
    # and the merge cleanup is best-effort. Log it and carry on with no merges,
    # matching the "usually a no-op" contract rather than losing the whole run.
    if worker.error is not None:
        exc = worker.error
        log.warning(
            "Rank consolidation phase failed: %s",
            exception_type_name(exc),
        )
        yield emit(WarningEvent(phase=CONSOLIDATE,
            message="Duplicate-criteria cleanup could not finish. Current criteria and scores were kept."))
    consolidation = (
        Consolidation(merges={}, narrative=None, audit=[],
            cost=replace(provider.snapshot(), failed_calls=max(1, provider.snapshot().failed_calls)))
        if worker.error is not None
        else worker.result
    )
    apply_consolidation(
        db, analysis, member_ranking,
        merges=consolidation.merges,
        audit=consolidation.audit,
        narrative=consolidation.narrative,
        configuration=configuration,
    )
    return consolidation, round((time.perf_counter() - _t0) * 1000)


def stream_rank(
    db: Session,
    provider: AIProvider,
    settings: AppSettings,
    user: User,
    *,
    opening_id: int,
    estimated_usd: float,
) -> Iterator[str]:
    """Run all Rank phases and yield their NDJSON events."""
    criteria = yield from _stream_criteria(db, provider, settings, user, opening_id, estimated_usd)
    if criteria is None:
        return
    recorded = {"Pattern discovery": criteria.discovery_cost, "Dimension decomposition": criteria.decompose_cost,
        "Dimension matching": criteria.match_cost}
    durations = dict(criteria.durations)
    score_tally = ScoreTally()
    failed_pass = "Dimension scoring"
    started = time.perf_counter()
    scoring_meter = MeasuredProvider(provider, label="Dimension scoring")
    consolidation_meter = MeasuredProvider(provider, label="Dimension consolidation")
    try:
        total_cost = (
            criteria.discovery_cost + criteria.decompose_cost + criteria.match_cost
        ).cost_usd

        score_tally, scoring_ms = yield from _stream_scoring(
            db,
            scoring_meter,
            settings,
            opening_id,
            criteria.report, tally=score_tally,
        )
        total_cost += score_tally.cost_usd
        recorded["Dimension scoring"] = score_tally.as_pass_cost(settings.ai.dimension_scoring_model)
        durations["Dimension scoring"] = scoring_ms

        failed_pass = "Dimension consolidation"
        started = time.perf_counter()
        consolidation, consolidate_ms = yield from _stream_consolidate(
            db,
            consolidation_meter,
            settings,
            criteria.analysis,
            criteria.member_ranking,
            criteria.report,
        )
        total_cost += consolidation.cost.cost_usd
        final_report = current_dimension_report(criteria.analysis)
        dimension_count = len(final_report.dimensions) if final_report is not None else 0

    except (WorkCancelled, RunLeaseLost):
        raise
    except Exception as error:
        db.rollback()
        active_meter = scoring_meter if failed_pass == "Dimension scoring" else consolidation_meter
        recorded[failed_pass] = active_meter.failed_pass_cost(
            score_tally.as_pass_cost(settings.ai.dimension_scoring_model)
            if failed_pass == "Dimension scoring" else PassCost())
        durations[failed_pass] = round((time.perf_counter() - started) * 1000)
        record_run_cost(db, kind="rank", status="failed", failed_pass=failed_pass,
            failure_type=exception_type_name(error)[:120],
            passes={label: recorded.get(label, PassCost()) for label in RANK_PASS_LABELS},
            durations_ms=durations, estimated_usd=estimated_usd, triggered_by_user_id=user.id, opening_id=opening_id)
        yield emit(StreamErrorEvent(phase=SCORES if failed_pass == "Dimension scoring" else CONSOLIDATE,
            message=f"Ranking failed during {failed_pass}. Saved results remain available."))
        return

    record_run_cost(
        db,
        kind="rank",
        passes={
            "Pattern discovery": criteria.discovery_cost,
            "Dimension decomposition": criteria.decompose_cost,
            "Dimension matching": criteria.match_cost,
            "Dimension scoring": score_tally.as_pass_cost(
                settings.ai.dimension_scoring_model
            ),
            "Dimension consolidation": consolidation.cost,
        },
        durations_ms={
            **criteria.durations,
            "Dimension scoring": scoring_ms,
            "Dimension consolidation": consolidate_ms,
        },
        estimated_usd=estimated_usd,
        triggered_by_user_id=user.id,
        opening_id=opening_id,
        dimension_count=dimension_count,
    )

    yield emit(
        RankSummary(
            dimensions=dimension_count,
            scored=score_tally.processed,
            failed=score_tally.failed,
            total_cost_usd=round(total_cost, 4),
        )
    )
