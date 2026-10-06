import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { deferred, renderCommittee as render } from "../../testSupport";
import type { CurrentRunResponse } from "../../types";
import { AIWorkspaceView } from "./AIWorkspaceView";

const api = vi.hoisted(() => ({
  fetchEvalCatalog: vi.fn<ReturnType<typeof import("../../api/evals").createApi>["fetchEvalCatalog"]>(),
  fetchEvalCases: vi.fn<ReturnType<typeof import("../../api/evals").createApi>["fetchEvalCases"]>(),
  fetchLastEvalRun: vi.fn<ReturnType<typeof import("../../api/evals").createApi>["fetchLastEvalRun"]>(),
  fetchJudgeBackgrounds: vi.fn<ReturnType<typeof import("../../api/evals").createApi>["fetchJudgeBackgrounds"]>(),
  fetchEvalInvariants: vi.fn<ReturnType<typeof import("../../api/evals").createApi>["fetchEvalInvariants"]>(),
}));
vi.mock("../../api/evals", async (original) => ({
  ...await original<typeof import("../../api/evals")>(), createApi: () => api,
}));
const traces = vi.hoisted(() => ({ fetchMatchAudit: vi.fn(), fetchDecomposeAudit: vi.fn(),
  fetchConsolidateAudit: vi.fn(), fetchFanOutAudit: vi.fn() }));
vi.mock("../../api/ranking", () => ({ createApi: () => traces }));

beforeEach(() => {
  vi.resetAllMocks();
  for (const read of Object.values(traces)) read.mockResolvedValue(null);
  api.fetchEvalCases.mockResolvedValue({ cases: [{ key: "synthetic", metadata: {
    pass: "screening", expected: { fires: [], absent: [] }, note: "Synthetic case",
  }, given: { fields: {}, essays: {} } }] });
  api.fetchLastEvalRun.mockResolvedValue({ runs: [], current: {} });
  api.fetchJudgeBackgrounds.mockResolvedValue({ backgrounds: [{ passName: "scoring", background: "Synthetic brief", caseCount: 1 }] });
  api.fetchEvalInvariants.mockResolvedValue({ hasFixture: true, dimensions: 1, invariants: [] });
});

const criteria = (analysisId: number): CurrentRunResponse => ({ analysisId, dimensions: [], proposedDimensions: [] });

it.each([
  ["Matching", "fetchMatchAudit"], ["Decomposition", "fetchDecomposeAudit"],
  ["Consolidation", "fetchConsolidateAudit"], ["Pattern discovery", "fetchFanOutAudit"],
] as const)("refreshes %s for the accepted criteria snapshot and requests its exact analysis", async (tab, method) => {
  const props = { family: "obs" as const, openingId: 1, refreshKey: null, onToast: vi.fn(), onError: vi.fn() };
  const first = criteria(1);
  const { rerender } = render(<AIWorkspaceView {...props} run={first} />);
  fireEvent.click(screen.getByRole("tab", { name: tab }));
  await waitFor(() => expect(traces[method]).toHaveBeenCalledExactlyOnceWith(1, 1));
  rerender(<AIWorkspaceView {...props} run={first} />);
  expect(traces[method]).toHaveBeenCalledTimes(1);
  // A remote run may finish with the same criteria object still mounted.
  // The existing dashboard poll supplies a new accepted observation.
  rerender(<AIWorkspaceView {...props} run={first} refreshKey={{}} />);
  await waitFor(() => expect(traces[method]).toHaveBeenCalledTimes(2));
  rerender(<AIWorkspaceView {...props} run={criteria(2)} />);
  await waitFor(() => expect(traces[method]).toHaveBeenLastCalledWith(1, 2));
});

