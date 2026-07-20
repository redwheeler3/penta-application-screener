"""Shared helpers for the golden-case harvest scripts (``harvest_scoring_cases``,
``harvest_screening_cases``).

Harvesting a scoring/screening golden case means committing an applicant's real evidence
(essay text, flag quotes), which is only safe on a SYNTHETIC pool — so every harvest routes
through ``require_synthetic_pool`` (fail-safe: refuses any run not traceable to an allowlisted
synthetic sheet). These are OPERATOR tools: they PROPOSE unlabelled candidates in the current
golden envelope (``{key, metadata:{expected…}, given}``) shaped as an EXACT slice of a real
run's input; a human picks the instructive ones, fills the SET_ME label + note, drops the
HARVEST_ key prefix, and commits them into ``<pass>_golden.json``. Capture never labels.

Run by hand from ``backend/``: ``python -m scripts.harvest_scoring_cases`` /
``python -m scripts.harvest_screening_cases``. No runtime caller.
"""

from __future__ import annotations

from app.db.models import RankingRun
from app.db.session import SessionLocal
from app.evals.synthetic_guard import require_synthetic_pool


def latest_run(db) -> RankingRun | None:
    """The newest ranking run (harvest reads the most recent run's cached output)."""
    from sqlalchemy import select

    return db.scalars(select(RankingRun).order_by(RankingRun.id.desc())).first()


def opaque_index(application_ids: list[int]) -> dict[int, int]:
    """Stable application_id → opaque 0-based index (sorted), so a proposed case names the
    applicant only by position — never the real id, matching the fixture's PII discipline."""
    return {aid: i for i, aid in enumerate(sorted(set(application_ids)))}


def open_synthetic_run():
    """Open a session + resolve the newest run, GATED on the synthetic-pool guard. Returns
    ``(db, run, sheet_id)``; the caller closes ``db``. Raises via ``require_synthetic_pool`` if
    the run's pool isn't allowlisted-synthetic — the fail-safe that keeps real applicant
    evidence out of committed fixtures. Returns ``(db, None, "")`` if there is no run yet."""
    db = SessionLocal()
    run = latest_run(db)
    if run is None:
        return db, None, ""
    sheet_id = require_synthetic_pool(db, run)  # raises on a non-synthetic pool
    return db, run, sheet_id
