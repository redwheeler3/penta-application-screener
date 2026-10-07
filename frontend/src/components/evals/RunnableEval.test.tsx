import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { renderCommittee as render, deferred } from "../../testSupport";
import { beforeEach, expect, it, vi } from "vitest";
import { RunnableEval } from "./RunnableEval";

const api = vi.hoisted(() => ({
  fetchEvalCases: vi.fn<ReturnType<typeof import("../../api/evals").createApi>["fetchEvalCases"]>(),
  fetchLastEvalRun: vi.fn<ReturnType<typeof import("../../api/evals").createApi>["fetchLastEvalRun"]>(),
  runEval: vi.fn<ReturnType<typeof import("../../api/evals").createApi>["runEval"]>(),
  saveEvalCase: vi.fn<ReturnType<typeof import("../../api/evals").createApi>["saveEvalCase"]>(),
}));

vi.mock("../../api/evals", async (original) => ({
  ...await original<typeof import("../../api/evals")>(),
  createApi: () => api,
}));

const cases = [
  { key: "a", metadata: { note: "Original A" }, given: {} },
  { key: "b", metadata: { note: "Original B" }, given: {} },
];

function setup() {
  const notifications = { onToast: vi.fn(), onError: vi.fn() };
  const view = render(<RunnableEval caseEvalKey="scoring" runKeys={[]} description="Synthetic cases" modes={[]} {...notifications} />);
  return { ...view, ...notifications };
}

async function edit(key: "a" | "b") {
  fireEvent.click(await screen.findByRole("button", { name: key }));
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.fetchEvalCases).mockResolvedValue({ cases, caseFingerprints: {} });
  vi.mocked(api.fetchLastEvalRun).mockResolvedValue({ runs: [], current: {} });
});

it("keeps the newer case editor when a previous case save finishes", async () => {
  const save = deferred<Response>();
  vi.mocked(api.saveEvalCase).mockReturnValue(save.promise);
  setup();
  await edit("a");
  fireEvent.click(screen.getByRole("button", { name: "Save case" }));
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await edit("b");
  fireEvent.change(screen.getByDisplayValue("Original B"), { target: { value: "New B draft" } });
  await act(async () => { save.resolve(Response.json({ cases, caseFingerprints: {} })); });
  expect(screen.getByDisplayValue("New B draft")).toBeInTheDocument();
  expect(screen.getByText("Edit case: b")).toBeInTheDocument();
});

it("acknowledges the submitted case while retaining text typed during its save", async () => {
  const save = deferred<Response>();
  vi.mocked(api.saveEvalCase).mockReturnValueOnce(save.promise).mockResolvedValueOnce(Response.json({ cases, caseFingerprints: {} }));
  setup();
  await edit("a");
  const editor = screen.getByDisplayValue("Original A");
  fireEvent.click(screen.getByRole("button", { name: "Save case" }));
  fireEvent.change(editor, { target: { value: "Newer A draft" } });
  await act(async () => { save.resolve(Response.json({ cases, caseFingerprints: {} })); });
  expect(editor).toHaveValue("Newer A draft");
  expect(screen.getByRole("button", { name: "Save case" })).toBeEnabled();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Save case" })); });
  expect(api.saveEvalCase).toHaveBeenLastCalledWith("scoring", { ...cases[0], metadata: { note: "Newer A draft" } });
  expect(screen.queryByText("Edit case: a")).not.toBeInTheDocument();
});

it("blocks duplicate saves and keeps a failed draft available for retry", async () => {
  const save = deferred<Response>();
  vi.mocked(api.saveEvalCase).mockReturnValue(save.promise);
  const { onError } = setup();
  await edit("a");
  const button = screen.getByRole("button", { name: "Save case" });
  fireEvent.click(button);
  fireEvent.click(button);
  await waitFor(() => expect(api.saveEvalCase).toHaveBeenCalledOnce());
  expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();
  await act(async () => { save.reject(new Error("Synthetic network failure")); });
  expect(onError).toHaveBeenCalledOnce();
  expect(screen.getByDisplayValue("Original A")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Save case" })).toBeEnabled();
});

it("keeps old output inspectable without a passing claim after a label save and failed refresh", async () => {
  const original = { key: "a", given: {}, metadata: { expected: { score_min: 0.5, score_max: 1 } } };
  api.fetchEvalCases.mockResolvedValue({ cases: [original], caseFingerprints: { a: "a1" } });
  api.fetchLastEvalRun.mockResolvedValue({ runs: [{ runId: 1, evalKey: "scoring", ranAt: "2026-10-01T12:00:00Z",
    modelId: "synthetic", promptVersion: "v1", reasoningEffort: "", supportsReasoningEffort: false,
    caseRunIds: { a: 1 }, result: { cases: [{ key: "a", score: 0.8, passed: true, inputFingerprint: "a1",
      confidence: "high", evidence: "Synthetic", failures: [] }] } }],
    current: { scoring: { modelId: "synthetic", promptVersion: "v1", reasoningEffort: "", caseFingerprints: { a: "a1" } } } });
  render(<RunnableEval caseEvalKey="scoring" runKeys={["scoring"]} description="Synthetic" modes={[
    { evalKey: "scoring", label: "Run scoring", rowLabel: "Run case", repetitions: 1 },
  ]} onToast={vi.fn()} onError={vi.fn()} />);
  fireEvent.click((await screen.findByText("a", { selector: ".eval-case-item-key" })).closest("button")!);
  await screen.findByText("passed");
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  fireEvent.change(screen.getByDisplayValue("0.5"), { target: { value: "0.9" } });
  api.fetchLastEvalRun.mockRejectedValue(new Error("Offline"));
  api.saveEvalCase.mockResolvedValue(Response.json({ cases: [{ ...original, metadata: { expected: { score_min: 0.9, score_max: 1 } } }],
    caseFingerprints: { a: "a2" } }));
  fireEvent.click(screen.getByRole("button", { name: "Save case" }));
  await screen.findByText("not current");
  expect(screen.getByText(/score 0.8/)).toBeInTheDocument();
  expect(screen.queryByText("passed", { exact: true })).toBeNull();
  expect(api.runEval).not.toHaveBeenCalled();
});

it.each(["a", "new"])("starts a fresh template when switching case %s to Add case", async (key) => {
  vi.mocked(api.fetchEvalCases).mockResolvedValue({ cases: [{ ...cases[0], key }], caseFingerprints: {} });
  setup();
  fireEvent.click(await screen.findByRole("button", { name: key }));
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  fireEvent.click(screen.getByRole("button", { name: "+ Add case" }));
  expect(screen.getByText("Add case", { selector: "strong" })).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "Key" })).toHaveValue("");
  expect(screen.queryByDisplayValue("Original A")).not.toBeInTheDocument();
});

