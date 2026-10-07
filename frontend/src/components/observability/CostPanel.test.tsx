import { screen, within } from "@testing-library/react";
import { renderCommittee as render } from "../../testSupport";
import { expect, it, vi } from "vitest";
import type { LastRunCost } from "../../types";
import { CostPanel } from "./CostPanel";

const observabilityMocks = vi.hoisted(() => ({
  fetchCostReport: vi.fn<ReturnType<typeof import("../../api/observability").createApi>["fetchCostReport"]>(),
  fetchLastRuns: vi.fn<ReturnType<typeof import("../../api/observability").createApi>["fetchLastRuns"]>(),
}));
const { fetchCostReport, fetchLastRuns } = observabilityMocks;

vi.mock("../../api/observability", () => ({
  createApi: () => observabilityMocks,
}));

it("labels failed attempts as known spending without comparing partial cost to a whole-run estimate", async () => {
  const failed: LastRunCost = {
    kind: "rank", status: "failed", failedPass: "Dimension decomposition", failureType: "RuntimeError",
    at: "2026-10-04T12:00:00Z", freshUsd: 0.03, cachedSavedUsd: 0, estimatedUsd: 1,
    triggeredBy: "synthetic@example.com", opening: "2BR · Synthetic opening",
    passes: [{ label: "Pattern discovery", freshUsd: 0.03, providerCalls: 5, freshUnits: null, inputTokens: 5000, outputTokens: 1000,
      cachedCount: 0, cachedSavedUsd: 0, cacheable: false }],
  };
  vi.mocked(fetchCostReport).mockResolvedValue({ groups: [], totalCostUsd: 0.03, totalSavedUsd: 0 });
  vi.mocked(fetchLastRuns).mockResolvedValue({ screen: null, rank: failed, rankScores: null });
  render(<CostPanel />);
  expect(await screen.findByText(/Failed during Dimension decomposition · known usage only/)).toBeInTheDocument();
  expect(screen.queryByText(/est .*actual/)).not.toBeInTheDocument();
  expect(screen.getByText("5.0k → 1.0k")).toBeInTheDocument();
});

it.each([3, null])("shows comparable result counts in both tables, preserving unknown (%s)", async (freshUnits) => {
  const pass = { providerCalls: 1, freshUnits, inputTokens: 1000, outputTokens: 200,
    cachedCount: 1, cachedSavedUsd: 0.01, cacheable: true };
  fetchCostReport.mockResolvedValue({ groups: [{ runLabel: "Score current criteria",
    subtotalUsd: 0.02, subtotalSavedUsd: 0.01,
    passes: [{ ...pass, passLabel: "Dimension scoring", costUsd: 0.02 }] }], totalCostUsd: 0.02, totalSavedUsd: 0.01 });
  fetchLastRuns.mockResolvedValue({ screen: null, rank: null, rankScores: {
    kind: "rank_scores", status: "completed", failedPass: null, failureType: null,
    at: "2026-10-06T00:00:00Z", freshUsd: 0.02, cachedSavedUsd: 0.01, estimatedUsd: 0,
    triggeredBy: null, opening: null, passes: [{ ...pass, label: "Dimension scoring", freshUsd: 0.02 }],
  } });
  render(<CostPanel />);
  const cells = await screen.findAllByTitle("1 provider replies");
  expect(cells).toHaveLength(2);
  for (const cell of cells) {
    expect(cell).toHaveTextContent(freshUnits === null ? "—" : "3");
    const row = within(cell.closest("tr")!);
    expect(row.getAllByRole("cell")[3]).toHaveTextContent("1");
  }
});
