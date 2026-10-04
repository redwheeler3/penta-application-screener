"""Assemble the ranker's input from stored dimension scores.

This is the one place that turns persisted ``dimension_scoring`` results into the
pure ``ranking`` domain's ``CandidateScores`` — shared by the screening router
(the ranked shortlist) and the applications router (a candidate's detail page),
so both views compute fit, impact, and pool means from the identical pipeline and
can never drift. It lives in services (not a router) precisely so both routers can
depend on it one-way.

It deliberately does no math itself: ``rank_candidates`` does. Keeping assembly
here and arithmetic in the domain keeps the formula (``impact = weight ·
(score − pool_mean)``) in exactly one place.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.ai.dimension_scoring import applications_to_score, kind_for_dimension
from app.ai.schemas import PoolDimensionReport
from app.db.models import Application, ApplicationAIResult, ApplicationAISelection
from app.domain.ranking import CandidateScores, ScoredDimension
from app.services.ranking.dimensions import current_dimension_report


def selected_application_scores(db: Session, application_id: int, report: PoolDimensionReport) -> list[ApplicationAIResult]:
    """Selected score and provenance rows for one applicant, excluding unused narratives."""
    return list(db.scalars(select(ApplicationAIResult).options(load_only(
        ApplicationAIResult.kind, ApplicationAIResult.output, ApplicationAIResult.model_id,
        ApplicationAIResult.reasoning_effort, ApplicationAIResult.prompt_version,
        ApplicationAIResult.input_tokens, ApplicationAIResult.output_tokens, ApplicationAIResult.cost_usd,
    )).join(ApplicationAISelection, ApplicationAISelection.result_id == ApplicationAIResult.id).where(
        ApplicationAISelection.application_id == application_id,
        ApplicationAISelection.kind.in_([kind_for_dimension(dim.key) for dim in report.dimensions]),
    )))


def scored_dimensions(report: PoolDimensionReport, outputs: dict[str, dict]) -> list[ScoredDimension]:
    return [ScoredDimension(
        dimension_key=dim.key, name=dim.name, score=float(score.get("score", 0.0)),
        confidence=score.get("confidence", "low"), rationale=score.get("rationale", ""), evidence=score.get("evidence", ""),
    ) for dim in report.dimensions if (score := outputs.get(kind_for_dimension(dim.key))) is not None]


def candidate_scores(
    db: Session,
    analysis,
    *,
    include_application: Application | None = None,
    report: PoolDimensionReport | None = None,
    captured_candidate: CandidateScores | None = None,
) -> list[CandidateScores]:
    """Every eligible candidate with its per-dimension scores under ``analysis``,
    joined to dimension labels. A candidate's score for each dimension is read
    from its **per-key** cache row (``dimension_scoring:<dimension_key>``), so
    scores reused from a prior analysis (matched dimensions share the prior key) are
    picked up transparently. A candidate with no scored dimensions at all is
    skipped (nothing to rank on). Shared across members — scores don't depend on tiers.

    ``include_application`` adds one historical candidate to the assembled score set
    without changing the active ranking pool. The applicant detail view uses this for a
    selected household, whose persisted scores remain reviewable after selection removes
    the household from future AI work.
    A detail request can supply its captured candidate scores and report; that
    applicant is excluded from a second score read so provenance and values agree.
    """
    report = report if report is not None else current_dimension_report(analysis)
    if analysis.opening_id is None or report is None:
        return []
    applications = applications_to_score(db, analysis.opening_id)
    by_id = {app.id: app for app in applications}
    if include_application is not None:
        by_id.setdefault(include_application.id, include_application)
    if not by_id or not report.dimensions:
        return []

    # Fetch selected results in one query. The consumer can differ from the original
    # producer of a content-addressed cache row. Keep report order in assembled vectors.
    kinds = [kind_for_dimension(dim.key) for dim in report.dimensions]
    ids = set(by_id) - ({captured_candidate.application_id} if captured_candidate is not None else set())
    rows = db.execute(select(
        ApplicationAISelection.application_id, ApplicationAISelection.kind, ApplicationAIResult.output,
    ).join(ApplicationAISelection, ApplicationAISelection.result_id == ApplicationAIResult.id).where(
        ApplicationAISelection.application_id.in_(ids), ApplicationAISelection.kind.in_(kinds)))
    outputs_by_app: dict[int, dict[str, dict]] = {app_id: {} for app_id in by_id}
    for app_id, kind, output in rows:
        outputs_by_app[app_id][kind] = output or {}
    candidates: list[CandidateScores] = []
    for app_id, app in by_id.items():
        scores = (captured_candidate.scores if captured_candidate is not None and captured_candidate.application_id == app_id
                  else scored_dimensions(report, outputs_by_app[app_id]))
        if not scores:
            continue
        candidates.append(
            CandidateScores(
                application_id=app_id, name=app.applicant_name, scores=scores
            )
        )
    return candidates
