"""Guard: is a Rank's applicant pool SAFE to commit evidence quotes from?

Score-defensibility eval cases must include the applicant's cited ``evidence`` quote —
that quote is the thing under test, so unlike every other eval category it can't be
stripped. That's only committable when the pool is SYNTHETIC (fictional test data), never
real applicants.

The DB can't infer synthetic-vs-real: both arrive via a Google Sheet, recorded only as
``SyncRun.source_sheet_id``. So the safe pool is identified by an explicit **allowlist of
known-synthetic sheet ids**. The synthetic pool was made by exporting
``test-data/synthetic-penta-application-responses.csv`` into one specific sheet; that id
is allowlisted below. Any other sheet — including a real deployment's — is rejected BY
DEFAULT (fail-safe: you never add a real sheet here, so the guard can't be tripped by
forgetting a flag). Verifiable from data the DB actually has, not an operator promise.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import RankingRun, SyncRun

# Google Sheet ids whose contents are known-synthetic (the test-data CSV, exported to a
# sheet for import). Add ONLY sheets you can personally vouch contain no real applicant
# data. A real deployment's sheet must never appear here.
SYNTHETIC_SHEET_IDS: frozenset[str] = frozenset({
    "1shuJeJRWL05F4TCQ9yr0-uiQB58MbjaNc6dkokmBn8Y",  # test-data/synthetic-penta-...csv export
})


class NonSyntheticPoolError(RuntimeError):
    """Raised when eval-evidence capture is attempted on a pool not proven synthetic."""


def source_sheet_id_for_run(db: Session, run: RankingRun) -> str | None:
    """The Google Sheet id the run's pool was imported from, via its source SyncRun.
    None when the run has no recorded source (older/hand-built runs)."""
    if run.source_sync_run_id is None:
        return None
    sync = db.get(SyncRun, run.source_sync_run_id)
    return sync.source_sheet_id if sync is not None else None


def is_synthetic_pool(db: Session, run: RankingRun) -> bool:
    """True only when the run's pool traces to an allowlisted synthetic sheet."""
    sheet_id = source_sheet_id_for_run(db, run)
    return sheet_id is not None and sheet_id in SYNTHETIC_SHEET_IDS


def require_synthetic_pool(db: Session, run: RankingRun) -> str:
    """Assert the run's pool is safe to commit evidence quotes from; return the sheet id
    (for stamping ``evidence_source``). Raises ``NonSyntheticPoolError`` otherwise — the
    fail-safe gate: an unrecognized or missing source is refused, never assumed safe."""
    sheet_id = source_sheet_id_for_run(db, run)
    if sheet_id is None:
        raise NonSyntheticPoolError(
            f"Run {run.id} has no recorded source sheet — cannot prove its pool is "
            "synthetic, so committing applicant evidence quotes is refused."
        )
    if sheet_id not in SYNTHETIC_SHEET_IDS:
        raise NonSyntheticPoolError(
            f"Run {run.id}'s source sheet {sheet_id!r} is not on the synthetic allowlist. "
            "Committing applicant evidence quotes is refused (it may be real applicant "
            "data). Add the sheet to SYNTHETIC_SHEET_IDS only if you can vouch it is "
            "fictional test data."
        )
    return sheet_id
