import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { renderCommittee as render } from "../../testSupport";
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

beforeEach(() => {
  vi.resetAllMocks();
  api.fetchEvalCases.mockResolvedValue({ cases: [{ key: "synthetic", metadata: {
    pass: "screening", expected: { fires: [], absent: [] }, note: "Synthetic case",
  }, given: { fields: {}, essays: {} } }] });
  api.fetchLastEvalRun.mockResolvedValue({ runs: [] });
  api.fetchJudgeBackgrounds.mockResolvedValue({ backgrounds: [{ passName: "scoring", background: "Synthetic brief", caseCount: 1 }] });
  api.fetchEvalInvariants.mockResolvedValue({ hasFixture: true, dimensions: 1, invariants: [] });
});

function setup(editable: boolean) {
  api.fetchEvalCatalog.mockResolvedValue({ fixtureEditingEnabled: editable, evals: [
    { key: "screening", label: "Screening", description: "Synthetic", spends: true, estimatedCalls: 1 },
    { key: "screening_stability", label: "Screening stability", description: "Synthetic", spends: true, estimatedCalls: 5 },
  ] });
  return render(<AIWorkspaceView family="eval" run={null} openingId={1} onToast={vi.fn()} onError={vi.fn()} />);
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
