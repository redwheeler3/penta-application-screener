from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

# Scope + cache-key helpers reused from the passes themselves, so "coverage" counts
# exactly what a re-run would process (never a parallel definition that could drift).
from app.ai.analysis import cache_key
from app.ai.dimension_scoring import (
    PROMPT_VERSION as SCORING_PROMPT_VERSION,
)
from app.ai.dimension_scoring import applications_to_score
from app.ai.screening import applications_for_screening as screening_scope
from app.ai.screening import screening_prompt_version
from app.api.dependencies import require_current_user
from app.db.models import (
    Analysis,
    Application,
    ApplicationAIResult,
    ApplicationStatus,
    StatusSource,
    SyncRun,
    User,
)
from app.db.session import get_db
from app.domain.status import effective_status
from app.schemas.dashboard import (
    CoverageEntry,
    DashboardCounts,
    DashboardResponse,
    WorkflowState,
)
from app.services.analysis import (
    current_dimension_kinds,
    get_current_analysis,
    ranking_is_current,
)
from app.services.application_import import settings_fingerprint
from app.services.eligibility import machine_flags_by_app, overrides_by_app
from app.services.settings import get_app_settings

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
def read_dashboard(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> DashboardResponse:
    settings = get_app_settings(db)
    total = db.scalar(select(func.count()).select_from(Application)) or 0

    # Counts are this member's effective view: their overrides applied over the shared
    # machine verdict, computed on read. Named views are composed client-side.
    by_status, by_source = _member_status_counts(db, user.id)
    coverage = _coverage(db, settings)
    scoring_coverage = coverage.get("candidatesScored")
    # A completed score-only run is the committee's deliberate choice to retain the
    # current criteria for this pool. Full coverage therefore clears the Rank stale
    # state even when the discovery-input fingerprint changed.
    current_criteria_scored = (
        scoring_coverage is not None
        and scoring_coverage.in_scope > 0
        and scoring_coverage.cached == scoring_coverage.in_scope
    )

    return DashboardResponse(
        settings_complete=bool(settings.google_sheet_id),
        counts=DashboardCounts(
            submitted=total,
            status={s.value: by_status.get(s, 0) for s in ApplicationStatus},
            source={s.value: by_source.get(s, 0) for s in StatusSource},
        ),
        # Whether each step has run, from persisted data so workflow gating survives
        # a reload. Sync is "done" once any application exists; the AI steps once any
        # result of their kind exists.
        workflow=WorkflowState(
            synced=total > 0,
            # Whether the latest import used the settings as they are now. Changed
            # import-relevant settings flag Import amber (a re-import would
            # reclassify eligibility). We can't detect a changed spreadsheet, so this
            # is "probably fresh," not a guarantee.
            import_current=_import_is_current(db, settings),
            screened=_kind_exists(db, "screening"),
            # Pattern discovery is a ranking run, not a per-application result.
            patterns_discovered=_run_exists(db),
            # Scoring kinds are per-dimension, so match by prefix.
            candidates_scored=_kind_prefix_exists(db, "dimension_scoring:"),
            # A full discovery run is fresh when its inputs match; alternatively,
            # complete current-criteria coverage records the score-only path.
            ranking_current=(
                ranking_is_current(db, get_current_analysis(db), settings)
                or current_criteria_scored
            ),
        ),
        # Per-AI-step coverage of the current scope. A step whose results predate a
        # re-sync goes stale (cached < inScope) even though it ran, so the UI warns
        # instead of showing a misleading done-check.
        coverage=coverage,
    )


def _import_is_current(db: Session, settings) -> bool:
    """True when the latest import's settings fingerprint matches the live one.
    Also true if there's no import yet (nothing to be stale). False only when a
    stored fingerprint differs.
    """
    latest = db.scalar(select(SyncRun).order_by(SyncRun.id.desc()).limit(1))
    if latest is None:
        return True
    return latest.settings_fingerprint == settings_fingerprint(settings)


def _coverage(db: Session, settings) -> dict[str, CoverageEntry]:
    # Coverage is a cache-hit count, so each pass must be probed under the model it
    # actually runs on — a cache row's key includes the model. These are separate
    # settings now, so don't share one variable across passes.
    def covered(
        applications, kind: str, prompt_version: str, model: str
    ) -> CoverageEntry:
        cached = sum(
            1
            for app in applications
            if db.scalar(
                select(ApplicationAIResult.id).where(
                    ApplicationAIResult.cache_key
                    == cache_key(
                        application=app, kind=kind, model_id=model,
                        prompt_version=prompt_version,
                    )
                )
            )
            is not None
        )
        return CoverageEntry(cached=cached, in_scope=len(applications))

    result = {
        # Screening's version folds in the pet-policy line, so changing the pet limits
        # drops coverage (cached < inScope) and Screen shows out of date — same as a
        # prompt edit.
        "screened": covered(
            screening_scope(db), "screening", screening_prompt_version(settings),
            settings.ai.screening_model,
        ),
    }
    # Scoring coverage is only meaningful against the current run. A candidate
    # counts as scored once it has a cached row for EVERY dimension key, so partial
    # coverage reads as not-yet-complete.
    kinds = current_dimension_kinds(db)
    if kinds:
        applications = applications_to_score(db)
        fully_scored = sum(
            1
            for app in applications
            if all(
                db.scalar(
                    select(ApplicationAIResult.id).where(
                        ApplicationAIResult.cache_key
                        == cache_key(
                            application=app, kind=kind,
                            model_id=settings.ai.dimension_scoring_model,
                            prompt_version=SCORING_PROMPT_VERSION,
                        )
                    )
                )
                is not None
                for kind in kinds
            )
        )
        result["candidatesScored"] = CoverageEntry(
            cached=fully_scored, in_scope=len(applications)
        )
    return result


def _kind_exists(db: Session, kind: str) -> bool:
    return (
        db.scalar(
            select(ApplicationAIResult.id).where(ApplicationAIResult.kind == kind).limit(1)
        )
        is not None
    )


def _kind_prefix_exists(db: Session, prefix: str) -> bool:
    return (
        db.scalar(
            select(ApplicationAIResult.id)
            .where(ApplicationAIResult.kind.startswith(prefix))
            .limit(1)
        )
        is not None
    )


def _run_exists(db: Session) -> bool:
    return db.scalar(select(Analysis.id).limit(1)) is not None


def _member_status_counts(
    db: Session, user_id: int
) -> tuple[dict[ApplicationStatus, int], dict[StatusSource, int]]:
    """This member's effective (status, source) tallies over every application — their
    overrides applied over the shared machine verdict. Computed on read (status is no
    longer stored), so it mirrors exactly what the applications list shows the member."""
    applications = db.scalars(select(Application)).all()
    ids = [app.id for app in applications]
    flags_by_app = machine_flags_by_app(db, ids)
    overrides = overrides_by_app(db, user_id, ids)

    by_status: dict[ApplicationStatus, int] = {}
    by_source: dict[StatusSource, int] = {}
    for app in applications:
        status, source = effective_status(
            overrides.get(app.id),
            has_reasons=bool(app.hard_filter_reasons),
            has_ai_flags=bool(flags_by_app.get(app.id)),
        )
        by_status[status] = by_status.get(status, 0) + 1
        by_source[source] = by_source.get(source, 0) + 1
    return by_status, by_source
