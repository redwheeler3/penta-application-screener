import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { fetchCostReport, fetchLastRuns } from "../../api/observability";
import type { LastRunCost } from "../../types";
import { CostPanel } from "./CostPanel";

vi.mock("../../api/observability", () => ({ fetchCostReport: vi.fn(), fetchLastRuns: vi.fn() }));

it("labels failed attempts as known spending without comparing partial cost to a whole-run estimate", async () => {
  const failed: LastRunCost = {
    kind: "rank", status: "failed", failedPass: "Dimension decomposition", failureType: "RuntimeError",
    at: "2026-10-04T12:00:00Z", freshUsd: 0.03, cachedSavedUsd: 0, estimatedUsd: 1,
    triggeredBy: "synthetic@example.com", opening: "2BR · Synthetic opening",
    passes: [{ label: "Pattern discovery", freshUsd: 0.03, freshCalls: 5, inputTokens: 5000, outputTokens: 1000,
      cachedCount: 0, cachedSavedUsd: 0, cacheable: false }],
  };
  vi.mocked(fetchCostReport).mockResolvedValue({ groups: [], totalCostUsd: 0.03, totalSavedUsd: 0 });
  vi.mocked(fetchLastRuns).mockResolvedValue({ screen: null, rank: failed, rankScores: null });
  render(<CostPanel />);
  expect(await screen.findByText(/Failed during Dimension decomposition · known usage only/)).toBeInTheDocument();
  expect(screen.queryByText(/est .*actual/)).not.toBeInTheDocument();
  expect(screen.getByText("5.0k → 1.0k")).toBeInTheDocument();
});
