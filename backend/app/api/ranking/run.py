"""Rank: the combined criteria → scores chain, plus its cost estimates.

The endpoints here spend real model calls (or project what they would spend):

  - GET  /estimate — combined cost projection for a full Rank (before the cap check).
  - GET  /score-current/estimate — exact cache-aware cost to fill missing scores only.
  - POST /score-current — fill missing scores without changing dimensions or tiers.
  - POST /run — the full chain (find criteria → score → consolidate), streaming NDJSON.

``rank_run`` is the heart of the app. Its ``stream()`` reads as a short pipeline — criteria
→ scoring → consolidation → record+summary — with each phase a ``_stream_*`` helper that
yields NDJSON and returns its result (captured via ``yield from``). The criteria and
consolidation phases bridge the providers' streamed reasoning through a worker-thread/queue
into ``thinking`` deltas (a generator can't yield from the provider's callback). The combined
cost is checked against the cap once before any model call, so an over-cap run fails fast and
spends nothing.
"""

import logging
import queue
import threading
import time
from collections.abc import Generator, Iterator
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai.analysis import (
    PassResult,
    SpendingCapExceeded,
    enforce_cap,
    exception_type_name,
    log,
)
from app.ai.dimension_consolidate import (
    Consolidation,
    consolidate_dimensions,
    estimate_consolidate,
)
from app.ai.dimension_decompose import (
    decompose_audit_payload,
    decompose_dimensions,
    enforce_committee_requests,
    estimate_decompose,
    to_pool_report,
)
from app.ai.dimension_matching import estimate_match, match_dimensions
from app.ai.dimension_scoring import (
    applications_needing_scores,
    applications_to_score,
    score_dimensions,
)
from app.ai.dimension_scoring_cost import estimate_dimension_scoring
from app.ai.pattern_discovery import (
    DiscoverySeeds,
    discover_patterns_fanout,
    eligible_applications,
    estimate_discovery,
)
from app.ai.pricing import PassCost
from app.ai.provider import AIProvider
from app.ai.schemas import PoolDimension, PoolDimensionReport
from app.api.dependencies import get_ai_provider, require_current_user
from app.api.problems import Problem
from app.db.models import RankingRun, User
from app.db.session import get_db
from app.schemas.events import ErrorEvent as StreamErrorEvent
from app.schemas.events import (
    NoticeEvent,
    PhaseEvent,
    ProgressEvent,
    RankSummary,
    StageEvent,
    ThinkingEvent,
    WarningEvent,
    emit,
)
from app.schemas.ranking import (
    RankEstimateBreakdown,
    RankEstimateResponse,
    ScoreCurrentEstimateResponse,
)
from app.schemas.settings import AppSettings
from app.services.cost_report import (
    SCORE_CURRENT_KIND,
    recent_pass_fresh_usd,
    record_run_cost,
)
from app.services.ranking_run import (
    adopt_matched_keys,
    all_known_dimensions,
    apply_consolidation,
    carry_forward_layout,
    create_run,
    current_dimension_report,
    get_current_run,
    kept_keys,
    key_history,
    mark_ranking_current,
    proposed_dimensions,
    ranking_is_current,
    tier_history,
)
from app.services.settings import get_app_settings

router = APIRouter(prefix="/ranking")

# Phase names for the rank stream (every event carries one, so the client's
# stream switch is uniform across this job and the screening job).
CRITERIA, SCORES, CONSOLIDATE = "criteria", "scores", "consolidate"

# Sub-stages within the criteria phase — the sequential model calls under its one
# banner, surfaced so the UI can say which step is running (they're opaque calls with
# no per-item progress). Emitted as StageEvents; see _run_criteria_passes + the drain loop.
CRITERIA_STAGES = {
    "discovering": "discovering",
    "settling": "settling",
    "matching": "matching",
}

# A markdown horizontal rule streamed into the reasoning box between sections (each
# criteria sub-stage, and consolidation), so the model's reasoning for one step reads
# as visually distinct from the next. ReactMarkdown renders it as an <hr>. Emitted as
# a thinking delta — the frontend appends it like any other, staying a dumb sink.
THINKING_SEPARATOR = "\n\n---\n\n"


