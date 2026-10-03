import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../../api/openings";
import type { Opening, OpeningPreview, OpeningSelection } from "../../types";
import { deferred } from "../../testSupport";
import { OpeningsPanel } from "./OpeningsPanel";

vi.mock("../../api/openings", () => ({
  fetchOpenings: vi.fn(),
  fetchOpeningSelection: vi.fn(),
  confirmOpeningSelection: vi.fn(),
  previewOpening: vi.fn(),
  createOpening: vi.fn(),
  updateOpening: vi.fn(),
  confirmNoHouseholdSelected: vi.fn(),
}));

vi.mock("./DirectSelectionOpeningForm", () => ({
  DirectSelectionOpeningForm: (props: { onCancel: () => void }) => (
    <section>
      <h4>Direct selection</h4>
      <button type="button" onClick={props.onCancel}>Cancel direct selection</button>
    </section>
  ),
}));

const props = {
  onError: vi.fn(),
  onPoolChanged: vi.fn(),
  onOpenApplicant: vi.fn(),
  onOpenRetainedApplicant: vi.fn(),
};

const closedOpening: Opening = {
  id: 7,
  intakeMode: "applications",
  unitSizeBedrooms: 2,
  housingChargeCents: 150_000,
  applicationOpenDate: "2026-07-01",
  applicationCloseDate: "2026-08-01",
  moveInDate: "2026-09-01",
  phase: "closed",
  publishedAt: "2026-07-01T12:00:00Z",
  submissionCount: 3,
  selectedApplicationId: null,
  selectedApplicantName: null,
  noHouseholdSelected: false,
  needsDecision: true,
  createdAt: "2026-06-01T12:00:00Z",
  updatedAt: "2026-08-01T12:00:00Z",
};

const preview: OpeningPreview = {
  audienceCount: 2,
  subscriberOnlyCount: 2,
  applicationOnlyCount: 0,
  overlapCount: 0,
  variants: [{ kind: "notification_list", recipientCount: 2 }],
  socketlabs: {
    available: false, retrievedAt: null, billingPeriodStart: null, billingPeriodEnd: null,
    messagesUsed: null, messageAllowance: null, messagesUsedPercent: null,
    allowOverages: null, projectedMessagesUsed: null,
  },
};

const selection: OpeningSelection = {
  openingId: 7,
  intakeMode: "applications",
  phase: "closed",
  selectedApplicationId: null,
  selectedApplicantName: null,
  noHouseholdSelected: false,
  activeParticipantCount: 3,
  candidates: [
    { applicationId: 1, applicantName: "Jordan Patel", primaryEmail: "jordan@example.com" },
    { applicationId: 2, applicantName: "Casey Singh", primaryEmail: "casey@example.com" },
    { applicationId: 3, applicantName: "Riley Chen", primaryEmail: "riley@example.com" },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.fetchOpenings).mockResolvedValue([]);
});

