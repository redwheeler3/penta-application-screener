"""HTTP presentation for one captured analysis and its member-owned ranking state."""

from dataclasses import asdict

from sqlalchemy.orm import Session

from app.db.models import MemberRanking, User, UserRole
from app.domain.ranking import rank_candidates
from app.schemas.applications import DimensionContributionOut
from app.schemas.ranking import (
    CurrentRunResponse,
    PoolDimensionOut,
    RankedCandidateOut,
    RankingResponse,
)
from app.services.applications.shared_shortlist import shortlisted_ids
from app.services.applications.stars import starred_ids
from app.services.eligibility.evaluation import eligible_application_ids_for
from app.services.ranking.dimensions import current_dimension_report
from app.services.ranking.member_state import (
    dimension_weights,
    kept_keys,
    proposed_dimensions,
    requested_flag_keys,
    revived_flag_keys,
)
from app.services.ranking.view import candidate_scores


def run_payload(db: Session, member_ranking: MemberRanking, user: User) -> CurrentRunResponse | None:
    """The captured analysis's discovered pattern report + the signed-in member's view of it,
    shaped for the UI. Dimensions are shared, historical operator reasoning is admin-only,
    and badges, kept axes and proposals come from this member's ranking."""
    analysis = member_ranking.analysis
    report = current_dimension_report(analysis)
    if report is None:
        return None
    return CurrentRunResponse(
        analysis_id=analysis.id,
        dimensions=[
            PoolDimensionOut(
                key=d.key,
                name=d.name,
                definition=d.definition,
                high_end=d.high_end,
                low_end=d.low_end,
                why_it_differentiates=d.why_it_differentiates,
                from_committee_request=d.from_committee_request,
            )
            for d in report.dimensions
        ],
        discovery_narrative=(analysis.audit.discovery_narrative
            if user.role == UserRole.ADMIN and analysis.audit else None),
        # Dimensions absent from the immediately-prior analysis in this member's view —
        # parked/placed but flagged for triage. Empty on a first run.
        new_dimension_keys=(member_ranking.run_state or {}).get("new_dimension_keys", []),
        # Of those flagged keys, the ones seen in an EARLIER analysis (revived), derived
        # from history — the frontend colours these blue vs. amber for genuinely-new.
        revived_dimension_keys=revived_flag_keys(db, member_ranking),
        # Keys a member proposed for this analysis, not yet dismissed by them — "Requested" pill.
        requested_dimension_keys=requested_flag_keys(member_ranking),
        # Kept axes: every dimension in a working (non-Ignore) tier of this member's ranking —
        # guaranteed to survive the next Rank. Derived from tier placement (see kept_keys). Plus
        # any pending free-text proposals (fed to the next Rank, then consumed).
        kept_keys=kept_keys(member_ranking),
        proposed_dimensions=proposed_dimensions(member_ranking),
    )



def ranking_payload(db: Session, member_ranking: MemberRanking, user: User) -> RankingResponse:
    """The ranked-shortlist response for a member's view of an analysis. Shared by
    the board read and the tier-edit endpoint, so a tier change returns the re-sorted list in one
    round-trip. Ranking weights + tiers are this member's; the dimension scores and star state
    are shared, resolved off the analysis / this user.
    """
    weights = dimension_weights(member_ranking)
    # The scored pool is the shared UNION (every applicant eligible for at least one member),
    # so restrict this member's shortlist to the applicants eligible in THEIR own view —
    # another member's eligible-only applicant is scored but must not appear on this board.
    # Pool means/impact still come from the full rankable union (shared math), so a candidate's
    # numbers don't shift with who is filtering; we only drop rows the member excluded.
    if member_ranking.analysis.opening_id is None:
        raise ValueError("A current analysis must belong to an opening.")
    opening_id = member_ranking.analysis.opening_id
    eligible_ids = eligible_application_ids_for(db, user.id, opening_id)
    ranked = [
        c
        for c in rank_candidates(candidate_scores(db, member_ranking.analysis), weights)
        if c.application_id in eligible_ids
    ]
    starred = starred_ids(db, user.id, [c.application_id for c in ranked])
    shortlisted = shortlisted_ids(db, opening_id, [c.application_id for c in ranked])
    return RankingResponse(
        analysis_id=member_ranking.analysis_id,
        weights=weights,
        scored_count=len(ranked),
        candidates=[
            RankedCandidateOut(
                application_id=c.application_id,
                name=c.name,
                rank=c.rank,
                fit=c.fit,
                band=c.band,
                contributions=[
                    DimensionContributionOut(**asdict(contribution))
                    for contribution in c.contributions
                ],
                starred_by_me=c.application_id in starred,
                shortlisted=c.application_id in shortlisted,
            )
            for c in ranked
        ],
        # Recomputed each save so the tier-list refreshes badges in the same
        # round-trip (moving or acknowledging a flagged dimension clears it).
        new_dimension_keys=(member_ranking.run_state or {}).get("new_dimension_keys", []),
        revived_dimension_keys=revived_flag_keys(db, member_ranking),
        requested_dimension_keys=requested_flag_keys(member_ranking),
        # Kept axes (derived from tiers) + pending proposals, so the tier list and
        # composer stay in sync after a tier/seed save.
        kept_keys=kept_keys(member_ranking),
        proposed_dimensions=proposed_dimensions(member_ranking),
    )