class _Stage:
    """A sentinel pushed onto the criteria delta queue to mark a sub-stage transition,
    so the drain loop can tell it apart from a reasoning-text delta (a plain str) and
    emit a StageEvent instead of a ThinkingEvent."""

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name


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
    # Sum of reused results' ORIGINAL cost — an estimate of what caching saved this run.
    cached_saved_usd: float = 0.0
    # Count of candidates (one PassResult each) that succeeded — distinct from
    # analyzed/cached, which count per-dimension UNITS for scoring (a candidate has
    # N dimensions). "N candidates scored" in the UI reads this, not the unit sum.
    processed: int = 0

    def add(self, result: PassResult) -> None:
        if result.failed:
            self.failed += 1
            return
        self.processed += 1
        self.input_tokens += result.outcome.input_tokens if result.outcome else 0
        self.output_tokens += result.outcome.output_tokens if result.outcome else 0
        if result.fresh_units is not None or result.cached_units is not None:
            self.analyzed += result.fresh_units or 0
            self.cached += result.cached_units or 0
            self.cached_saved_usd += result.cached_saved_usd or 0.0
            self.cost_usd += result.outcome.cost_usd
            return
        if result.outcome.cached:
            # A cache hit made no model call, so it spent nothing on THIS run; its
            # stored cost is the original first-run cost, so summing it estimates what
            # regenerating would have cost (what caching saved).
            self.cached += 1
            self.cached_saved_usd += result.outcome.cost_usd
            return
        self.analyzed += 1
        self.cost_usd += result.outcome.cost_usd

    def as_pass_cost(self, model_id: str) -> PassCost:
        """The scoring pass's spend in the shared shape (fresh tokens + cost, cache side)."""
        return PassCost(
            calls=self.analyzed,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cost_usd=self.cost_usd,
            cached_count=self.cached,
            cached_saved_usd=self.cached_saved_usd,
            failed_calls=self.failed,
            model_id=model_id if self.analyzed else "",
        )


def _rank_estimate(db: Session, settings: AppSettings) -> dict[str, Any]:
    """Combined projected cost of the Rank passes (K-discovery + decompose → match →
    scoring).

    The K parallel discovery calls always re-run (uncached), and the decomposition that
    settles them is one more call — both folded into ``criteria_usd``. The match pass adds
    a call only when a prior run exists. Scoring is priced as a whole-pool ceiling (every
    candidate × every dimension) because the estimate runs before discovery, so it can't
    yet know how many dimensions carry forward. Per-dimension reuse makes the actual run
    come in under this ceiling, so the total is an upper bound (the confirmation labels it
    approximate).
    """
    pool = eligible_applications(db)
    # Fan-out: K parallel discovery calls (SPEC "Fan-Out Redesign", D6), each priced
    # like the single call. Discovery is uncached, so K multiplies straight through —
    # the bigger-than-expected half of the fan-out cost (see the cost-model note).
    # Prefer MEASURED cost from recent runs; fall back to a seed estimate only when
    # there's no history (per .clinerules: history is the honest predictor — it self-
    # corrects when a prompt change moves output size, unlike a hand-tuned token guess).
    # The ledger stores discovery as the summed K-call cost, so the measured value is
    # already the whole fan-out — do NOT multiply by K again; the seed fallback does.
    measured_discovery = recent_pass_fresh_usd(db, "Pattern discovery")
    discovery_usd = (
        measured_discovery
        if measured_discovery is not None
        else estimate_discovery(pool, settings) * settings.ai.discovery_fan_out
    )
    # Decomposition: measured from history, else a seed from projected input size (K
    # reports × ~20 dims each, since the real reports don't exist pre-run).
    measured_decompose = recent_pass_fresh_usd(db, "Dimension decomposition")
    if measured_decompose is not None:
        decompose_usd = measured_decompose
    else:
        _stub = PoolDimension(
            key="x", name="x", definition="x", high_end="x", low_end="x", why_it_differentiates="x"
        )
        projected = [
            PoolDimensionReport(dimensions=[_stub] * 20)
            for _ in range(settings.ai.discovery_fan_out)
        ]
        decompose_usd = estimate_decompose(projected, settings)
    # A match pass runs only when there is a prior run to match against. Measured from
    # history when we have it (same principle as the other passes); the flat-token
    # estimate_match is the seed for the first re-run before any match cost is recorded.
    has_prior = get_current_run(db) is not None
    if not has_prior:
        match_usd = 0.0
    else:
        measured_match = recent_pass_fresh_usd(db, "Dimension matching")
        match_usd = measured_match if measured_match is not None else estimate_match(settings)
    scoring = estimate_dimension_scoring(db, settings, include_coverage=False)
    scoring_usd = float(scoring["estimated_usd"])
    # Post-score consolidation: a ceiling — the confirm call fires only when correlation
    # nominates a duplicate pair (often none). Measured from history when available, else
    # the flat seed; folded into criteria (it's criteria-cleanup) so the breakdown sums.
    measured_consolidate = recent_pass_fresh_usd(db, "Dimension consolidation")
    consolidate_usd = (
        measured_consolidate if measured_consolidate is not None else estimate_consolidate(settings)
    )
    total = round(discovery_usd + decompose_usd + match_usd + scoring_usd + consolidate_usd, 4)
    return {
        "eligible": len(pool),
        # K parallel discoveries per Rank (D6), so the confirm card can name the fan-out.
        "fan_out": settings.ai.discovery_fan_out,
        "breakdown": {
            # criteria = K discovery + decomposition + the post-score consolidation cleanup.
            "criteria_usd": round(discovery_usd + decompose_usd + consolidate_usd, 4),
            "match_usd": round(match_usd, 4),
            "scoring_usd": round(scoring_usd, 4),
        },
        "estimated_usd": total,
        "approximate": True,  # scoring is a ceiling; carry-forward reuse lowers the real cost
    }


