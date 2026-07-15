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
    """The passes triggered by one user-facing run, with subtotals. Screen runs the
    screening pass; full Ranks discover criteria then score; score-current updates only
    score against the retained criteria."""

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
    kind: str  # "screen" | "rank" | "rank_scores"
    at: str  # ISO timestamp of the run
    fresh_usd: float
    cached_saved_usd: float
    passes: list[LastRunPass]


class LastRunsReport(ResponseModel):
    """GET /ranking/insights/last-runs — the most recent Screen, full Rank, and
    score-current update, each with fresh spend and cache savings."""

    screen: LastRunCost | None = None
    rank: LastRunCost | None = None
    rank_scores: LastRunCost | None = None


# --- Operational metrics / trends (M13 Pillar 3) ------------------------------------


class TrendPoint(ResponseModel):
    """One completed run as a point on the trend charts, oldest→newest. Per-run rollups
    over that run's pass rows; ``dimensions`` is the run's live dimension count for full
    Ranks only — null for Screen and score-current updates."""

    at: str  # ISO timestamp of the run
    kind: str  # "screen" | "rank" | "rank_scores"
    cost_usd: float
    input_tokens: int
    output_tokens: int
    duration_ms: int
    failed_calls: int
    # Cache-hit rate over cacheable units this run (cached / (cached + fresh)); null when
    # the run had no cacheable work.
    cache_hit_rate: float | None = None
    # Live dimension count for a full Rank (post-consolidation); null otherwise.
    dimensions: int | None = None


class PassTrendPoint(ResponseModel):
    """One pass within one run, for the per-pass breakdown series."""

    at: str
    label: str
    cost_usd: float
    input_tokens: int
    output_tokens: int
    duration_ms: int
    failed_calls: int


class MetricsReport(ResponseModel):
    """GET /ranking/insights/metrics — operational trends across all completed runs
    (M13 Pillar 3). ``runs`` is the per-run rollup (both kinds, oldest→newest);
    ``passes`` is the flattened per-(run, pass) series for the per-pass breakdown.
    Empty lists when no run has completed since ledgering began."""

    runs: list[TrendPoint]
    passes: list[PassTrendPoint]
