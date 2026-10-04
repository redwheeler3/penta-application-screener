import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { fetchMetrics } from "../../api/observability";
import { MetricsPanel } from "./MetricsPanel";

vi.mock("../../api/observability", () => ({ fetchMetrics: vi.fn() }));

it("distinguishes a failed run from completed history and keeps unmeasured cache rates unknown", async () => {
  vi.mocked(fetchMetrics).mockResolvedValue({ passes: [], runs: [{
    kind: "rank", status: "failed", failedPass: "Dimension matching", at: "2026-10-04T12:00:00Z",
    costUsd: 0.03, inputTokens: 5000, outputTokens: 1000, durationMs: 1000, failedCalls: 1,
    cacheHitRate: null, dimensions: null, triggeredBy: null, opening: null,
  }] });
  render(<MetricsPanel />);
  expect(await screen.findByTitle("Failed during Dimension matching")).toHaveTextContent("Failed");
  expect(screen.queryByText("Completed")).not.toBeInTheDocument();
});
