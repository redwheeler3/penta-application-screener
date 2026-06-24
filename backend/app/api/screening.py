"""Screening API: the Rank chain (milestones 6-8) and the deterministic ranked
shortlist (milestone 8).

Flow the UI drives:
  1. GET  /screening/rank/estimate — combined cost projection for the chain.
  2. POST /screening/rank/run — summarize essays → find criteria → score every
     eligible applicant, streaming phase/progress/summary as NDJSON. The cap is
     enforced once over the COMBINED cost before any model call.
  3. GET  /screening/current — the current run's criteria + summary.
  4. GET  /screening/ranking — the ranked shortlist (math over cached scores).
  5. PUT  /screening/shortlist-line — move the shortlist line.

The committee never runs the three sub-passes individually, so they are exposed
as the single Rank step; the passes stay separate underneath (distinct schemas,
cache kinds, and status behavior).
"""

import json
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.analysis import ScreeningResult, SpendingCapExceeded, enforce_cap
from app.ai.dimension_scoring import (
    applications_to_score,
    estimate_scoring_without_dimensions,
    kind_for,
    screen_dimension_scores,
)
from app.ai.essay_analysis import (
    applications_to_analyze,
    estimate_essay_analysis,
    screen_essays,
)
from app.ai.pattern_discovery import (
    discover_patterns,
    eligible_applications,
    estimate_discovery,
)
from app.ai.provider import AIProvider
from app.api.dependencies import get_ai_provider, require_current_user
from app.db.models import ApplicationAIResult, User
from app.db.session import get_db
from app.domain.ranking import (
    CandidateScores,
    ScoredDimension,
    rank_candidates,
)
from app.schemas.settings import AppSettings
from app.services.screening_run import (
    create_run,
    current_pattern_report,
    dimension_weights,
    get_current_run,
    set_shortlist_size,
    shortlist_size,
)
from app.services.settings import get_app_settings

router = APIRouter(prefix="/screening", tags=["screening"])


@dataclass
class RunTally:
    """Running totals for a scoring run, emitted as the final summary line."""

    analyzed: int = 0
    cached: int = 0
    failed: int = 0
    cost_usd: float = 0.0

    def add(self, result: ScreeningResult) -> None:
        if result.failed:
            self.failed += 1
            return
        if result.outcome.cached:
            self.cached += 1
        else:
            self.analyzed += 1
        self.cost_usd += result.outcome.cost_usd


def _run_payload(db: Session) -> dict[str, Any] | None:
    """The current run's discovered pattern report, shaped for the UI."""
    run = get_current_run(db)
    if run is None:
        return None
    report = current_pattern_report(run)
    if report is None:
        return None
    return {
        "runId": run.id,
        "name": run.name,
        "status": run.status,
        "summary": report.summary,
        "dimensions": report.model_dump(mode="json")["dimensions"],
    }


@router.get("/current")
def current(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any] | None:
    """The current screening run's dimensions, or null if none discovered yet."""
    return _run_payload(db)


# --- Rank: the combined essays → criteria → scores chain --------------------
#
# The committee never runs the three sub-passes individually, so the UI exposes
# them as one "Rank" button. The passes stay separate underneath (distinct
# schemas, cache kinds, and status behavior — essay summary and scoring never
# touch status, discovery starts a fresh run); this layer just orchestrates them
# back-to-back. The spending cap is enforced once, over the COMBINED projected
# cost, before any model call — so the single button keeps the same hard cost
# gate as the individual passes had.


