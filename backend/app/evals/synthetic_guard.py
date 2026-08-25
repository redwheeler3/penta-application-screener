"""Guard: is a Rank's applicant pool safe to commit evidence quotes from?

Score-defensibility eval cases must include the applicant's cited ``evidence`` quote —
that quote is the thing under test, so unlike every other eval category it can't be
stripped. That's only committable when the pool is SYNTHETIC (fictional test data), never
real applicants.

Each analysis records whether its data was explicitly configured as synthetic when the
run was created. The default is false, so copied or production databases fail closed.
"""

from __future__ import annotations

from app.db.models import Analysis


class NonSyntheticPoolError(RuntimeError):
    """Raised when eval-evidence capture is attempted on a pool not proven synthetic."""


def is_synthetic_pool(analysis: Analysis) -> bool:
    """True only when the run was explicitly stamped as synthetic."""
    return analysis.synthetic_data


def require_synthetic_pool(analysis: Analysis) -> str:
    """Assert that evidence from this run is safe to commit and return its source label."""
    if not is_synthetic_pool(analysis):
        raise NonSyntheticPoolError(
            f"Analysis {analysis.id} is not stamped as synthetic. Committing applicant "
            "evidence quotes is refused because it may contain real applicant data."
        )
    return "synthetic application data"
