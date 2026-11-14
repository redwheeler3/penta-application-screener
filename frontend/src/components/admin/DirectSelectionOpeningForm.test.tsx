import { act, fireEvent, screen } from "@testing-library/react";
import { renderCommittee as render, deferred } from "../../testSupport";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { Opening, OpeningSelectionCandidate } from "../../types";
import { DirectSelectionOpeningForm } from "./DirectSelectionOpeningForm";

const api = vi.hoisted(() => ({
  searchPreviousApplicants: vi.fn<ReturnType<typeof import("../../api/openings").createApi>["searchPreviousApplicants"]>(),
  selectPreviousApplicant: vi.fn<ReturnType<typeof import("../../api/openings").createApi>["selectPreviousApplicant"]>(),
}));

vi.mock("../../api/openings", () => ({
  createApi: () => api,
}));
const applicant = { applicationId: 1, applicantName: "Synthetic Applicant", primaryEmail: "synthetic@example.com" };
const opening: Opening = { id: 10, unitSizeBedrooms: 2, housingChargeCents: 100000, moveInDate: "2099-12-31",
  applicationOpenDate: null, applicationCloseDate: "2099-12-01", intakeMode: "applications", phase: "preparing",
  publishedAt: null, submissionCount: 0, selectedApplicationId: null, selectedApplicantName: null,
  noHouseholdSelected: false, needsDecision: false, createdAt: "2026-01-01", updatedAt: "2026-01-01" };
const props = { opening, onCancel: vi.fn(), onCreated: vi.fn(), onUnconfirmed: vi.fn<() => Promise<void>>(), onError: vi.fn(), onReviewRetained: vi.fn(), onSavingChange: vi.fn() };
beforeEach(() => { vi.resetAllMocks(); props.onUnconfirmed.mockResolvedValue(undefined); });

async function beginCreate() {
  vi.mocked(api.searchPreviousApplicants).mockResolvedValue([applicant]);
  const host = render(<DirectSelectionOpeningForm {...props} />);
  const user = userEvent.setup();
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "synthetic" } });
  await user.click(screen.getByRole("button", { name: "Search" }));
  await user.click(await screen.findByRole("button", { name: "Choose" }));
  await user.click(screen.getByRole("button", { name: "Review direct selection" }));
  await user.click(screen.getByRole("button", { name: "Select applicant and finalize opening" }));
  return host;
}

it("freezes the confirmed facts and candidate during permanent selection", async () => {
  const pending = deferred<Response>();
  vi.mocked(api.selectPreviousApplicant).mockReturnValue(pending.promise);
  await beginCreate();
  expect(screen.getByRole("button", { name: "Chosen" })).toBeDisabled();
  expect(props.onSavingChange).toHaveBeenLastCalledWith(true);
  await act(async () => pending.resolve(Response.json({ openings: [] })));
  expect(props.onCreated).toHaveBeenCalledWith([], applicant);
  expect(props.onSavingChange).toHaveBeenLastCalledWith(false);
});

it.each([new Response("{", { status: 200 }), new Response("", { status: 503 }), Response.json({})])(
  "reconciles an uncertain decision in the background and prevents an immediate repeat", async (response) => {
    const refresh = deferred<void>();
    props.onUnconfirmed.mockReturnValue(refresh.promise);
    api.selectPreviousApplicant.mockResolvedValue(response);
    await beginCreate();
    expect(props.onError).toHaveBeenCalledWith(expect.stringContaining("may already be saved"));
    expect(props.onUnconfirmed).toHaveBeenCalledOnce();
    expect(props.onCreated).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Review direct selection" })).toBeNull();
    const review = screen.getByRole("button", { name: "Review openings" });
    expect(review).toBeEnabled();
    fireEvent.click(review);
    expect(props.onCancel).toHaveBeenCalledOnce();
    await act(async () => refresh.resolve());
  },
);

it("keeps a definite validation refusal editable without reconciling a permanent decision", async () => {
  api.selectPreviousApplicant.mockResolvedValue(Response.json({ detail: "Invalid move-in date" }, { status: 422 }));
  await beginCreate();
  expect(props.onError).toHaveBeenCalledWith("Invalid move-in date");
  expect(props.onUnconfirmed).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Review direct selection" })).toBeEnabled();
});

it("does not finish a selection into a closed workflow", async () => {
  const pending = deferred<Response>();
  vi.mocked(api.selectPreviousApplicant).mockReturnValue(pending.promise);
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