def _rank_estimate(db: Session, settings: AppSettings) -> dict[str, Any]:
    """Combined projected cost of the three Rank passes.

    Essay summary is netted against its cache (re-running is cheap if essays were
    already summarized). Discovery always re-runs (uncached) and scoring is
    priced for the whole eligible pool, because Rank discovers a fresh dimension
    set every time — so no prior scores are cache hits under it. The total is
    therefore an upper-ish bound; the confirmation labels it approximate.
    """
    essays = estimate_essay_analysis(db, settings)
    pool = eligible_applications(db)
    discovery_usd = estimate_discovery(pool, settings)
    scoring_usd = estimate_scoring_without_dimensions(db, settings)
    total = round(float(essays["estimated_usd"]) + discovery_usd + scoring_usd, 4)
    return {
        "eligible": len(pool),
        "breakdown": {
            "essays_usd": round(float(essays["estimated_usd"]), 4),
            "criteria_usd": round(discovery_usd, 4),
            "scoring_usd": round(scoring_usd, 4),
        },
        "essays_cached": essays["cached"],
        "estimated_usd": total,
        "approximate": True,  # criteria/scoring scale with essay output not yet produced
    }


@router.get("/rank/estimate")
def rank_estimate(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    settings: AppSettings = get_app_settings(db)
    if not eligible_applications(db):
        raise HTTPException(status_code=409, detail="No eligible applications to rank.")
    result = _rank_estimate(db, settings)
    result["cap_usd"] = settings.ai.spending_cap_usd
    result["within_cap"] = result["estimated_usd"] <= settings.ai.spending_cap_usd
    return result


@router.post("/rank/run")
def rank_run(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
    provider: AIProvider = Depends(get_ai_provider),
) -> StreamingResponse:
    """Run the full ranking chain — summarize essays → find criteria → score —
    streaming NDJSON. The combined cost is checked against the cap once, before
    any model call, so an over-cap run fails fast with a 402 and spends nothing.

    Stream shape: a ``phase`` line announces each pass (essays / criteria /
    scores), then ``progress`` lines for the per-candidate passes, then a final
    ``summary`` with the combined cost. Discovery is one call, so it emits a
    phase line and its standalone result, no progress fraction.
    """
    settings: AppSettings = get_app_settings(db)
    if not eligible_applications(db):
        raise HTTPException(status_code=409, detail="No eligible applications to rank.")

    estimate = _rank_estimate(db, settings)
    try:
        enforce_cap(estimate, settings.ai.spending_cap_usd)
    except SpendingCapExceeded as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc

    def stream() -> Iterator[str]:
        total_cost = 0.0

        # Phase 1: summarize essays (informational; never touches status).
        essays = applications_to_analyze(db)
        yield json.dumps({"type": "phase", "phase": "essays", "total": len(essays)}) + "\n"
        essay_tally = RunTally()
        for processed, result in enumerate(
            screen_essays(
                db, provider, applications=essays, settings=settings,
                max_workers=settings.ai.max_workers,
            ),
            start=1,
        ):
            essay_tally.add(result)
            yield json.dumps(
                {"type": "progress", "phase": "essays", "processed": processed, "total": len(essays)}
            ) + "\n"
        total_cost += essay_tally.cost_usd

        # Phase 2: find criteria (one synthesis call; starts a fresh run).
        yield json.dumps({"type": "phase", "phase": "criteria"}) + "\n"
        pool = eligible_applications(db)
        try:
            report, narrative, discovery_cost = discover_patterns(
                db, provider, applications=pool, settings=settings
            )
        except Exception as exc:  # noqa: BLE001 — surface provider failure to the client
            yield json.dumps(
                {"type": "error", "phase": "criteria",
                 "message": f"Finding criteria failed: {type(exc).__name__}: {exc}"}
            ) + "\n"
            return
        create_run(
            db, report=report, model_id=settings.ai.synthesis_model,
            narrative=narrative, cost_usd=discovery_cost,
        )
        total_cost += discovery_cost
        yield json.dumps(
            {"type": "criteria_done", "dimensions": len(report.dimensions)}
        ) + "\n"

        # Phase 3: score every eligible candidate against the new dimensions.
        to_score = applications_to_score(db)
        yield json.dumps({"type": "phase", "phase": "scores", "total": len(to_score)}) + "\n"
        score_tally = RunTally()
        for processed, result in enumerate(
            screen_dimension_scores(
                db, provider, applications=to_score, report=report,
                settings=settings, max_workers=settings.ai.max_workers,
            ),
            start=1,
        ):
            score_tally.add(result)
            yield json.dumps(
                {"type": "progress", "phase": "scores", "processed": processed, "total": len(to_score)}
            ) + "\n"
        total_cost += score_tally.cost_usd

        yield json.dumps(
            {
                "type": "summary",
                "dimensions": len(report.dimensions),
                "scored": score_tally.analyzed + score_tally.cached,
                "failed": essay_tally.failed + score_tally.failed,
                "totalCostUsd": round(total_cost, 4),
            }
        ) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


# --- Ranking (milestone 8) --------------------------------------------------
#
# The ranked shortlist is deterministic math over the cached dimension scores —
# no model call. This layer loads each eligible candidate's scores for the
# current run, joins the dimension labels, and hands flat values to the pure
# ``rank_candidates`` domain function. The run's equal-weight baseline lives in
# ``criteria.weights``; M9 will mutate it, and re-ranking is just a re-fetch.


def _candidate_scores(db: Session, report) -> list[CandidateScores]:
    """Build the ranker's input: every eligible candidate with its per-dimension
    scores under the current run, joined to dimension labels. Candidates not yet
    scored under this dimension set are skipped (they have nothing to rank on).
    """
    applications = applications_to_score(db)
    by_id = {app.id: app for app in applications}
    labels = {d.key: d.name for d in report.dimensions}

    kind = kind_for(report)
    results = db.scalars(
        select(ApplicationAIResult)
        .where(ApplicationAIResult.kind == kind)
        .where(ApplicationAIResult.application_id.in_(list(by_id)))
        .order_by(ApplicationAIResult.created_at)
    )
    latest: dict[int, ApplicationAIResult] = {}
    for result in results:
        latest[result.application_id] = result  # a re-run supersedes older rows

    candidates: list[CandidateScores] = []
    for app_id, app in by_id.items():
        result = latest.get(app_id)
        if result is None:
            continue
        scores = [
            ScoredDimension(
                dimension_key=s.get("dimension_key"),
                name=labels.get(s.get("dimension_key"), s.get("dimension_key")),
                score=float(s.get("score", 0.0)),
                confidence=s.get("confidence", "low"),
                rationale=s.get("rationale", ""),
                evidence=s.get("evidence", ""),
            )
            for s in (result.output or {}).get("scores", [])
        ]
        candidates.append(
            CandidateScores(
                application_id=app_id,
                name=app.applicant_name,
                scores=scores,
            )
        )
    return candidates


@router.get("/ranking")
def ranking(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The deterministic ranked shortlist for the current run.

    Ranks every scored eligible candidate by the weight-normalized average of its
    dimension scores, labels each by relative pool position, and marks those above
    the shortlist line. No model call — pure math over cached scores.
    """
    run = get_current_run(db)
    report = current_pattern_report(run) if run is not None else None
    if report is None:
        raise HTTPException(status_code=409, detail="Discover patterns before ranking.")

    weights = dimension_weights(run)
    line = shortlist_size(run)
    ranked = rank_candidates(_candidate_scores(db, report), weights, line)
    return {
        "runId": run.id,
        "weights": weights,
        "shortlistSize": line,
        "aboveLineCount": sum(1 for c in ranked if c.above_line),
        "scoredCount": len(ranked),
        "candidates": [asdict(c) for c in ranked],
    }


class ShortlistLineUpdate(BaseModel):
    shortlist_size: int = Field(ge=0)


@router.put("/shortlist-line")
def update_shortlist_line(
    body: ShortlistLineUpdate,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Move the shortlist line for the current run. The line is a reading aid —
    it never removes anyone — so any non-negative position is valid.
    """
    run = get_current_run(db)
    if run is None:
        raise HTTPException(status_code=409, detail="Discover patterns before ranking.")
    set_shortlist_size(db, run, body.shortlist_size)
    return {"shortlistSize": shortlist_size(run)}