describe("OpeningsPanel modes", () => {
  it("uses the same busy flag for a workflow and the opening list", async () => {
    vi.mocked(api.fetchOpenings).mockResolvedValue([closedOpening]);
    const pending = deferred<OpeningPreview>();
    vi.mocked(api.previewOpening).mockReturnValueOnce(pending.promise);
    const user = userEvent.setup();
    render(<OpeningsPanel {...props} />);
    await user.click(await screen.findByRole("button", { name: "New opening" }));
    fireEvent.change(screen.getByLabelText("Applications close"), { target: { value: "2026-11-01" } });
    fireEvent.change(screen.getByLabelText("Move-in date"), { target: { value: "2026-12-01" } });
    await user.click(screen.getByRole("button", { name: "Review opening and emails" }));
    expect(screen.getByRole("button", { name: "Working…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Edit" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Record decision" })).toBeDisabled();

    await act(async () => pending.reject(new Error("Preview unavailable")));
    expect(screen.getByRole("button", { name: "Review opening and emails" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Edit" })).toBeEnabled();
    expect(props.onError).toHaveBeenCalledWith("Could not preview the opening and notification audience.");
  });

  it("does not restore an outdated audience confirmation when the draft changes during preview", async () => {
    const pending = deferred<OpeningPreview>();
    vi.mocked(api.previewOpening).mockReturnValueOnce(pending.promise);
    const user = userEvent.setup();
    render(<OpeningsPanel {...props} />);
    await user.click(await screen.findByRole("button", { name: "New opening" }));
    fireEvent.change(screen.getByLabelText("Applications close"), { target: { value: "2026-11-01" } });
    fireEvent.change(screen.getByLabelText("Move-in date"), { target: { value: "2026-12-01" } });
    await user.click(screen.getByRole("button", { name: "Review opening and emails" }));
    fireEvent.change(screen.getByLabelText("Unit size"), { target: { value: "3" } });
    await act(async () => pending.resolve(preview));

    expect(screen.getByLabelText("Unit size")).toHaveValue("3");
    expect(screen.queryByText("Ready to open applications")).toBeNull();
    expect(screen.getByRole("button", { name: "Review opening and emails" })).toBeEnabled();
    expect(api.createOpening).not.toHaveBeenCalled();
  });

  it("requires confirmation before recording that no household was selected", async () => {
    vi.mocked(api.fetchOpenings).mockResolvedValueOnce([closedOpening]).mockResolvedValueOnce([]);
    vi.mocked(api.fetchOpeningSelection).mockResolvedValue(selection);
    vi.mocked(api.confirmNoHouseholdSelected).mockResolvedValue(Response.json({ openings: [], queuedNotificationCount: 0 }));
    const user = userEvent.setup();
    render(<OpeningsPanel {...props} />);
    await user.click(await screen.findByRole("button", { name: "Record decision" }));
    await user.click(screen.getByRole("button", { name: "No household selected" }));
    expect(screen.getByRole("heading", { name: "Confirm no household selected" })).toBeInTheDocument();
    expect(api.confirmNoHouseholdSelected).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Confirm decision" }));
    expect(await screen.findByText("Opening decision recorded. No new outcome emails were needed. Check Email delivery for existing deliveries.")).toBeInTheDocument();
    expect(api.confirmNoHouseholdSelected).toHaveBeenCalledWith(7);
    expect(api.confirmOpeningSelection).not.toHaveBeenCalled();
    expect(props.onPoolChanged).toHaveBeenCalledOnce();
  });

  it("requires a fresh audience review after an opening draft changes", async () => {
    vi.mocked(api.previewOpening).mockResolvedValue(preview);
    vi.mocked(api.createOpening).mockResolvedValue(Response.json({
      openings: [closedOpening], queuedNotificationCount: 2,
    }));
    const user = userEvent.setup();
    render(<OpeningsPanel {...props} />);
    await user.click(await screen.findByRole("button", { name: "New opening" }));
    fireEvent.change(screen.getByLabelText("Applications close"), { target: { value: "2026-11-01" } });
    fireEvent.change(screen.getByLabelText("Move-in date"), { target: { value: "2026-12-01" } });
    await user.click(screen.getByRole("button", { name: "Review opening and emails" }));
    expect(await screen.findByText("Ready to open applications")).toBeInTheDocument();
    expect(api.createOpening).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Unit size"), { target: { value: "3" } });
    expect(screen.queryByText("Ready to open applications")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Review opening and emails" }));
    await user.click(await screen.findByRole("button", { name: "Open applications and queue 2 emails" }));
    expect(api.createOpening).toHaveBeenCalledWith(expect.objectContaining({ unitSizeBedrooms: 3 }), 2);
    expect(await screen.findByText("Applications are open and 2 emails are queued.")).toBeInTheDocument();
  });

  it("updates an existing opening without publishing or reviewing an audience", async () => {
    vi.mocked(api.fetchOpenings).mockResolvedValue([closedOpening]);
    vi.mocked(api.updateOpening).mockResolvedValue(Response.json({ openings: [closedOpening], saved: { ...closedOpening, moveInDate: "2026-10-01" } }));
    const user = userEvent.setup();
    render(<OpeningsPanel {...props} />);
    await user.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText("Move-in date"), { target: { value: "2026-10-01" } });
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Opening updated.")).toBeInTheDocument();
    expect(api.updateOpening).toHaveBeenCalledWith(7, expect.objectContaining({ moveInDate: "2026-09-01" }), expect.objectContaining({ moveInDate: "2026-10-01" }));
    expect(api.previewOpening).not.toHaveBeenCalled();
    expect(api.createOpening).not.toHaveBeenCalled();
  });

  it("enters and leaves the new-opening form as one exclusive mode", async () => {
    const user = userEvent.setup();
    render(<OpeningsPanel {...props} />);

    await user.click(await screen.findByRole("button", { name: "New opening" }));
    expect(screen.getByRole("heading", { name: "New opening" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Fill from previous applicants" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "New opening" })).toBeInTheDocument();
  });

  it("keeps direct selection mutually exclusive with the opening form", async () => {
    const user = userEvent.setup();
    render(<OpeningsPanel {...props} />);

    await user.click(await screen.findByRole("button", { name: "Fill from previous applicants" }));
    expect(screen.getByRole("heading", { name: "Direct selection" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "New opening" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Cancel direct selection" }));
    expect(screen.getByRole("button", { name: "New opening" })).toBeInTheDocument();
  });

  it("shows a finalized selection as an ordinary fact without decision management", async () => {
    vi.mocked(api.fetchOpenings).mockResolvedValueOnce([{
      ...closedOpening,
      phase: "archived",
      selectedApplicationId: 1,
      selectedApplicantName: "Jordan Patel",
      needsDecision: false,
    }]);
    render(<OpeningsPanel {...props} />);

    expect(await screen.findByText("Selected applicant")).toBeInTheDocument();
    expect(screen.getByText("Jordan Patel")).toBeInTheDocument();
    expect(screen.queryByText("Permanent")).toBeNull();
    expect(screen.queryByRole("button", { name: "Manage decision" })).toBeNull();
    expect(screen.getByRole("button", { name: "Review application" })).toBeInTheDocument();
  });

  it("releases decision controls on the committed response without an extra openings read", async () => {
    const pending = deferred<Response>();
    vi.mocked(api.fetchOpenings).mockResolvedValue([closedOpening]);
    vi.mocked(api.fetchOpeningSelection).mockResolvedValue(selection);
    vi.mocked(api.confirmOpeningSelection).mockReturnValue(pending.promise);
    const user = userEvent.setup();
    render(<OpeningsPanel {...props} />);
    await user.click(await screen.findByRole("button", { name: "Record decision" }));
    await user.click(screen.getAllByRole("button", { name: "Select" })[0]);
    await user.click(screen.getByRole("button", { name: "Confirm selection" }));
    expect(screen.getByRole("button", { name: "Saving decision…" })).toBeDisabled();
    await act(async () => { pending.resolve(Response.json({ openings: [{ ...closedOpening, phase: "archived", selectedApplicationId: 1,
      selectedApplicantName: "Jordan Patel", needsDecision: false }], queuedNotificationCount: 2 })); });
    expect(screen.getByText("Successful applicant selected. 2 outcome emails are queued. Check Email delivery for status.")).toBeInTheDocument();
    expect(api.fetchOpenings).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Edit" })).toBeEnabled();
    expect(props.onPoolChanged).toHaveBeenCalledOnce();
  });
});
