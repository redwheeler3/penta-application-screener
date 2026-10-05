import { type ApiClient } from "./client";
import type { CostReport, LastRunsReport, MetricsReport } from "../types";

export function createApi(client: ApiClient) {
  const { getJson } = client;
  const fetchCostReport = () => getJson<CostReport>("/observability/cost");

  // The most recent Screen and Rank runs, each with fresh spend + cache savings.
  const fetchLastRuns = () => getJson<LastRunsReport>("/observability/last-runs");

  // Operational trends across all runs: cost, tokens, latency, cache use, and failures.
  const fetchMetrics = () => getJson<MetricsReport>("/observability/metrics");
  return {
    fetchCostReport, fetchLastRuns, fetchMetrics,
  };
}
