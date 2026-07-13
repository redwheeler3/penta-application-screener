"""Response shapes for the Insights tab's run-level observability (M13)."""

from app.schemas.base import ResponseModel


class CostPass(ResponseModel):
    """One pass's aggregated cost + token breakdown, summed across all runs from the
    run-cost ledger's per-pass rows.

    ``cacheable`` distinguishes passes that can reuse results (screening, dimension
    scoring) from those that always call fresh (pattern discovery, dimension matching).
    ``cached_saved_usd`` is meaningful only when ``cacheable`` —
    the UI shows "—" for non-cacheable passes, never $0, so a structural absence of
    caching doesn't read as "caching failed here"."""

    pass_label: str
    calls: int  # uncached result units; dimension scoring counts per dimension row
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cacheable: bool = False
    cached_count: int = 0  # cache reuses, summed from the ledger (0 for non-cacheable)
    cached_saved_usd: float = 0.0


class CostGroup(ResponseModel):
    """The passes triggered by one user-facing run (Screen or Rank), with subtotals.
    Screen runs the screening pass; Rank runs pattern discovery → dimension
    decomposition → dimension matching → dimension scoring."""

    run_label: str
    passes: list[CostPass]
    subtotal_usd: float
    subtotal_saved_usd: float


class CostReport(ResponseModel):
    """GET /ranking/insights/cost — cumulative AI spend across all runs, grouped by the
    run that triggers each pass (Screen vs. Rank).

    ``total_cost_usd`` is every dollar ever spent (exact). ``total_saved_usd`` is what
    caching saved, summed from the run-cost ledger — so it only covers runs since
    ledgering began, while spend is all-time. (The local DB is reset before go-live, so
    that horizon mismatch is transient dev-data noise, not surfaced to the user.)

    Note this is unrelated to the spending cap: the cap bounds each individual run
    against its estimate before it starts; this lifetime total has no ceiling of its own.
    """

    groups: list[CostGroup]
    total_cost_usd: float
    total_saved_usd: float


class LastRunPass(ResponseModel):
    """One pass within a single completed run: what it spent fresh vs. reused from cache,
    plus the fresh token breakdown. ``cached_saved_usd`` is the reused results' original
    cost — an estimate of what regenerating them would have cost (what caching saved this
    run)."""

    label: str
    fresh_usd: float
    fresh_calls: int  # uncached result units; dimension scoring counts dimensions
    input_tokens: int = 0
    output_tokens: int = 0
    cached_count: int  # cached result units, in the same units as fresh_calls
    cached_saved_usd: float
    # Whether this pass can cache at all. Pattern discovery and dimension matching
    # always call fresh, so the UI shows "—" for their savings, not $0.
    cacheable: bool = False


class LastRunCost(ResponseModel):
    kind: str  # "screen" | "rank"
    at: str  # ISO timestamp of the run
    fresh_usd: float
    cached_saved_usd: float
    passes: list[LastRunPass]


class LastRunsReport(ResponseModel):
    """GET /ranking/insights/last-runs — the most recent Screen and Rank, each with its
    fresh spend and cache savings. Either is null if that run type hasn't completed
    since per-run ledgering began."""

    screen: LastRunCost | None = None
    rank: LastRunCost | None = None
