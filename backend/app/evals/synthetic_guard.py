"""Guard: is a Rank's applicant pool safe to commit evidence quotes from?

Score-defensibility eval cases must include the applicant's cited ``evidence`` quote —
that quote is the thing under test, so unlike every other eval category it can't be
stripped. That's only committable when the pool is SYNTHETIC (fictional test data), never
real applicants.

Rank captures synthetic assurance and contributing identities before provider work. Exporters
also check the actual current cohort; unknown history and ordinary applicant inputs fail closed.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.db.models import Analysis, Application


class NonSyntheticPoolError(RuntimeError):
    """Raised when eval-evidence capture is attempted on a pool not proven synthetic."""


def is_synthetic_pool(analysis: Analysis) -> bool:
    """True only when the run was explicitly stamped as synthetic."""
    return bool(analysis.synthetic_data and analysis.source_application_ids is not None)


def require_synthetic_pool(analysis: Analysis, applications: Sequence[Application]) -> str:
    """Assert that evidence from this run is safe to commit and return its source label."""
    if not is_synthetic_pool(analysis) or any(not application.synthetic_data for application in applications):
        raise NonSyntheticPoolError(
            f"Analysis {analysis.id} or its exported inputs are not stamped as synthetic. Committing applicant "
            "evidence quotes is refused because it may contain real applicant data."
        )
    return "synthetic application data"
