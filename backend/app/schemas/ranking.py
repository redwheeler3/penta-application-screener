"""Response/request shapes for the ranking router.

Reuses the applications boundary out-models (`DimensionContributionOut`) for the
ranked candidates, so the ranked-list row and the candidate-detail contributions
share one wire shape. ``PoolDimensionOut`` is a camelCase view of the stored
``PoolDimension`` (which stays snake_case as the prompt/storage contract).
"""

from app.schemas.applications import DimensionContributionOut
from app.schemas.base import RequestModel, ResponseModel


class PoolDimensionOut(ResponseModel):
    """Camel-cased view of a stored discovery dimension."""

    key: str
    name: str
    definition: str
    high_end: str = ""
    low_end: str = ""
    why_it_differentiates: str
    from_committee_request: bool = False


class CurrentRunResponse(ResponseModel):
    """GET /ranking/current — the current run's discovered criteria, or null."""

    analysis_id: int
    dimensions: list[PoolDimensionOut]
    # The model's streamed reasoning from the discovery pass (markdown), for the
    # Insights trace. Null for runs from before it was captured / if the provider
    # surfaced none.
    discovery_narrative: str | None = None
    new_dimension_keys: list[str] = []
    # Subset of new_dimension_keys that are "revived" (seen in an earlier run, dropped,
    # now back) rather than genuinely new — derived from history at read time. The
    # frontend colours these blue ("Revived") vs. amber ("New"); new = flagged − revived.
    revived_dimension_keys: list[str] = []
    # Keys a member proposed on THIS run (from_committee_request) not yet dismissed —
    # drives the chip's "Requested" provenance pill. Cleared on the next Rank when the
    # underlying flag clears; see requested_flag_keys.
    requested_dimension_keys: list[str] = []
    kept_keys: list[str] = []
    proposed_dimensions: list[str] = []


class RawDiscoveryDimensionOut(ResponseModel):
    """One dimension as discovery emitted it, before matched keys were rewritten."""

    key: str
    name: str
    from_committee_request: bool = False


class PriorDimensionRef(ResponseModel):
    """The prior dimension a matched new dimension carried forward from: its key and
    (when known) its user-facing name. ``name`` is null for audits written before the
    prior-names capture existed."""

    key: str
    name: str | None = None


class MatchAuditResponse(ResponseModel):
    """GET /ranking/current/match-audit — the carry-forward trace for the current
    run (M13 per-run AI legibility). Null when no run exists or the run predates
    match-audit capture.

    ``carryForwardRate`` is null on a first run (no prior dimensions to match); a
    persistently near-1.0 rate on re-runs is the over-matching smell.
    """

    analysis_id: int
    raw_discovery_dimensions: list[RawDiscoveryDimensionOut]
    new_to_old: dict[str, PriorDimensionRef]  # new dimension key → the prior dim it adopted
    match_narrative: str | None = None
    prior_dimension_count: int
    discovered_count: int
    matched_count: int
    new_count: int
    carry_forward_rate: float | None = None


class SettledDimensionOut(ResponseModel):
    """One settled axis from the decomposition, for the Insights trace: what it is,
    the input axes it absorbed (``sourceKeys`` — one = kept as-is, several = a merge),
    and the model's ``decision`` reasoning (why merged / kept distinct).

    ``sourceReportMap`` maps each source key to the discovery report indices (0-based)
    that coined it — so the UI can label a source as "trade_skills (R0, R3)", showing
    which of the K discoverers surfaced it (a key in several reports = independent
    re-discovery). Empty for runs whose fan-out audit wasn't captured."""

    key: str
    name: str
    source_keys: list[str]
    source_report_map: dict[str, list[int]] = {}
    # source key → its user-facing name, so the panel labels each input axis by name +
    # key (mirroring the Matching tab). Empty for runs whose fan-out wasn't captured; the
    # UI then falls back to the bare source key.
    source_names: dict[str, str] = {}
    from_committee_request: bool = False
    decision: str


class FoldedRequestOut(ResponseModel):
    """A committee-requested axis that decomposition merged INTO another (D9): the
    request key and the settled axis it was folded into. Surfaced so a fold is visible
    to the committee, never a silent disappearance."""

    request_key: str
    into_key: str


class DecomposeAuditResponse(ResponseModel):
    """GET /ranking/current/decompose-audit — how the K fan-out discovery reports were
    settled into one non-overlapping set for the current run. Null when the run predates
    decomposition (single-discovery runs).

    ``mergeCount`` / the settle-down from ``inputDimensionCount`` to ``settledCount`` show
    how much the decomposition collapsed; ``foldedRequests`` is the D9 committee-request
    trail (empty when no request was merged away)."""

    analysis_id: int
    input_report_count: int
    input_dimension_count: int
    settled_count: int
    merge_count: int
    settled: list[SettledDimensionOut]
    folded_requests: list[FoldedRequestOut] = []
    # The decomposition pass's free-text reasoning (markdown), for the Insights panel.
    narrative: str | None = None


