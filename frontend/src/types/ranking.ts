// The current run's discovered dimensions, from GET /ranking/current.
export type PoolDimension = {
  key: string;
  name: string;
  definition: string;
  highEnd: string;
  lowEnd: string;
  whyItDifferentiates: string;
  // True when a member proposed this axis on THIS run (per-run provenance, cleared on
  // the next Rank). Drives the chip's "Requested" pill; see enforce_committee_requests.
  fromCommitteeRequest: boolean;
};

// --- Ranking: the deterministic ranked shortlist from GET /ranking,
// pure math over the cached scores. Mirrors the backend ranking dataclasses.

// How one dimension fed a candidate's fit. `impact` = weight × (score − pool mean):
// magnitude ranks "what mattered", sign gives direction.
export type DimensionContribution = {
  dimensionKey: string;
  name: string;
  score: number;
  weight: number;
  impact: number;
  confidence: "low" | "medium" | "high";
  rationale: string;
  evidence: string;
};

export type RankedCandidate = {
  applicationId: number;
  name: string | null;
  rank: number; // 1-based position
  fit: number; // -1..+1 weighted average — supporting detail, not the headline
  band: string; // relative pool-position label (Strong fit … Limited)
  contributions: DimensionContribution[];
  // Whether the signed-in member has starred this applicant (private per member).
  starredByMe: boolean;
  // Whether the committee has placed this applicant on its shared shortlist.
  shortlisted: boolean;
};

export type RankingResponse = {
  analysisId: number;
  weights: Record<string, number>;
  scoredCount: number;
  candidates: RankedCandidate[];
  // Unacknowledged flagged dimensions (new OR revived), recomputed on every tier save
  // so badges clear in the same round-trip.
  newDimensionKeys: string[];
  // Subset of newDimensionKeys that are "revived" (seen in an earlier run, dropped,
  // now back) — the UI badges these blue vs. amber "new". new = flagged − revived.
  revivedDimensionKeys: string[];
  // Keys a member proposed on THIS run, not yet dismissed — the "Requested" pill.
  // Cleared on the next Rank when the underlying flag clears.
  requestedDimensionKeys: string[];
  // Kept axes: every dimension in a working (non-Ignore) tier — guaranteed to survive
  // the next Rank. Derived from tier placement. Echoed so the tier list stays in sync.
  keptKeys: string[];
  proposedDimensions: string[];
};

// One importance tier. Same tier → equal weight; higher tiers weigh more; Ignore
// weighs 0. The backend stores only working tiers and synthesizes the Ignore zone
// for display (the one with `ignore: true`), so the flag is optional here.
export type Tier = {
  id: string;
  label: string;
  dimensionKeys: string[];
  ignore?: boolean;
};

export type CurrentRunResponse = {
  analysisId: number;
  dimensions: PoolDimension[];
  // The model's streamed reasoning from the discovery pass (markdown), shown on the
  // Observability tab. Null when no narrative was captured.
  discoveryNarrative: string | null;
  // Flagged dimensions (new OR revived) absent from the immediately-prior run — they
  // are badged until the committee triages them. Empty on a first run.
  newDimensionKeys: string[];
  // Subset of newDimensionKeys that are "revived" (seen in an earlier run, dropped,
  // now back) — badged blue vs. amber "new". new = flagged − revived.
  revivedDimensionKeys: string[];
  // Keys a member proposed on THIS run, not yet dismissed — the "Requested" pill.
  // Cleared on the next Rank when the underlying flag clears.
  requestedDimensionKeys: string[];
  // Kept axes: every dimension in a working (non-Ignore) tier — guaranteed to survive
  // the next Rank (derived from tier placement). Plus pending free-text proposals fed
  // to the next Rank then consumed.
  keptKeys: string[];
  proposedDimensions: string[];
};

// GET /ranking/current/match-audit — the carry-forward trace for the current run.
// What discovery emitted before matched keys
// were rewritten, how the match pass mapped it onto prior dimensions, and the
// derived carry-forward rate. Null when no run or audit exists.
export type MatchAuditResponse = {
  analysisId: number;
  rawDiscoveryDimensions: { key: string; name: string; fromCommitteeRequest: boolean }[];
  // new dimension key → adopted prior dimension; name is null when unavailable.
  newToOld: Record<string, { key: string; name: string | null }>;
  matchNarrative: string | null;
  priorDimensionCount: number;
  discoveredCount: number;
  matchedCount: number;
  newCount: number;
  // Fraction matched onto a prior dimension. Null on a first run (undefined, not 0);
  // a persistently near-1.0 rate on re-runs is the over-matching smell.
  carryForwardRate: number | null;
};

// GET /ranking/current/decompose-audit — how the parallel discovery reports were
// settled into one non-overlapping dimension set. Null when no audit was recorded.
export type DecomposeAuditResponse = {
  analysisId: number;
  inputReportCount: number;
  inputDimensionCount: number;
  settledCount: number;
  mergeCount: number;
  // Each settled axis: its key/name, the input axes it absorbed (sourceKeys — one =
  // kept as-is, several = a merge), the committee-request flag, and the model's
  // decision reasoning (why merged / kept distinct).
  settled: {
    key: string;
    name: string;
    sourceKeys: string[];
    // source key → discovery report indices that coined it (e.g. {trade_skills: [0, 3]}),
    // so the UI can label a source "trade_skills (R0, R3)". Empty if fan-out uncaptured.
    sourceReportMap: Record<string, number[]>;
    // source key → its user-facing name, so a source shows as name + key (like Matching).
    // Empty if fan-out uncaptured; the UI then falls back to the bare source key.
    sourceNames: Record<string, string>;
    fromCommitteeRequest: boolean;
    decision: string;
  }[];
  // D9: committee-requested axes decomposition folded INTO another axis
  // (requestKey → intoKey), surfaced so a fold is visible, never silent.
  foldedRequests: { requestKey: string; intoKey: string }[];
  // The decomposition pass's free-text reasoning (markdown). Null if none surfaced.
  narrative: string | null;
};

// GET /ranking/current/consolidate-audit — the post-score duplicate-merge pass:
// score-vector correlation nominates suspected-duplicate pairs, a confirm call merges
// genuine ones (older key kept, newer aliased). Null on runs that predate the pass.
export type ConsolidateAuditResponse = {
  analysisId: number;
  // Applied merges: dropped (newer) key → kept (older canonical) key.
  merges: Record<string, string>;
  // Every nominated pair: keep/drop keys + their user-facing names (snapshotted at
  // consolidation time — a merged drop key leaves the report, so its name can't be
  // resolved later; empty when the key predates name capture), the correlation r that
  // flagged it, whether it merged, and the confirm call's reason.
  pairs: {
    keep: string;
    drop: string;
    keepName: string;
    dropName: string;
    r: number;
    merged: boolean;
    reason: string;
  }[];
  nominatedCount: number;
  mergedCount: number;
  // The confirm call's free-text reasoning (markdown). Null if none surfaced.
  narrative: string | null;
};

// GET /ranking/current/fan-out-audit — the parallel discoverers that fed
// decomposition. Each pass includes its dimensions and reasoning. Null when absent.
export type FanOutAuditResponse = {
  analysisId: number;
  k: number;
  passes: {
    dimensions: { key: string; name: string; definition: string; whyItDifferentiates: string }[];
    narrative: string | null;
  }[];
};
