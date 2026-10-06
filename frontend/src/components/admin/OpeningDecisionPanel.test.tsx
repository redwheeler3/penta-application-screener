import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { renderCommittee as render, deferred } from "../../testSupport";
import { OpeningDecisionPanel } from "./OpeningDecisionPanel";
import type { OpeningSelection } from "../../types";

const api = vi.hoisted(() => ({ confirmNoHouseholdSelected: vi.fn() }));
vi.mock("../../api/openings", () => ({ createApi: () => api }));
const selection: OpeningSelection = {
  openingId: 1, intakeMode: "applications", phase: "closed", selectedApplicationId: null,
  selectedApplicantName: null, noHouseholdSelected: false, activeParticipantCount: 2, candidates: [],
};
const props = { selection, busy: false, setBusy: vi.fn(), onSaved: vi.fn(), onError: vi.fn(),
  onReview: vi.fn(), onClose: vi.fn(), onUnconfirmed: vi.fn<() => Promise<void>>() };
beforeEach(() => { vi.resetAllMocks(); props.onUnconfirmed.mockResolvedValue(); });

it.each([new Response("", { status: 503 }), new Response("{", { status: 200 }), Response.json({})])(
  "reconciles an unconfirmed permanent decision without waiting or offering another choice", async (response) => {
    const refresh = deferred<void>();
    props.onUnconfirmed.mockReturnValue(refresh.promise);
    api.confirmNoHouseholdSelected.mockResolvedValue(response);
    render(<OpeningDecisionPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "No household selected" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm decision" }));
    fireEvent.click(await screen.findByRole("button", { name: "Review openings" }));
    expect(props.onUnconfirmed).toHaveBeenCalledOnce();
    expect(props.onClose).toHaveBeenCalledOnce();
    expect(props.onSaved).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Confirm decision" })).toBeNull();
    refresh.resolve();
  },
);

it("keeps a definite refusal editable", async () => {
  api.confirmNoHouseholdSelected.mockResolvedValue(Response.json({ detail: "Not closed" }, { status: 409 }));
  render(<OpeningDecisionPanel {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "No household selected" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm decision" }));
  await vi.waitFor(() => expect(props.onError).toHaveBeenCalledWith("Not closed"));
  expect(props.onUnconfirmed).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Back" })).toBeEnabled();
});
