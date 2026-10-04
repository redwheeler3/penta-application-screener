"""Compute criteria passes and their audits without writing database state."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.ai.dimension_decomposition import (
    decompose_audit_payload,
    decompose_dimensions,
    enforce_committee_requests,
    to_pool_report,
)
from app.ai.dimension_discovery import (
    DiscoverySeeds,
    FanOutDiscovery,
    discover_patterns_fanout,
)
from app.ai.dimension_matching import match_dimensions
from app.ai.pricing import MeasuredProvider, PassCost
from app.ai.provider import AIProvider
from app.ai.schemas import PoolDimension, PoolDimensionReport
from app.core.work_cancellation import WorkCancelled
from app.db.models import Application
from app.schemas.events import CriteriaStage
from app.schemas.settings import AppSettings


@dataclass(frozen=True)
class CriteriaStageChange:
    """Distinguish a stage transition from a reasoning-text delta in the worker queue."""

    name: CriteriaStage


@dataclass(frozen=True)
class CriteriaPassResult:
    report: PoolDimensionReport
    narrative: str | None
    new_to_old: dict[str, str]
    discovery_cost: PassCost
    decompose_cost: PassCost
    match_cost: PassCost
    durations: dict[str, int]
    fan_out_audit: dict[str, Any]
    decompose_audit: dict[str, Any]
    match_audit: dict[str, Any]


class CriteriaFailure(Exception):
    """The original failure plus known spend and durations up to the failed stage."""

    def __init__(self, cause: Exception, failed_pass: str, costs: dict[str, PassCost], durations: dict[str, int]):
        self.cause, self.failed_pass, self.costs, self.durations = cause, failed_pass, costs, durations
        super().__init__(str(cause))


def discovery_audit(fan_out: FanOutDiscovery) -> dict[str, Any]:
    """Retain every surviving discoverer's report and its own reasoning."""
    return {
        "k": len(fan_out.passes),
        "failed_count": fan_out.failed_count,
        "passes": [
            {"report": item.report.model_dump(mode="json"), "narrative": item.narrative}
            for item in fan_out.passes
        ],
    }


def matching_audit(
    report: PoolDimensionReport,
    new_to_old: dict[str, str],
    narrative: str | None,
    history: PoolDimensionReport | None,
) -> dict[str, Any]:
    """Capture dimensions before key adoption so carry-forward remains explainable."""
    return {
        "raw_discovery_dimensions": [
            {"key": d.key, "name": d.name, "from_committee_request": d.from_committee_request}
            for d in report.dimensions
        ],
        "new_to_old": new_to_old,
        "match_narrative": narrative,
        "prior_dimension_count": len(history.dimensions) if history else 0,
        "prior_dimension_names": {d.key: d.name for d in history.dimensions} if history else {},
    }


def run_criteria_passes(
    provider: AIProvider,
    *,
    applications: list[Application],
    settings: AppSettings,
    seeds: DiscoverySeeds,
    kept: list[PoolDimension],
    match_history: PoolDimensionReport | None,
    on_delta: Callable[[str | CriteriaStageChange], None],
) -> CriteriaPassResult:
    """Discover independently, settle the reports, then match onto shared history.

    Proposals seed one discoverer; kept axes enter decomposition so discovery stays
    diverse. All audits describe the model output before persisted keys are adopted.
    """
    durations: dict[str, int] = {}
    meters = {label: MeasuredProvider(provider, label=label) for label in (
        "Pattern discovery", "Dimension decomposition", "Dimension matching")}
    failed_pass = "Pattern discovery"
    started = time.perf_counter()
    try:
        on_delta(CriteriaStageChange("discovering"))
        started = time.perf_counter()
        fan_out = discover_patterns_fanout(
            meters[failed_pass], applications=applications, settings=settings,
            k=settings.ai.discovery_fan_out, seeds=seeds, on_delta=on_delta,
        )
        durations["Pattern discovery"] = round((time.perf_counter() - started) * 1000)
        reports = fan_out.reports

        failed_pass = "Dimension decomposition"
        on_delta(CriteriaStageChange("settling"))
        started = time.perf_counter()
        decomposition, decompose_narrative, decompose_cost = decompose_dimensions(
            meters[failed_pass], reports=reports, settings=settings, kept=kept, on_delta=on_delta,
        )
        durations["Dimension decomposition"] = round((time.perf_counter() - started) * 1000)
        # Committee requests cannot silently disappear through a merge or omission.
        decomposition, folded_requests = enforce_committee_requests(decomposition, reports, kept=kept)
        # Pool-grounded explanations come from discoverers; decomposition never sees the pool.
        report = to_pool_report(decomposition, reports, kept=kept)
        narrative = decompose_narrative or fan_out.narrative

        new_to_old: dict[str, str] = {}
        match_narrative: str | None = None
        match_cost = PassCost()
        if match_history is not None:
            failed_pass = "Dimension matching"
            on_delta(CriteriaStageChange("matching"))
            started = time.perf_counter()
            new_to_old, match_narrative, match_cost = match_dimensions(
                meters[failed_pass], old=match_history, new=report, settings=settings, on_delta=on_delta,
            )
            durations["Dimension matching"] = round((time.perf_counter() - started) * 1000)

    except WorkCancelled:
        raise
    except Exception as error:
        durations[failed_pass] = round((time.perf_counter() - started) * 1000)
        raise CriteriaFailure(error, failed_pass, {label: meter.snapshot() for label, meter in meters.items()}, durations) from error

    return CriteriaPassResult(
        report=report, narrative=narrative, new_to_old=new_to_old,
        discovery_cost=fan_out.cost, decompose_cost=decompose_cost, match_cost=match_cost,
        durations=durations,
        fan_out_audit=discovery_audit(fan_out),
        decompose_audit=decompose_audit_payload(
            decomposition, reports, narrative=narrative, folded_requests=folded_requests,
        ),
        match_audit=matching_audit(report, new_to_old, match_narrative, match_history),
    )
