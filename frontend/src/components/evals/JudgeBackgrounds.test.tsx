import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import * as api from "../../api/evals";
import { deferred } from "../../testSupport";
import { JudgeBackgrounds } from "./JudgeBackgrounds";

vi.mock("../../api/evals", () => ({ fetchJudgeBackgrounds: vi.fn(), saveJudgeBackground: vi.fn() }));

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
  render(<JudgeBackgrounds onToast={vi.fn()} onError={vi.fn()} />);
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
