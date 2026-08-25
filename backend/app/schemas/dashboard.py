"""Response shape for the dashboard router.

The status/source maps and the coverage map are keyed by enum *values* (data, e.g.
``"untouched"``, ``"eligible"``) — those stay as plain dicts, untouched by the
alias generator, which only renames declared field names.
"""

from app.schemas.base import ResponseModel


class WorkflowState(ResponseModel):
    applications_available: bool
    screened: bool
    patterns_discovered: bool
    candidates_scored: bool
    ranking_current: bool


class CoverageEntry(ResponseModel):
    cached: int
    in_scope: int


class DashboardResponse(ResponseModel):
    workflow: WorkflowState
    # Per-AI-step coverage; keys absent for steps not yet computable.
    coverage: dict[str, CoverageEntry]
