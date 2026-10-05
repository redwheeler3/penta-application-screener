import { screen } from "@testing-library/react";
import { renderCommittee as render } from "../../testSupport";
import { expect, it, vi } from "vitest";
import { MetricsPanel } from "./MetricsPanel";

const observabilityMocks = vi.hoisted(() => ({
  fetchMetrics: vi.fn<ReturnType<typeof import("../../api/observability").createApi>["fetchMetrics"]>(),
}));
const { fetchMetrics } = observabilityMocks;

vi.mock("../../api/observability", () => ({
  createApi: () => observabilityMocks,
}));

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

it("shows interruption without inventing a zero-millisecond latency", async () => {
  vi.mocked(fetchMetrics).mockResolvedValue({ passes: [], runs: [{
    kind: "rank", status: "failed", failedPass: "Interrupted", at: "2026-10-04T12:00:00Z",
    costUsd: 0.03, inputTokens: 5000, outputTokens: 1000, durationMs: null, failedCalls: 0,
    cacheHitRate: null, dimensions: null, triggeredBy: null, opening: null,
  }] });
  render(<MetricsPanel />);
  expect(await screen.findByText("Interrupted")).toBeInTheDocument();
  expect(screen.queryByText("0ms")).not.toBeInTheDocument();
});
