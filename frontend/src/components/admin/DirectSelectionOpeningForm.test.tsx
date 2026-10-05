import { act, fireEvent, screen } from "@testing-library/react";
import { renderCommittee as render, deferred } from "../../testSupport";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { OpeningSelectionCandidate } from "../../types";
import { DirectSelectionOpeningForm } from "./DirectSelectionOpeningForm";

const api = vi.hoisted(() => ({
  searchPreviousApplicants: vi.fn<ReturnType<typeof import("../../api/openings").createApi>["searchPreviousApplicants"]>(),
  createDirectSelectionOpening: vi.fn<ReturnType<typeof import("../../api/openings").createApi>["createDirectSelectionOpening"]>(),
}));

vi.mock("../../api/openings", () => ({
  createApi: () => api,
}));
const applicant = { applicationId: 1, applicantName: "Synthetic Applicant", primaryEmail: "synthetic@example.com" };
const props = { onCancel: vi.fn(), onCreated: vi.fn(), onError: vi.fn(), onReviewRetained: vi.fn(), onSavingChange: vi.fn() };
beforeEach(() => vi.resetAllMocks());

async function beginCreate() {
  vi.mocked(api.searchPreviousApplicants).mockResolvedValue([applicant]);
  const host = render(<DirectSelectionOpeningForm {...props} />);
  const user = userEvent.setup();
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "synthetic" } });
  await user.click(screen.getByRole("button", { name: "Search" }));
  await user.click(await screen.findByRole("button", { name: "Choose" }));
  fireEvent.change(screen.getByLabelText("Move-in date"), { target: { value: "2026-12-01" } });
  await user.click(screen.getByRole("button", { name: "Review direct selection" }));
  await user.click(screen.getByRole("button", { name: "Create opening and select applicant" }));
  return host;
}

it("freezes the confirmed facts and candidate during permanent selection", async () => {
  const pending = deferred<Response>();
  vi.mocked(api.createDirectSelectionOpening).mockReturnValue(pending.promise);
  await beginCreate();
  expect(screen.getByLabelText("Move-in date")).toBeDisabled();
  expect(screen.getByLabelText("Unit size")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Chosen" })).toBeDisabled();
  expect(props.onSavingChange).toHaveBeenLastCalledWith(true);
  await act(async () => pending.resolve(Response.json({ openings: [] })));
  expect(props.onCreated).toHaveBeenCalledWith([], applicant);
  expect(props.onSavingChange).toHaveBeenLastCalledWith(false);
});

it("does not finish a selection into a closed workflow", async () => {
  const pending = deferred<Response>();
  vi.mocked(api.createDirectSelectionOpening).mockReturnValue(pending.promise);
  const host = await beginCreate();
  host.unmount();
  await act(async () => pending.resolve(Response.json({ openings: [] })));
  expect(props.onCreated).not.toHaveBeenCalled();
  expect(props.onError).not.toHaveBeenCalled();
});

it("discards results for a search that has been replaced", async () => {
  const pending = deferred<OpeningSelectionCandidate[]>();
  vi.mocked(api.searchPreviousApplicants).mockReturnValueOnce(pending.promise).mockResolvedValueOnce([]);
  const user = userEvent.setup();
  render(<DirectSelectionOpeningForm {...props} />);
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "earlier" } });
  await user.click(screen.getByRole("button", { name: "Search" }));
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "newer" } });
  await user.click(screen.getByRole("button", { name: "Search" }));
  await act(async () => pending.resolve([applicant]));
  expect(screen.queryByRole("button", { name: "Choose" })).toBeNull();
  expect(screen.getByText("No previous applicants match that search.")).toBeInTheDocument();
});
