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

from app.ai.dimension_scoring import applications_to_score, kind_for
from app.db.models import ApplicationAIResult
from app.domain.ranking import CandidateScores, ScoredDimension


def candidate_scores(db: Session, report) -> list[CandidateScores]:
    """Every eligible candidate with its per-dimension scores under the current
    run, joined to dimension labels. Candidates not yet scored under this
    dimension set are skipped (they have nothing to rank on).
    """
    applications = applications_to_score(db)
    by_id = {app.id: app for app in applications}
    labels = {d.key: d.name for d in report.dimensions}

    results = db.scalars(
        select(ApplicationAIResult)
        .where(ApplicationAIResult.kind == kind_for(report))
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