@router.get("/estimate", response_model=RankEstimateResponse)
def rank_estimate(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> RankEstimateResponse:
    settings: AppSettings = get_app_settings(db)
    if not eligible_applications(db):
        raise Problem("no_eligible_applications", detail="No eligible applications to rank.")
    result = _rank_estimate(db, settings)
    cap = settings.ai.spending_cap_usd
    breakdown = result["breakdown"]
    return RankEstimateResponse(
        eligible=result["eligible"],
        fan_out=result["fan_out"],
        breakdown=RankEstimateBreakdown(
            criteria_usd=breakdown["criteria_usd"],
            match_usd=breakdown["match_usd"],
            scoring_usd=breakdown["scoring_usd"],
        ),
        estimated_usd=result["estimated_usd"],
        approximate=result["approximate"],
        cap_usd=cap,
        within_cap=result["estimated_usd"] <= cap,
        # When the pool is unchanged, the ranking is already current; the UI uses
        # this to say "up to date" instead of offering to spend.
        ranking_current=ranking_is_current(db, get_current_run(db), settings),
    )


def _current_scoring_estimate(
    db: Session, settings: AppSettings
) -> tuple[PoolDimensionReport, dict[str, object]]:
    """Return the current criteria and an exact cache-aware scoring estimate.

    Unlike a full Rank, this path never discovers, matches, consolidates, or creates a
    run. It only fills cache misses for the current run's dimensions.
    """
    run = get_current_run(db)
    report = current_dimension_report(run) if run is not None else None
    if report is None:
        raise Problem(
            "run_required",
            detail="Discover ranking criteria before scoring applicants against them.",
        )
    return report, estimate_dimension_scoring(db, settings, prefer_history=False)


@router.get("/score-current/estimate", response_model=ScoreCurrentEstimateResponse)
def score_current_estimate(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ScoreCurrentEstimateResponse:
    settings = get_app_settings(db)
    report, result = _current_scoring_estimate(db, settings)
    estimated_usd = float(result["estimated_usd"])
    return ScoreCurrentEstimateResponse(
        eligible=int(result["total"]),
        to_analyze=int(result["to_analyze"]),
        cached=int(result["cached"]),
        dimensions=len(report.dimensions),
        estimated_usd=estimated_usd,
        cap_usd=settings.ai.spending_cap_usd,
        within_cap=estimated_usd <= settings.ai.spending_cap_usd,
    )


@router.post("/score-current")
def score_current(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
    provider: AIProvider = Depends(get_ai_provider),
) -> StreamingResponse:
    """Fill missing scores without changing the current dimensions or tier layout."""
    settings = get_app_settings(db)
    report, estimate = _current_scoring_estimate(db, settings)
    if int(estimate["to_analyze"]) == 0:
        raise Problem(
            "unchanged_pool",
            detail="Every eligible applicant is already scored against the current criteria.",
        )
    try:
        enforce_cap(estimate, settings.ai.spending_cap_usd)
    except SpendingCapExceeded as exc:
        raise Problem(
            "cap_exceeded",
            detail=str(exc),
            cap_usd=settings.ai.spending_cap_usd,
            estimated_usd=float(estimate["estimated_usd"]),
        ) from exc

    # Restrict the work list before streaming so the progress count means applicants
    # that actually need a model call, not every eligible applicant.
    candidates = applications_needing_scores(
        db, report, settings.ai.dimension_scoring_model
    )

    def stream() -> Iterator[str]:
        yield emit(PhaseEvent(phase=SCORES, total=len(candidates)))
        tally = ScoreTally()
        started = time.perf_counter()
        for processed, result in enumerate(
            score_dimensions(
                db, provider, applications=candidates, report=report,
                settings=settings, max_workers=settings.ai.max_workers,
            ),
            start=1,
        ):
            tally.add(result)
            yield emit(ProgressEvent(phase=SCORES, processed=processed, total=len(candidates)))
        if tally.failed == 0:
            # Choosing the score-only path is an explicit committee decision to retain
            # these criteria for the changed pool. Re-stamp only after complete success;
            # a partial score run must stay amber and invite a retry.
            run = get_current_run(db)
            if run is not None:
                mark_ranking_current(db, run, settings)
        record_run_cost(
            db,
            kind=SCORE_CURRENT_KIND,
            passes={"Dimension scoring": tally.as_pass_cost(settings.ai.dimension_scoring_model)},
            durations_ms={"Dimension scoring": round((time.perf_counter() - started) * 1000)},
            estimated_usd=float(estimate["estimated_usd"]),
        )
        yield emit(
            RankSummary(
                dimensions=len(report.dimensions),
                scored=tally.processed,
                failed=tally.failed,
                total_cost_usd=round(tally.cost_usd, 4),
            )
        )

    return StreamingResponse(stream(), media_type="application/x-ndjson")


# --- Rank: the criteria → scores → consolidation chain -----------------------
#
# ``rank_run`` streams the three phases below in order. Each is a ``_stream_*`` generator
# that yields NDJSON lines and returns its result; ``rank_run.stream()`` threads those
# results together and writes the run's cost ledger + summary at the end.


@dataclass
class _CriteriaWork:
    """The criteria worker thread's raw output, handed back to ``_stream_criteria`` after
    the thread joins (the thread computes the AI passes; the generator does the DB writes
    and event emission, which must stay on the request thread)."""

    report: PoolDimensionReport
    narrative: str | None
    discovery_cost: PassCost
    new_to_old: dict[str, str]
    match_narrative: str | None
    match_cost: PassCost
    fan_out_reports: list[PoolDimensionReport]
    decomposition: Any
    decompose_cost: PassCost
    folded_requests: Any
    fan_out_audit: dict[str, Any]


@dataclass
class _CriteriaResult:
    """What the criteria phase hands the rest of the chain: the created run, its dimension
    report, the three sub-pass costs (for the ledger), and their wall-clocks."""

    run: RankingRun
    report: PoolDimensionReport
    discovery_cost: PassCost
    decompose_cost: PassCost
    match_cost: PassCost
    durations: dict[str, int]


def _stream_criteria(
    db: Session, provider: AIProvider, settings: AppSettings
) -> Generator[str, None, _CriteriaResult | None]:
    """Phase 1 — find criteria: K-parallel discovery → decomposition → identity-match onto
    prior dimensions → adopt matched keys → carry tiers forward → create the run. The
    sub-passes are opaque multi-minute model calls, so their reasoning streams live via a
    worker thread that pushes deltas onto a queue this generator drains into
    ``thinking``/``stage`` events. Returns the run + per-pass costs, or ``None`` after
    emitting a fatal ``error`` (the caller then aborts the whole stream)."""
    # Capture prior state before discovery. Matching and tier carry-forward both
    # look across ALL prior runs, not just the last: a concept that fell out and
    # re-surfaces should re-adopt its existing key (reusing its cached scores) and
    # restore the committee's last tier placement for it. See SPEC "Matching scope".
    prior_run = get_current_run(db)
    prior_report = current_dimension_report(prior_run) if prior_run else None
    match_history = all_known_dimensions(db)  # every dimension ever, one per key
    scaffold_tiers, tier_by_key, _known_keys = tier_history(db)
    # The immediately-prior run's keys: a dimension present here is continuous in
    # the committee's view (never flagged); one absent-then-present is a presence
    # gap to flag (new or revived). See carry_forward_layout.
    immediately_prior_keys = {d.key for d in prior_report.dimensions} if prior_report else set()
    # Committee asks split by what each needs (SPEC "Fan-Out Redesign", committee-axis
    # injection). PROPOSALS are untested free-text hypotheses → seeded into discovery
    # (worker 0 only) so it grounds them in the pool and gates on variance. KEPT axes
    # (those the committee placed in a working tier) are prior dimensions already
    # grounded + scored → injected at DECOMPOSITION, not discovery, so all K
    # discoverers stay blind (seeding them would correlate the samples and cost
    # coverage). An empty set leaves discovery fully blind (first-run).
    prior_kept = kept_keys(prior_run) if prior_run else []
    kept_dims = [
        d
        for d in (prior_report.dimensions if prior_report else [])
        if d.key in set(prior_kept)
    ]
    seeds = DiscoverySeeds(
        proposed=proposed_dimensions(prior_run) if prior_run else [],
    )

    # Carry K (the fan-out width) on the criteria phase event's `total` so the UI can
    # name it ("Running K parallel discovery passes…"). Criteria has no per-item
    # fraction, so `total` is free to repurpose as this count.
    yield emit(PhaseEvent(phase=CRITERIA, total=settings.ai.discovery_fan_out))
    pool = eligible_applications(db)
    # Discovery and match are single multi-minute model calls with no per-item
    # progress, so we STREAM their reasoning text as live "thinking". The
    # provider invokes on_delta from inside the call; a generator can't yield
    # from a callback, so the work runs on a worker thread that pushes deltas
    # onto a queue, and this generator drains the queue into NDJSON lines.
    # A None sentinel marks the work done; the worker stashes its outcome/error.
    # Queue items: str = a reasoning-text delta, _Stage = a sub-stage transition,
    # None = work complete. The drain loop below fans these into the right events.
    delta_queue: queue.Queue[str | _Stage | None] = queue.Queue()
    criteria_outcome: dict[str, Any] = {}
    # Per-pass wall-clock (ms) for the criteria sub-passes, filled as each runs and
    # read back after the worker joins (M13 Pillar 3). On this dict, not the result
    # object, since the worker thread fills it while the generator drains.
    durations: dict[str, int] = {}

    def on_delta(text: str) -> None:
        delta_queue.put(text)

    def run_criteria_passes() -> None:
        try:
            # Pass 1: K-parallel fresh-context re-discovery (SPEC "Fan-Out
            # Redesign", D6), blind except for the committee's seeds. The K reports'
            # cross-call variation is the diversity the decomposition step (pass 1b)
            # settles — measured to buy +36% real coverage vs. a single run (see the
            # coverage gate). All K are persisted as an audit trail.
            delta_queue.put(_Stage(CRITERIA_STAGES["discovering"]))
            _t0 = time.perf_counter()
            fan_out = discover_patterns_fanout(
                provider, applications=pool, settings=settings,
                k=settings.ai.discovery_fan_out, seeds=seeds, on_delta=on_delta,
            )
            durations["Pattern discovery"] = round((time.perf_counter() - _t0) * 1000)
            fan_out_reports = fan_out.reports
            # Persist every discoverer's report AND its own reasoning, built here
            # where the passes are in scope. Each pass = one fresh-context discovery;
            # keeping all K narratives (not just the streamed one) is what lets the
            # Insights panel show each discoverer — and reasoning has proven vital for
            # debugging (see .clinerules).
            fan_out_audit = {
                "k": len(fan_out.passes),  # survivors (the reports decomposition saw)
                "failed_count": fan_out.failed_count,  # workers that timed out/errored
                "passes": [
                    {"report": p.report.model_dump(mode="json"), "narrative": p.narrative}
                    for p in fan_out.passes
                ],
            }
            discovery_cost = fan_out.cost
            # Pass 1b: decomposition — settle the K reports into ONE finest,
            # non-overlapping set (SPEC "Fan-Out Redesign", Phase 3). A single call
            # distils the union to ~one axis per real concept. Its DecompositionReport
            # is projected onto a PoolDimensionReport so the match → adopt → score tail
            # below consumes it unchanged; source_keys + the per-axis merge reasoning
            # are preserved separately in decompose_audit.
            delta_queue.put(_Stage(CRITERIA_STAGES["settling"]))
            # Kept axes are injected HERE (not into discovery): the settling call sees
            # every carving at once, so it folds any re-discovered twin into the kept
            # axis (reusing its key → match adopts it → cached scores carry forward)
            # and keeps it present regardless.
            _t0 = time.perf_counter()
            decomposition, decompose_narrative, decompose_cost = decompose_dimensions(
                provider, reports=fan_out_reports, settings=settings,
                kept=kept_dims, on_delta=on_delta,
            )
            durations["Dimension decomposition"] = round((time.perf_counter() - _t0) * 1000)
            # D9 guard: a committee ask (proposal OR kept axis) must never be silently
            # merged away. Deterministic backstop for the prompt — repairs flag-loss on
            # merge and re-adds any ask decomposition dropped; `folded` lists asks merged
            # INTO another axis, surfaced to the committee (never a silent vanish).
            decomposition, folded_requests = enforce_committee_requests(
                decomposition, fan_out_reports, kept=kept_dims
            )
            # The settled why_it_differentiates is carried forward from each axis's
            # primary source (the discoverer/kept axis that actually read the pool),
            # NOT written by the decomposer (which never sees the pool). See
            # to_pool_report / DecomposedDimension.
            report = to_pool_report(
                decomposition, fan_out_reports, kept=kept_dims
            )
            narrative = decompose_narrative or fan_out.narrative
            # Pass 2: identity-match new dimensions onto ALL prior dimensions (not
            # just the last run) so a re-surfaced concept re-adopts its key rather
            # than minting a new one — keeping the key count converging and reusing
            # cached scores. Skipped on the very first run (no history).
            new_to_old: dict[str, str] = {}
            match_narrative: str | None = None
            match_cost = PassCost()
            if match_history is not None:
                delta_queue.put(_Stage(CRITERIA_STAGES["matching"]))
                _t0 = time.perf_counter()
                new_to_old, match_narrative, match_cost = match_dimensions(
                    provider, old=match_history, new=report, settings=settings,
                    on_delta=on_delta,
                )
                durations["Dimension matching"] = round((time.perf_counter() - _t0) * 1000)
            criteria_outcome["ok"] = _CriteriaWork(
                report=report, narrative=narrative, discovery_cost=discovery_cost,
                new_to_old=new_to_old, match_narrative=match_narrative, match_cost=match_cost,
                fan_out_reports=fan_out_reports, decomposition=decomposition,
                decompose_cost=decompose_cost, folded_requests=folded_requests,
                fan_out_audit=fan_out_audit,
            )
        except Exception as exc:
            criteria_outcome["error"] = exc
        finally:
            delta_queue.put(None)  # signal completion

    worker = threading.Thread(target=run_criteria_passes, daemon=True)
    worker.start()
    # Separate each sub-stage's reasoning with a rule — but not before the first, so
    # the box doesn't open with a stray divider.
    first_stage = True
    while True:
        item = delta_queue.get()
        if item is None:
            break
        if isinstance(item, _Stage):
            if not first_stage:
                yield emit(ThinkingEvent(phase=CRITERIA, text=THINKING_SEPARATOR))
            first_stage = False
            yield emit(StageEvent(phase=CRITERIA, stage=item.name))
        else:
            yield emit(ThinkingEvent(phase=CRITERIA, text=item))
    worker.join()

    if "error" in criteria_outcome:
        exc = criteria_outcome["error"]
        log.warning(
            "Rank criteria phase failed: %s",
            exception_type_name(exc), exc_info=exc,
        )
        yield emit(
            StreamErrorEvent(
                phase=CRITERIA,
                message=f"Finding criteria failed: {type(exc).__name__}: {exc}",
            )
        )
        return None
    work: _CriteriaWork = criteria_outcome["ok"]
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
                    f"{_failed} of {_failed + _survived} discovery workers failed "
                    f"(likely a Bedrock timeout); continued on the {_survived} that "
                    f"succeeded. Criteria may be slightly less diverse — re-rank to retry."
                ),
            )
        )
    # Decompose audit: per settled axis, the source_keys it absorbed + the merge/keep
    # reasoning (the Insights panel surface, and the D9 committee-request trail). Built
    # from the pre-adopt decomposition so it reflects what decomposition actually did,
    # before the match pass rewrites matched keys to prior ones below.
    decompose_audit = decompose_audit_payload(
        work.decomposition, work.fan_out_reports, narrative=work.narrative,
        folded_requests=work.folded_requests,
    )
    # Audit trail for the carry-forward: what discovery ACTUALLY emitted (its own
    # keys, before adopt_matched_keys rewrites matched ones to prior keys) and how
    # the match pass mapped it. Without this the stored report only shows the
    # rewritten result, so we can't tell genuine re-discovery from match over-
    # matching. (Exposed in the admin debug view.)
    match_audit = {
        "raw_discovery_dimensions": [
            {"key": d.key, "name": d.name, "from_committee_request": d.from_committee_request}
            for d in work.report.dimensions
        ],
        "new_to_old": work.new_to_old,
        "match_narrative": work.match_narrative,
        # How many prior dimensions the match pass matched against — now the full
        # cross-run history (all known keys), not just the last run. 0 on the very
        # first run (no history), so the audit viewer can tell a first run — where
        # carry-forward is N/A — from a genuine zero-match re-run.
        "prior_dimension_count": len(match_history.dimensions) if match_history else 0,
        # Prior-key → prior-name (from history), so the audit viewer can show a
        # matched dimension's user-facing prior title next to its key.
        "prior_dimension_names": (
            {d.key: d.name for d in match_history.dimensions} if match_history else {}
        ),
    }
    # For every matched dimension, adopt the prior dimension wholesale (key + text)
    # from match_history — the same history the match pass matched against — so its
    # tier placement AND cached score carry forward, and the displayed text stays
    # the wording that score was computed against.
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
    run = create_run(
        db, report=report, settings=settings, model_id=settings.ai.discovery_model,
        narrative=work.narrative,
        # Tier placements (carried forward above) ARE the kept set — no separate
        # field to thread through; create_run clears the consumed proposals.
        tier_layout=layout, new_dimension_keys=new_dimension_keys,
        match_audit=match_audit,
        fan_out_audit=work.fan_out_audit,
        decompose_audit=decompose_audit,
    )
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
        run=run, report=report, discovery_cost=work.discovery_cost,
        decompose_cost=work.decompose_cost, match_cost=work.match_cost, durations=durations,
    )