it("does not display a late trace from an analysis the operator has left", async () => {
  const old = deferred<null>();
  traces.fetchMatchAudit.mockReturnValueOnce(old.promise).mockResolvedValue({ analysisId: 2,
    rawDiscoveryDimensions: [{ key: "new", name: "Current criterion" }], newToOld: {},
    priorDimensionCount: 1, discoveredCount: 1, matchedCount: 0, newCount: 1, carryForwardRate: 0 });
  const props = { family: "obs" as const, openingId: 1, refreshKey: null, onToast: vi.fn(), onError: vi.fn() };
  const { rerender } = render(<AIWorkspaceView {...props} run={criteria(1)} />);
  fireEvent.click(screen.getByRole("tab", { name: "Matching" }));
  rerender(<AIWorkspaceView {...props} run={criteria(2)} />);
  await screen.findByText("Current criterion");
  await act(async () => old.resolve(null));
  expect(screen.getByText("Current criterion")).toBeInTheDocument();
});

function setup(editable: boolean) {
  api.fetchEvalCatalog.mockResolvedValue({ fixtureEditingEnabled: editable, evals: [
    { key: "screening", label: "Screening", description: "Synthetic", spends: true, estimatedCalls: 1, repetitions: 1 },
    { key: "screening_stability", label: "Screening stability", description: "Synthetic", spends: true, estimatedCalls: 5, repetitions: 5 },
    { key: "judge", label: "Judge", description: "Synthetic", spends: true, estimatedCalls: 1, repetitions: 1 },
    { key: "stability", label: "Judge stability", description: "Synthetic", spends: true, estimatedCalls: 5, repetitions: 5 },
  ] });
  return render(<AIWorkspaceView family="eval" refreshKey={null} run={null} openingId={1} onToast={vi.fn()} onError={vi.fn()} />);
}

it("keeps hosted cases and run controls while hiding every corpus write control", async () => {
  setup(false);
  await screen.findByText(/Edit fixtures locally/);
  fireEvent.click(await screen.findByRole("button", { name: /synthetic/ }));
  expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  expect(screen.queryByRole("button", { name: /Add case/ })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Run screening (~1)" }));
  expect(screen.getByText(/This makes ~1 model call/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

  fireEvent.click(screen.getByRole("tab", { name: "Judge" }));
  expect(await screen.findByRole("textbox", { name: "scoring judge brief", hidden: true })).toHaveAttribute("readonly");
  expect(screen.queryByRole("button", { name: "Save brief", hidden: true })).toBeNull();
  expect(screen.getByRole("button", { name: /Run judge/ })).toBeEnabled();

  fireEvent.click(screen.getByRole("tab", { name: "Invariants" }));
  await screen.findByText(/dimensions in the baseline/);
  expect(screen.queryByRole("button", { name: /Re-baseline/ })).toBeNull();
});

it("preserves local case, brief and baseline editing", async () => {
  setup(true);
  fireEvent.click(await screen.findByRole("button", { name: /synthetic/ }));
  expect(screen.getByRole("button", { name: "Edit" })).toBeEnabled();
  expect(screen.getByRole("button", { name: /Add case/ })).toBeEnabled();
  fireEvent.click(screen.getByRole("tab", { name: "Judge" }));
  expect(await screen.findByRole("textbox", { name: "scoring judge brief", hidden: true })).not.toHaveAttribute("readonly");
  expect(screen.getByRole("button", { name: "Save brief", hidden: true })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "Invariants" }));
  await screen.findByText(/dimensions in the baseline/);
  expect(screen.getByRole("button", { name: /Re-baseline/ })).toBeEnabled();
});

it("keeps paid controls unavailable when run details fail and offers Retry", async () => {
  api.fetchEvalCatalog.mockRejectedValueOnce(new Error("Synthetic failure"));
  render(<AIWorkspaceView family="eval" refreshKey={null} run={null} openingId={null} onToast={vi.fn()} onError={vi.fn()} />);
  await screen.findByText("Could not load eval run details.");
  expect(screen.getByRole("button", { name: /Run screening/ })).toBeDisabled();
  api.fetchEvalCatalog.mockResolvedValue({ fixtureEditingEnabled: false, evals: [
    { key: "screening", label: "Screening", description: "Synthetic", spends: true, estimatedCalls: 1, repetitions: 1 },
  ] });
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Run screening (~1)" })).toBeEnabled());
});
