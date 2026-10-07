"""Known spending from recorded AI attempts, grouped by workflow and pass.

Completed and failed attempts share the RunCostLedger/RunPassCost shape. Returned
usage is priced; billing without returned usage is not inferred. ApplicationAIResult
is a reuse cache and cannot reconstruct a run's spend or cache choices after the fact.
The spending cap checks the pre-run estimate; cumulative known spending has no ceiling.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from threading import Lock
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.model_catalog import known_model_spec
from app.ai.pricing import MeasuredProvider, PassCost, cost_usd
from app.ai.provider import Usage
from app.core.time import utc_isoformat
from app.db.models import RunCostLedger, RunPassCost
from app.schemas.observability import (
    CostGroup,
    CostPass,
    CostReport,
    LastRunCost,
    LastRunPass,
    LastRunsReport,
)

# The canonical pass labels per user-facing run, and the SINGLE SOURCE OF TRUTH for
# "which passes exist." Each run mode records its own full set (a pass that made no call
# still records a zero row), so both surfaces cover that mode's passes by construction
# and can't drift. Add a pass here first, then have its mode record a RunPassCost for it.
RANK_PASS_LABELS = [
    "Pattern discovery",
    "Dimension decomposition",
    "Dimension matching",
    "Dimension scoring",
    "Dimension consolidation",
]
SCREEN_PASS_LABELS = ["Screening"]
SCORE_CURRENT_PASS_LABELS = ["Dimension scoring"]

FULL_RANK_KIND = "rank"
SCORE_CURRENT_KIND = "rank_scores"

# Passes that can reuse cached results. The others (discovery, decomposition, matching,
# consolidation) do not reuse results, so a "saved by cache" figure is N/A — the UI
# shows "—", never $0, so structural absence of caching doesn't read as failure.
CACHEABLE_PASSES = {"Screening", "Dimension scoring"}
RUN_COST_RECORDER_KEY = "run_cost_recorder"
log = logging.getLogger(__name__)


@dataclass
class RunCostRecorder:
    """Keep already-returned spending when HTTP cleanup stops an unfinished run.

    Workers register in-memory meters only. Cleanup writes expense facts in its
    own short session after result fencing and lease release; no cancelled result
    is published and no provider is awaited for additional usage.
    """

    kind: str
    estimated_usd: float
    triggered_by_user_id: int
    opening_id: int | None
    recorded: bool = False
    _meters: dict[str, MeasuredProvider] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def observe(self, label: str, meter: MeasuredProvider) -> None:
        with self._lock:
            self._meters[label] = meter

    def record_interrupted(self, bind) -> None:
        if self.recorded:
            return
        with self._lock:
            meters = dict(self._meters)
        labels = {"screen": SCREEN_PASS_LABELS, FULL_RANK_KIND: RANK_PASS_LABELS,
            SCORE_CURRENT_KIND: SCORE_CURRENT_PASS_LABELS}[self.kind]
        passes = {label: meters[label].snapshot() if label in meters else PassCost() for label in labels}
        if not any(cost.calls or cost.failed_calls for cost in passes.values()):
            return
        try:
            with Session(bind=bind) as receipt:
                record_run_cost(receipt, kind=self.kind, status="failed", failed_pass="Interrupted",
                    failure_type="WorkInterrupted", passes=passes, estimated_usd=self.estimated_usd,
                    triggered_by_user_id=self.triggered_by_user_id, opening_id=self.opening_id)
            self.recorded = True
        except Exception as error:
            log.warning("Interrupted run expense recording failed: %s", type(error).__name__)


def opening_label(run: RunCostLedger) -> str | None:
    if run.opening is None:
        return None
    move_in = run.opening.move_in_date.strftime("%b %d, %Y").replace(" 0", " ")
    return f"{run.opening.unit_size_bedrooms}BR · {move_in}"


# --- Recording (both Screen and Rank write here) ----------------------------------


def record_run_cost(
    db: Session,
    *,
    kind: str,
    passes: dict[str, PassCost],
    durations_ms: dict[str, int] | None = None,
    estimated_usd: float = 0.0,
    triggered_by_user_id: int | None = None,
    opening_id: int | None = None,
    dimension_count: int | None = None,
    status: Literal["completed", "failed"] = "completed",
    failed_pass: str | None = None,
    failure_type: str | None = None,
) -> None:
    """Persist a recorded attempt's known per-pass cost (``kind`` = "screen" | "rank" |
    "rank_scores"), one
    ``RunPassCost`` row per pass, under a header row. Called as the run's stream finishes
    — the only point the fresh/cached split is known. ``passes`` maps each canonical pass
    label to its ``PassCost`` (a pass that made no call still passes a zero cost, so the
    row set always covers the canonical labels). ``durations_ms`` maps a label to the
    pass's wall-clock (measured by the caller, not summed from PassCost — see the model
    docstring); a label absent from it records 0. ``estimated_usd`` is the pre-run cost
    projection the caller showed the committee, stored for estimate-vs-actual
    reconciliation (0.0 when the kind has no pre-run estimate surface).
    ``triggered_by_user_id`` stamps the member who kicked off this shared run, so
    Observability can attribute the shared spend; None leaves it unattributed.
    Commits its own rows so a later failure can't lose them.
    """
    durations_ms = durations_ms or {}
    header = RunCostLedger(
        kind=kind,
        status=status, failed_pass=failed_pass, failure_type=failure_type,
        dimension_count=dimension_count,
        estimated_usd=round(estimated_usd, 6),
        triggered_by_user_id=triggered_by_user_id,
        opening_id=opening_id,
        passes=[
            RunPassCost(
                label=label,
                model_id=cost.model_id,
                calls=cost.calls,
                fresh_units=cost.fresh_units,
                input_tokens=cost.input_tokens,
                output_tokens=cost.output_tokens,
                cost_usd=round(cost.cost_usd, 6),
                cached_count=cost.cached_count,
                cached_saved_usd=round(cost.cached_saved_usd, 6),
                duration_ms=durations_ms.get(label, 0),
                failed_calls=cost.failed_calls,
            )
            for label, cost in passes.items()
        ],
    )
    db.add(header)
    db.commit()
    recorder = db.info.get(RUN_COST_RECORDER_KEY)
    if recorder is not None:
        recorder.recorded = True


# --- Cumulative report (all-time spend, grouped by triggering run) ----------------


def _cost_pass(label: str, rows: list[RunPassCost]) -> CostPass:
    """Fold every recorded row for one pass label into its cumulative CostPass."""
    return CostPass(
        pass_label=label,
        provider_calls=sum(r.calls for r in rows),
        fresh_units=(sum(r.fresh_units for r in rows)
                     if all(r.fresh_units is not None for r in rows) else None),
        input_tokens=sum(r.input_tokens for r in rows),
        output_tokens=sum(r.output_tokens for r in rows),
        cost_usd=round(sum(r.cost_usd for r in rows), 6),
        cacheable=label in CACHEABLE_PASSES,
        cached_count=sum(r.cached_count for r in rows),
        cached_saved_usd=round(sum(r.cached_saved_usd for r in rows), 6),
    )


def _group(run_label: str, passes: list[CostPass]) -> CostGroup:
    return CostGroup(
        run_label=run_label,
        passes=passes,
        subtotal_usd=round(sum(p.cost_usd for p in passes), 6),
        subtotal_saved_usd=round(sum(p.cached_saved_usd for p in passes), 6),
    )


def cost_report(db: Session) -> CostReport:
    """Cumulative AI spend across all runs, grouped by the run that triggers each pass.
    A plain sum over every recorded ``RunPassCost`` — spend, tokens, and cache savings
    all exact.

    Screen runs the screening pass; full Ranks run pattern discovery → dimension
    decomposition → dimension matching → dimension scoring → dimension consolidation;
    score-current updates run dimension scoring only.
    """
    by_kind_and_label: dict[tuple[str, str], list[RunPassCost]] = {}
    for kind, row in db.execute(
        select(RunCostLedger.kind, RunPassCost).join(RunPassCost, RunPassCost.run_id == RunCostLedger.id)
    ):
        by_kind_and_label.setdefault((kind, row.label), []).append(row)

    def passes_for(kind: str, labels: list[str]) -> list[CostPass]:
        return [_cost_pass(label, by_kind_and_label.get((kind, label), [])) for label in labels]

    groups = [
        _group("Screen", passes_for("screen", SCREEN_PASS_LABELS)),
        _group("Discover criteria & rank", passes_for(FULL_RANK_KIND, RANK_PASS_LABELS)),
        _group("Score current criteria", passes_for(SCORE_CURRENT_KIND, SCORE_CURRENT_PASS_LABELS)),
    ]
    return CostReport(
        groups=groups,
        total_cost_usd=round(sum(g.subtotal_usd for g in groups), 6),
        total_saved_usd=round(sum(g.subtotal_saved_usd for g in groups), 6),
    )


# --- Last-run report (most recent Screen / Rank, fresh vs. cached) ----------------


def _last_run(db: Session, kind: str) -> LastRunCost | None:
    row = db.scalar(
        select(RunCostLedger)
        .where(RunCostLedger.kind == kind)
        .order_by(RunCostLedger.id.desc())
        .limit(1)
    )
    if row is None:
        return None
    passes = [
        LastRunPass(
            label=p.label,
            fresh_usd=round(p.cost_usd, 6),
            provider_calls=p.calls,
            fresh_units=p.fresh_units,
            input_tokens=p.input_tokens,
            output_tokens=p.output_tokens,
            cached_count=p.cached_count,
            cached_saved_usd=round(p.cached_saved_usd, 6),
            cacheable=p.label in CACHEABLE_PASSES,
        )
        for p in row.passes
    ]
    return LastRunCost(
        kind=row.kind,
        status=row.status, failed_pass=row.failed_pass, failure_type=row.failure_type,
        at=utc_isoformat(row.created_at),
        fresh_usd=round(sum(p.fresh_usd for p in passes), 6),
        cached_saved_usd=round(sum(p.cached_saved_usd for p in passes), 6),
        estimated_usd=round(row.estimated_usd, 6),
        # Attribution only; omit the stamp when the member relationship is unavailable.
        triggered_by=row.triggered_by.email if row.triggered_by else None,
        opening=opening_label(row),
        passes=passes,
    )


def last_runs_report(db: Session) -> LastRunsReport:
    """The most recent recorded Screen, full Rank, and score-current attempt, each with fresh
    spend and cache savings. A run is null if that type has not been recorded since
    ledgering began."""
    return LastRunsReport(
        screen=_last_run(db, "screen"),
        rank=_last_run(db, FULL_RANK_KIND),
        rank_scores=_last_run(db, SCORE_CURRENT_KIND),
    )


# How many recent Rank runs to average when predicting a re-run's fresh scoring cost.
_SCORING_HISTORY_WINDOW = 5


def recent_pass_fresh_usd(
    db: Session, opening_id: int, pass_label: str = "Dimension scoring", *,
    model_id: str, provider_calls: int | None = None,
) -> float | None:
    """Reprice recent compatible usage, weighted toward this opening's newest runs.

    Discovery normalizes usage per returned provider reply and multiplies by the
    requested fan-out. Other passes retain their measured workload and cache mix.
    Unknown or incompatible models and skipped passes provide no usage evidence;
    callers use their existing seed/cache-aware fallback when none remains.

    This remains approximate: the ledger does not establish prompt/reasoning changes
    or pool growth. Never invent those facts by associating runs and analyses by time.
    """
    rows = list(
        db.scalars(
            select(RunPassCost)
            .join(RunCostLedger, RunPassCost.run_id == RunCostLedger.id)
            .where(
                RunCostLedger.kind == FULL_RANK_KIND,
                RunCostLedger.status == "completed",
                RunCostLedger.opening_id == opening_id,
                RunPassCost.label == pass_label,
            )
            .order_by(RunCostLedger.id.desc())
            .limit(_SCORING_HISTORY_WINDOW)
        )
    )
    # rows are newest→oldest (one per recent Rank, since each run records one row per pass).
    current = known_model_spec(model_id)
    fresh = []
    for row in rows:
        observed = known_model_spec(row.model_id)
        # Tokens transfer only between certified routes for the same model.
        # The ledger has no analysis FK: do not infer prompt/reasoning provenance
        # from an adjacent analysis or reuse dollars from an unknown model.
        if current is None or observed is None or current.model_identity != observed.model_identity:
            continue
        if row.calls == 0 and provider_calls is not None:
            continue
        projected = cost_usd(model_id, Usage(input_tokens=row.input_tokens, output_tokens=row.output_tokens))
        if provider_calls is not None:
            projected *= provider_calls / row.calls
        fresh.append(projected)
    if not fresh:
        return None
    # Linear recency weights: newest gets the largest weight (len), oldest gets 1.
    weights = list(range(len(fresh), 0, -1))
    weighted = sum(f * w for f, w in zip(fresh, weights, strict=True))
    return weighted / sum(weights)
