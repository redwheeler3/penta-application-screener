import { act, fireEvent, screen } from "@testing-library/react";
import { renderCommittee as render, deferred } from "../../testSupport";
import { beforeEach, expect, it, vi } from "vitest";
import { JudgeBackgrounds } from "./JudgeBackgrounds";

const api = vi.hoisted(() => ({
  fetchJudgeBackgrounds: vi.fn<ReturnType<typeof import("../../api/evals").createApi>["fetchJudgeBackgrounds"]>(),
  saveJudgeBackground: vi.fn<ReturnType<typeof import("../../api/evals").createApi>["saveJudgeBackground"]>(),
}));

vi.mock("../../api/evals", () => ({
  createApi: () => api,
}));

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.fetchJudgeBackgrounds).mockResolvedValue({ backgrounds: [
    { passName: "scoring", background: "Original scoring", caseCount: 1 },
    { passName: "screening", background: "Original screening", caseCount: 2 },
  ] });
});

it("retains edits typed while saving and tracks independent pending passes", async () => {
  const scoring = deferred<Response>();
  const screening = deferred<Response>();
  vi.mocked(api.saveJudgeBackground).mockReturnValueOnce(scoring.promise).mockReturnValueOnce(screening.promise);
  const onSaved = vi.fn();
  render(<JudgeBackgrounds onToast={vi.fn()} onError={vi.fn()} onSaved={onSaved} />);
  const editor = await screen.findByRole("textbox", { name: "scoring judge brief", hidden: true });
  fireEvent.click(screen.getByText(/Judge briefs/));
  fireEvent.change(editor, { target: { value: "Submitted scoring" } });
  fireEvent.click(screen.getAllByRole("button", { name: "Save brief" })[0]);
  fireEvent.change(editor, { target: { value: "Newer scoring draft" } });
  fireEvent.change(screen.getByRole("textbox", { name: "screening judge brief" }), { target: { value: "Submitted screening" } });
  fireEvent.click(screen.getByRole("button", { name: "Save brief" }));
  await act(async () => { screening.resolve(Response.json({ passName: "screening", background: "Submitted screening", caseCount: 2 })); });
  expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();
  await act(async () => { scoring.resolve(Response.json({ passName: "scoring", background: "Submitted scoring", caseCount: 1 })); });
  expect(onSaved).toHaveBeenCalledTimes(2);
  expect(editor).toHaveValue("Newer scoring draft");
  expect(screen.getAllByRole("button", { name: "Save brief" })[0]).toBeEnabled();
  expect(screen.getAllByRole("button", { name: "Save brief" })[1]).toBeDisabled();
});

it("keeps a failed draft available for retry", async () => {
  vi.mocked(api.saveJudgeBackground).mockRejectedValue(new Error("Synthetic network failure"));
  const onError = vi.fn();
  render(<JudgeBackgrounds onToast={vi.fn()} onError={onError} />);
  const editor = await screen.findByRole("textbox", { name: "scoring judge brief", hidden: true });
  fireEvent.click(screen.getByText(/Judge briefs/));
  fireEvent.change(editor, { target: { value: "Keep this draft" } });
  await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Save brief" })[0]); });
  expect(onError).toHaveBeenCalledOnce();
  expect(editor).toHaveValue("Keep this draft");
  expect(screen.getAllByRole("button", { name: "Save brief" })[0]).toBeEnabled();
});
