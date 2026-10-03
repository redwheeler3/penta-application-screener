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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.dimension_scoring import applications_to_score, kind_for_dimension
from app.db.models import Application, ApplicationAIResult
from app.domain.ranking import CandidateScores, ScoredDimension
from app.services.ranking.dimensions import current_dimension_report


def candidate_scores(
    db: Session,
    analysis,
    *,
    include_application: Application | None = None,
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
    """
    report = current_dimension_report(analysis)
    if analysis.opening_id is None:
        return []
    applications = applications_to_score(db, analysis.opening_id)
    by_id = {app.id: app for app in applications}
    if include_application is not None:
        by_id.setdefault(include_application.id, include_application)
    if not by_id or not report.dimensions:
        return []

    # Fetch only the newest row per applicant and dimension in one query, with
    # row ID breaking timestamp ties. Keep report order when assembling vectors.
    kinds = [kind_for_dimension(dim.key) for dim in report.dimensions]
    ordered = select(
        ApplicationAIResult.id,
        func.row_number().over(
            partition_by=(ApplicationAIResult.application_id, ApplicationAIResult.kind),
            order_by=(ApplicationAIResult.created_at.desc(), ApplicationAIResult.id.desc()),
        ).label("position"),
    ).where(
        ApplicationAIResult.kind.in_(kinds),
        ApplicationAIResult.application_id.in_(by_id),
    ).subquery()
    rows = db.execute(select(
        ApplicationAIResult.application_id, ApplicationAIResult.kind, ApplicationAIResult.output,
    ).join(ordered, ordered.c.id == ApplicationAIResult.id).where(ordered.c.position == 1))
    latest = {(app_id, kind): output or {} for app_id, kind, output in rows}
    candidates: list[CandidateScores] = []
    scores_by_app: dict[int, list[ScoredDimension]] = {app_id: [] for app_id in by_id}
    for dim in report.dimensions:
        kind = kind_for_dimension(dim.key)
        for app_id in by_id:
            score = latest.get((app_id, kind))
            if score is None:
                continue
            scores_by_app[app_id].append(ScoredDimension(
                dimension_key=dim.key, name=dim.name, score=float(score.get("score", 0.0)),
                confidence=score.get("confidence", "low"), rationale=score.get("rationale", ""),
                evidence=score.get("evidence", ""),
            ))

    for app_id, app in by_id.items():
        scores = scores_by_app[app_id]
        if not scores:
            continue
        candidates.append(
            CandidateScores(
                application_id=app_id, name=app.applicant_name, scores=scores
            )
        )
    return candidates
