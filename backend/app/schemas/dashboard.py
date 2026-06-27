"""Response shape for the dashboard router.

The status/source maps and the coverage map are keyed by enum *values* (data, e.g.
``"untouched"``, ``"eligible"``) — those stay as plain dicts, untouched by the
alias generator, which only renames declared field names.
"""

from app.schemas.base import ResponseModel


class DashboardCounts(ResponseModel):
    submitted: int
    # Keyed by ApplicationStatus / StatusSource values (data, not field names).
    status: dict[str, int]
    source: dict[str, int]


class WorkflowState(ResponseModel):
    synced: bool
    import_current: bool
    screened: bool
    essays_analyzed: bool
    patterns_discovered: bool
    candidates_scored: bool
    ranking_current: bool


class CoverageEntry(ResponseModel):
    cached: int
    in_scope: int


class DashboardResponse(ResponseModel):
    settings_complete: bool
    counts: DashboardCounts
    workflow: WorkflowState
    # Per-AI-step coverage; keys absent for steps not yet computable.
    coverage: dict[str, CoverageEntry]