class ConsolidatedPairOut(ResponseModel):
    """One correlation-nominated duplicate pair and its confirm verdict, for the trace:
    ``keep``/``drop`` keys (older kept, newer aliased on a merge), their user-facing names
    (``keepName``/``dropName`` — snapshotted at consolidation time, since a merged drop key
    is removed from the report right after), the correlation ``r`` that nominated it,
    whether it ``merged``, and the model's ``reason``."""

    keep: str
    drop: str
    # Snapshotted mint names; empty when the key predates name capture (older run) — the
    # panel then falls back to the bare key.
    keep_name: str = ""
    drop_name: str = ""
    r: float
    merged: bool
    reason: str = ""


class ConsolidateAuditResponse(ResponseModel):
    """GET /ranking/current/consolidate-audit — the post-score duplicate-merge pass:
    which correlated pairs were nominated and how each was adjudicated. Null when the run
    predates the pass. ``merges`` is the applied drop→keep map; ``nominatedCount`` /
    ``mergedCount`` summarize the pass at a glance."""

    analysis_id: int
    merges: dict[str, str] = {}
    pairs: list[ConsolidatedPairOut] = []
    nominated_count: int = 0
    merged_count: int = 0
    # The confirm call's free-text reasoning (markdown), for the Insights panel.
    narrative: str | None = None


class FanOutPassOut(ResponseModel):
    """One of the K parallel discoverers, for the Insights discovery panel: the
    dimensions it found and its own reasoning narrative (null on legacy runs that stored
    reports without per-pass narratives)."""

    dimensions: list[PoolDimensionOut]
    narrative: str | None = None


class FanOutAuditResponse(ResponseModel):
    """GET /ranking/current/fan-out-audit — the K fresh-context discovery passes that
    fed decomposition, so the committee can see each discoverer (not just the one whose
    reasoning streamed live). Null on runs that predate the fan-out redesign."""

    analysis_id: int
    k: int
    passes: list[FanOutPassOut]


class RankEstimateBreakdown(ResponseModel):
    criteria_usd: float
    match_usd: float
    scoring_usd: float


class RankEstimateResponse(ResponseModel):
    """GET /ranking/run/estimate — combined cost projection for the rank chain."""

    eligible: int
    # K parallel discovery calls per Rank (the fan-out width), so the confirm card can
    # name it ("N parallel discoveries, then settle them into one set").
    fan_out: int
    breakdown: RankEstimateBreakdown
    estimated_usd: float
    approximate: bool
    cap_usd: float
    within_cap: bool
    ranking_current: bool


class ScoreCurrentEstimateResponse(ResponseModel):
    """Cost projection for filling missing scores on the current dimension set."""

    eligible: int
    to_analyze: int
    cached: int
    dimensions: int
    estimated_usd: float
    cap_usd: float
    within_cap: bool


class RankedCandidateOut(ResponseModel):
    """Camel-cased view of the ranking ``RankedCandidate`` dataclass."""

    application_id: int
    name: str | None = None
    rank: int
    fit: float
    band: str
    contributions: list[DimensionContributionOut]
    # Whether the current member has starred this applicant (private per member).
    starred_by_me: bool = False


class RankingResponse(ResponseModel):
    """GET /ranking and PUT /ranking/tiers — the ranked shortlist for the analysis."""

    # The shared analysis this ranking is for. The client echoes it back on a tier/seed
    # save so the server can reject a save against a superseded analysis (409 stale_analysis).
    analysis_id: int
    weights: dict[str, float]  # keyed by dimension key (data)
    scored_count: int
    candidates: list[RankedCandidateOut]
    new_dimension_keys: list[str] = []
    revived_dimension_keys: list[str] = []
    # Keys a member proposed on THIS run not yet dismissed — the "Requested" pill; kept
    # in sync after a tier/ack save so the badge clears in the same round-trip.
    requested_dimension_keys: list[str] = []
    kept_keys: list[str] = []
    proposed_dimensions: list[str] = []


class TierOut(ResponseModel):
    id: str
    label: str
    dimension_keys: list[str] = []
    ignore: bool = False


class TiersResponse(ResponseModel):
    """GET /ranking/tiers — the committee's importance-tier layout."""

    tiers: list[TierOut]


class SeedsResponse(ResponseModel):
    """PUT /ranking/seeds — the current pending-proposal state."""

    proposed_dimensions: list[str] = []


# --- Request bodies (camelCase-only on the wire) ----------------------------


class TierModel(RequestModel):
    id: str
    label: str
    dimension_keys: list[str] = []
    ignore: bool = False


class TierLayoutUpdate(RequestModel):
    # The analysis the client is viewing. If it isn't the current one (another member
    # re-ranked since), the save is rejected with 409 stale_analysis rather than applied
    # to the wrong board. Always current at one member, so inert until real concurrency.
    analysis_id: int
    tiers: list[TierModel]
    # Keys the committee acknowledged as "reviewed" this save (badge ✕ / "mark all
    # reviewed") — they drop out of new_dimension_keys even if left in Ignore.
    acknowledged_keys: list[str] = []
    # Keys whose "Requested" provenance pill the committee dismissed (its ✕). Separate
    # from acknowledged_keys because requested is provenance, not triage — it never
    # clears on a move, only on this explicit dismissal.
    acknowledged_requested_keys: list[str] = []


class SeedsUpdate(RequestModel):
    # The analysis the client is viewing — same stale-guard as TierLayoutUpdate.
    analysis_id: int
    # Optional so a no-op PUT leaves proposals untouched.
    proposed_dimensions: list[str] | None = None
