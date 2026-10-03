import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import * as api from "../../api/evals";
import { deferred } from "../../testSupport";
import { RunnableEval } from "./RunnableEval";

vi.mock("../../api/evals", async (original) => ({
  ...await original<typeof import("../../api/evals")>(),
  fetchEvalCases: vi.fn(), fetchLastEvalRun: vi.fn(), saveEvalCase: vi.fn(),
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
  vi.mocked(api.fetchEvalCases).mockResolvedValue({ cases });
  vi.mocked(api.fetchLastEvalRun).mockResolvedValue({ runs: [] });
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
  await act(async () => { save.resolve(Response.json({ cases })); });
  expect(screen.getByDisplayValue("New B draft")).toBeInTheDocument();
  expect(screen.getByText("Edit case: b")).toBeInTheDocument();
});

it("acknowledges the submitted case while retaining text typed during its save", async () => {
  const save = deferred<Response>();
  vi.mocked(api.saveEvalCase).mockReturnValueOnce(save.promise).mockResolvedValueOnce(Response.json({ cases }));
  setup();
  await edit("a");
  const editor = screen.getByDisplayValue("Original A");
  fireEvent.click(screen.getByRole("button", { name: "Save case" }));
  fireEvent.change(editor, { target: { value: "Newer A draft" } });
  await act(async () => { save.resolve(Response.json({ cases })); });
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

it.each(["a", "new"])("starts a fresh template when switching case %s to Add case", async (key) => {
  vi.mocked(api.fetchEvalCases).mockResolvedValue({ cases: [{ ...cases[0], key }] });
  const { container } = setup();
  fireEvent.click(await screen.findByRole("button", { name: key }));
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  fireEvent.click(screen.getByRole("button", { name: "+ Add case" }));
  expect(screen.getByText("Add case", { selector: "strong" })).toBeInTheDocument();
  expect(container.querySelector(".eval-editor input")).toHaveValue("");
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
  await act(async () => { first.resolve(Response.json({ cases })); });
  expect(api.saveEvalCase).toHaveBeenCalledTimes(2);
  expect(api.saveEvalCase).toHaveBeenLastCalledWith("scoring", cases[1]);
  expect(screen.getByText("Edit case: b")).toBeInTheDocument();
  await act(async () => { second.resolve(Response.json({ cases })); });
  expect(screen.queryByText("Edit case: b")).not.toBeInTheDocument();
});
