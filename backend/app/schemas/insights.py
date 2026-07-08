"""Response shapes for the Insights tab's run-level observability (M13)."""

from app.schemas.base import ResponseModel


class CostPass(ResponseModel):
    """One pass's aggregated cost. ``input_tokens``/``output_tokens`` are 0 for the
    discovery and matching passes, which store cost only (no token breakdown)."""

    pass_label: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class CostGroup(ResponseModel):
    """The passes triggered by one user-facing run (Screen or Rank), with a subtotal.
    Screen runs the screening pass; Rank runs essay analysis → pattern discovery →
    dimension matching → dimension scoring."""

    run_label: str
    passes: list[CostPass]
    subtotal_usd: float


class CostReport(ResponseModel):
    """GET /ranking/insights/cost — cumulative AI spend across all runs, grouped by the
    run that triggers each pass (Screen vs. Rank).

    Every dollar ever spent (all passes, all runs) — exact. Note this is unrelated to
    the spending cap: the cap bounds each individual run (Screen or Rank) against its
    estimate before it starts; this lifetime total is the running sum across all runs
    and has no ceiling of its own. A per-run "what did this run cost" figure is
    deliberately omitted: cost rows are a reuse cache with no run-id stamp, so per-run
    cost can't be reconstructed without over-counting (would need run attribution
    stamped at write time).
    """

    groups: list[CostGroup]
    total_cost_usd: float
