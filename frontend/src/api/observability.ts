import type { CostReport, LastRunsReport, MetricsReport } from "../types";
import { getJson } from "./client";

export const fetchCostReport = () => getJson<CostReport>("/observability/cost");

// The most recent Screen and Rank runs, each with fresh spend + cache savings.
export const fetchLastRuns = () => getJson<LastRunsReport>("/observability/last-runs");

// Operational trends across all runs: cost, tokens, latency, cache use, and failures.
export const fetchMetrics = () => getJson<MetricsReport>("/observability/metrics");