it("orders fixture saves without replacing the active editor with an older acknowledgement", async () => {
  const first = deferred<Response>();
  const second = deferred<Response>();
  vi.mocked(api.saveEvalCase).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  setup();
  await edit("a");
  fireEvent.click(screen.getByRole("button", { name: "Save case" }));
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await edit("b");
  fireEvent.click(screen.getByRole("button", { name: "Save case" }));
  await waitFor(() => expect(api.saveEvalCase).toHaveBeenCalledOnce());
  await act(async () => { first.resolve(Response.json({ cases, caseFingerprints: {} })); });
  expect(api.saveEvalCase).toHaveBeenCalledTimes(2);
  expect(api.saveEvalCase).toHaveBeenLastCalledWith("scoring", cases[1]);
  expect(screen.getByText("Edit case: b")).toBeInTheDocument();
  await act(async () => { second.resolve(Response.json({ cases, caseFingerprints: {} })); });
  expect(screen.queryByText("Edit case: b")).not.toBeInTheDocument();
});


it("selects, edits and runs a Judge case by family and key", async () => {
  const shared = ["matching", "consolidation"].map((pass) => ({ key: "same", metadata: { pass, expected: "keep", note: `Note for ${pass}` }, given: {} }));
  api.fetchEvalCases.mockResolvedValue({ cases: shared, caseFingerprints: {} });
  api.runEval.mockResolvedValue(new Response(JSON.stringify({ type: "summary", eval: "judge", savedPath: null,
    result: { experimentId: "same", cases: [{ key: "same", passName: "consolidation", marker: "[ok]", humanLabel: "keep", judgeLabel: "keep", contested: false, detail: "Synthetic", labelRationale: "" }] } })));
  api.saveEvalCase.mockResolvedValue(Response.json({ cases: shared, caseFingerprints: {} }));
  const mode = { evalKey: "judge" as const, label: "Judge", rowLabel: "Run case", repetitions: 2 };
  render(<RunnableEval caseEvalKey="judge" runKeys={["judge"]} description="Synthetic" groupBy="pass" addable={false} modes={[mode]} onToast={vi.fn()} onError={vi.fn()} />);
  const buttons = await screen.findAllByRole("button", { name: /same\s*keep/ });
  // Pipeline order puts matching before consolidation.
  fireEvent.click(buttons[1]);
  fireEvent.click(screen.getByRole("button", { name: "Run case" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm & run" }));
  await waitFor(() => expect(api.runEval).toHaveBeenCalledWith("judge", expect.objectContaining({ caseKey: "same", passName: "consolidation" })));
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  expect(screen.getByDisplayValue("Note for consolidation")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Save case" }));
  await waitFor(() => expect(api.saveEvalCase).toHaveBeenCalledWith("judge", shared[1]));
});

it("uses current fixture size for whole runs and the same K for a row request", async () => {
  const six = Array.from({ length: 6 }, (_, index) => ({ key: `case-${index}`, metadata: { expected: "matches" }, given: {} }));
  api.fetchEvalCases.mockResolvedValue({ cases: six, caseFingerprints: {} });
  api.runEval.mockResolvedValue(new Response(JSON.stringify({ type: "summary", eval: "matching_stability", storedRunId: 1,
    result: { experimentId: "same", cases: [] } })));
  render(<RunnableEval caseEvalKey="matching" runKeys={["matching_stability"]} description="Synthetic"
    modes={[{ evalKey: "matching_stability", label: "Run stability", rowLabel: "Run one", repetitions: 5 }]}
    onToast={vi.fn()} onError={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: /case-0/ }));
  fireEvent.click(screen.getByRole("button", { name: "Run one" }));
  expect(screen.getByText(/This makes ~5 model calls/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Confirm & run" }));
  await waitFor(() => expect(api.runEval).toHaveBeenCalledWith("matching_stability", expect.objectContaining({ k: 5, caseKey: "case-0" })));
  await waitFor(() => expect(screen.getByRole("button", { name: "Run stability (K=5) (~30)" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Run stability (K=5) (~30)" }));
  expect(screen.getByText(/This makes ~30 model calls/)).toBeInTheDocument();
});