def _stream_scoring(
    db: Session, provider: AIProvider, settings: AppSettings, report: PoolDimensionReport
) -> Generator[str, None, tuple[ScoreTally, int]]:
    """Phase 3 — score every eligible candidate against the new dimensions, emitting
    per-candidate progress. Returns the run's scoring tally + the pass's wall-clock (ms)."""
    to_score = applications_to_score(db)
    yield emit(PhaseEvent(phase=SCORES, total=len(to_score)))
    tally = ScoreTally()
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
    db: Session, provider: AIProvider, settings: AppSettings,
    run: RankingRun, report: PoolDimensionReport,
) -> Generator[str, None, tuple[Consolidation, int]]:
    """Phase 3b — consolidate duplicate dimensions (SPEC "Post-score consolidation").
    Now that every dimension is scored, score-vector correlation can nominate duplicates
    the definition-only match pass missed; one LLM call confirms by definition and merges
    genuine duplicates (loser aliased to the older key, which heals the fork on future
    matches too). Runs post-score because it needs the vectors; re-writes the just-created
    run in place (collapse merged keys) and writes the alias rows. Usually a no-op
    (correlation nominates nothing → $0). Returns the consolidation + its wall-clock (ms)."""
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
    canonical_rank, known_defs, known_names = key_history(db)

    consolidate_queue: queue.Queue[str | None] = queue.Queue()
    consolidate_outcome: dict[str, Any] = {}

    def run_consolidate_pass() -> None:
        try:
            consolidate_outcome["ok"] = consolidate_dimensions(
                provider,
                report=report,
                canonical_rank=canonical_rank,
                vectors=load_score_vectors(db),
                definitions=known_defs,
                names=known_names,
                settings=settings,
                on_delta=consolidate_queue.put,
            )
        except Exception as exc:
            consolidate_outcome["error"] = exc
        finally:
            consolidate_queue.put(None)  # signal completion

    worker = threading.Thread(target=run_consolidate_pass, daemon=True)
    worker.start()
    # Criteria always ran first and left text in the box, so consolidation's reasoning
    # needs a leading rule. Emit it lazily — only once real deltas arrive — so a no-op
    # consolidation (correlation nominated nothing → no call) leaves no stray divider.
    first_delta = True
    while True:
        item = consolidate_queue.get()
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
    if "error" in consolidate_outcome:
        exc = consolidate_outcome["error"]
        log.warning(
            "Rank consolidation phase failed: %s",
            exception_type_name(exc), exc_info=exc,
        )
    consolidation = consolidate_outcome.get("ok") or Consolidation(
        merges={}, narrative=None, audit=[], cost=PassCost()
    )
    apply_consolidation(
        db, run,
        merges=consolidation.merges,
        audit=consolidation.audit,
        narrative=consolidation.narrative,
    )
    return consolidation, round((time.perf_counter() - _t0) * 1000)


