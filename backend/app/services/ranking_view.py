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
from sqlalchemy.orm import Session

from app.ai.dimension_scoring import applications_to_score, kind_for_dimension
from app.db.models import ApplicationAIResult
from app.domain.ranking import CandidateScores, ScoredDimension
from app.services.screening_run import current_pattern_report


def candidate_scores(db: Session, run) -> list[CandidateScores]:
    """Every eligible candidate with its per-dimension scores under ``run``,
    joined to dimension labels. A candidate's score for each dimension is read
    from its **per-key** cache row (``dimension_scoring:<dimension_key>``), so
    scores reused from a prior run (matched dimensions share the prior key) are
    picked up transparently. A candidate with no scored dimensions at all is
    skipped (nothing to rank on).
    """
    report = current_pattern_report(run)
    applications = applications_to_score(db)
    by_id = {app.id: app for app in applications}

    # One query per dimension kind, each giving the latest row per candidate. There
    # are ~15-30 dimensions, so this is a handful of small indexed lookups.
    candidates: list[CandidateScores] = []
    scores_by_app: dict[int, list[ScoredDimension]] = {app_id: [] for app_id in by_id}
    for dim in report.dimensions:
        rows = db.scalars(
            select(ApplicationAIResult)
            .where(ApplicationAIResult.kind == kind_for_dimension(dim.key))
            .where(ApplicationAIResult.application_id.in_(list(by_id)))
            .order_by(ApplicationAIResult.created_at)
        )
        latest: dict[int, ApplicationAIResult] = {}
        for row in rows:
            latest[row.application_id] = row  # a re-score supersedes older rows
        for app_id, row in latest.items():
            s = row.output or {}
            scores_by_app[app_id].append(
                ScoredDimension(
                    dimension_key=dim.key,
                    name=dim.name,
                    score=float(s.get("score", 0.0)),
                    confidence=s.get("confidence", "low"),
                    rationale=s.get("rationale", ""),
                    evidence=s.get("evidence", ""),
                )
            )

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
