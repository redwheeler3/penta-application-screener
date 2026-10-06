"""Adopt valid saved findings and scores without starting an AI run."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.analysis import cache_key
from app.ai.dimension_scoring import (
    PROMPT_VERSION,
    applications_to_score,
    kind_for_dimension,
)
from app.ai.result_selection import select_results
from app.ai.screening import applications_for_screening, screening_prompt_version
from app.db.models import (
    Application,
    ApplicationAIResult,
    ApplicationAISelection,
    Opening,
    OpeningPhase,
    RunLock,
)
from app.schemas.settings import AppSettings, effective_reasoning_effort
from app.services.openings.catalog import opening_phase
from app.services.ranking.analysis import get_current_analysis
from app.services.ranking.dimensions import current_dimension_report
from app.services.run_lock import LEASE_TTL, lock_run_state
from app.services.settings import get_app_settings


def _matching_references(db: Session, applications: list[Application], kinds: list[str], *, model: str,
                         prompt: str, reasoning: str | None) -> list[tuple[int, str, int]]:
    expected = {(app.id, kind): cache_key(application=app, kind=kind, model_id=model,
        prompt_version=prompt, reasoning_effort=reasoning) for app in applications for kind in kinds}
    keys = list(set(expected.values()))
    cached = {}
    for start in range(0, len(keys), 500):
        cached.update(db.execute(select(ApplicationAIResult.cache_key, ApplicationAIResult.id)
            .where(ApplicationAIResult.cache_key.in_(keys[start:start + 500]))).all())
    selected = {}
    ids = [app.id for app in applications]
    for start in range(0, len(ids), 500):
        rows = db.execute(select(ApplicationAISelection.application_id, ApplicationAISelection.kind,
            ApplicationAISelection.result_id).where(ApplicationAISelection.application_id.in_(ids[start:start + 500]),
                ApplicationAISelection.kind.in_(kinds)))
        selected.update(((app_id, kind), result_id) for app_id, kind, result_id in rows)
    references = [(app_id, kind, cached[key]) for (app_id, kind), key in expected.items()
                  if key in cached and selected.get((app_id, kind)) != cached[key]]
    return references


def _screening_references(db: Session, opening_id: int, settings: AppSettings):
    return _matching_references(db, applications_for_screening(db, opening_id), ["screening"],
        model=settings.ai.screening_model, prompt=screening_prompt_version(),
        reasoning=effective_reasoning_effort(settings.ai.screening_model, settings.ai.screening_reasoning_effort))


def _scoring_references(db: Session, opening_id: int, settings: AppSettings):
    analysis = get_current_analysis(db, opening_id)
    report = current_dimension_report(analysis) if analysis is not None else None
    if report is None:
        return []
    references = _matching_references(db, applications_to_score(db, opening_id),
        [kind_for_dimension(dim.key) for dim in report.dimensions], model=settings.ai.dimension_scoring_model,
        prompt=PROMPT_VERSION, reasoning=effective_reasoning_effort(
            settings.ai.dimension_scoring_model, settings.ai.dimension_scoring_reasoning_effort))
    return references


def refresh_cached_results(db: Session, opening_id: int) -> bool:
    """Refresh only differing references, rechecking scope/inputs under a short writer.

    Ordinary refreshes avoid a write when every reference is already current. An active
    AI run owns publication; background reuse waits for a later refresh rather than
    replacing its captured work. No provider call, run claim or spending ledger is used.
    """
    settings = get_app_settings(db)
    if not _screening_references(db, opening_id, settings) and not _scoring_references(db, opening_id, settings):
        return False
    lock_run_state(db)
    db.expire_all()
    opening = db.get(Opening, opening_id)
    active_run = db.scalar(select(RunLock.id).where(RunLock.holder_user_id.is_not(None),
        RunLock.renewed_at >= datetime.now(UTC) - LEASE_TTL))
    if opening is None or opening_phase(opening) == OpeningPhase.ARCHIVED or active_run is not None:
        db.rollback()
        return False
    settings = get_app_settings(db)
    screening = _screening_references(db, opening_id, settings)
    select_results(db, screening)
    # Refreshed pet facts and flags can change the eligible scoring pool.
    scores = _scoring_references(db, opening_id, settings)
    select_results(db, scores)
    db.commit()
    return bool(screening or scores)