@router.post("/run")
def rank_run(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
    provider: AIProvider = Depends(get_ai_provider),
) -> StreamingResponse:
    """Run the full ranking chain — find criteria → score → consolidate — streaming NDJSON.
    The combined cost is checked against the cap once before any model call, so an over-cap
    run fails fast with a 402 and spends nothing.

    Stream shape: a ``phase`` line per pass, ``progress`` lines for the
    per-candidate passes, then a final ``summary`` with the combined cost.
    Discovery is one call, so it emits a phase line and its result, no progress.
    """
    settings: AppSettings = get_app_settings(db)
    if not eligible_applications(db):
        raise Problem("no_eligible_applications", detail="No eligible applications to rank.")

    # An unchanged pool needs no re-rank, but one is allowed: discovery is nondeterministic,
    # so re-running deliberately gives the committee a fresh set of criteria. The
    # confirmation card is the gate (it flags that nothing requires a re-run); a member who
    # confirms here has opted in on purpose.
    estimate = _rank_estimate(db, settings)
    try:
        enforce_cap(estimate, settings.ai.spending_cap_usd)
    except SpendingCapExceeded as exc:
        raise Problem(
            "cap_exceeded",
            detail=str(exc),
            cap_usd=settings.ai.spending_cap_usd,
            estimated_usd=float(estimate["estimated_usd"]),
        ) from exc

    def stream() -> Iterator[str]:
        # Phase 1: find criteria (starts a fresh run). A fatal failure emits its own error
        # line and returns None — abort the whole stream, nothing was scored.
        criteria = yield from _stream_criteria(db, provider, settings)
        if criteria is None:
            return
        total_cost = (
            criteria.discovery_cost + criteria.decompose_cost + criteria.match_cost
        ).cost_usd

        # Phase 3: score every eligible candidate against the new dimensions.
        score_tally, scoring_ms = yield from _stream_scoring(
            db, provider, settings, criteria.report
        )
        total_cost += score_tally.cost_usd

        # Phase 3b: consolidate duplicate dimensions (post-score, usually a no-op).
        consolidation, consolidate_ms = yield from _stream_consolidate(
            db, provider, settings, criteria.run, criteria.report
        )
        total_cost += consolidation.cost.cost_usd

        # Persist this run's per-pass cost (the only point the fresh/cached split is
        # known). Each pass hands over its PassCost — discovery is the summed K fan-out
        # calls; match/consolidation are zero-cost no-ops when they made no call this run,
        # still recorded so the pass set always covers RANK_PASS_LABELS. durations carries
        # each pass's wall-clock (Pillar 3); the criteria dict omits matching on a first run.
        durations = {
            **criteria.durations,
            "Dimension scoring": scoring_ms,
            "Dimension consolidation": consolidate_ms,
        }
        record_run_cost(
            db,
            kind="rank",
            passes={
                "Pattern discovery": criteria.discovery_cost,
                "Dimension decomposition": criteria.decompose_cost,
                "Dimension matching": criteria.match_cost,
                "Dimension scoring": score_tally.as_pass_cost(settings.ai.dimension_scoring_model),
                "Dimension consolidation": consolidation.cost,
            },
            durations_ms=durations,
            # The pre-run projection shown at the confirmation card (computed above for the
            # cap check), stored for estimate-vs-actual reconciliation.
            estimated_usd=float(estimate["estimated_usd"]),
        )

        # Snapshot the DB now that the run's (expensive, non-deterministic) output is
        # persisted — this is the only durable record once the live DB moves on, so it is
        # captured automatically rather than left to someone remembering. Best-effort: a
        # backup failure must never fail a completed Rank, so it is logged and swallowed.
        try:
            from app.services.backup import create_from_session

            create_from_session(db, tag="rank")
        except Exception:
            logging.getLogger("app.api").exception(
                "Post-rank DB backup failed (run is saved; backup skipped)"
            )

        yield emit(
            RankSummary(
                dimensions=len(criteria.report.dimensions),
                scored=score_tally.processed,
                failed=score_tally.failed,
                total_cost_usd=round(total_cost, 4),
            )
        )

    return StreamingResponse(stream(), media_type="application/x-ndjson")
