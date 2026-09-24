import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../../api/openings";
import type { Opening, OpeningSelection } from "../../types";
import { OpeningsPanel } from "./OpeningsPanel";

vi.mock("../../api/openings", () => ({
  fetchOpenings: vi.fn(),
  fetchOpeningSelection: vi.fn(),
  confirmOpeningSelection: vi.fn(),
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

  it("shows provider-backed progress while finalizing an opening", async () => {
    const encoder = new TextEncoder();
    let streamController!: ReadableStreamDefaultController<Uint8Array>;
    const response = new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        streamController = controller;
      },
    }), { status: 200 });
    vi.mocked(api.fetchOpenings)
      .mockResolvedValueOnce([closedOpening])
      .mockResolvedValueOnce([{
        ...closedOpening,
        phase: "archived",
        selectedApplicationId: 1,
        selectedApplicantName: "Jordan Patel",
        needsDecision: false,
      }]);
    vi.mocked(api.fetchOpeningSelection).mockResolvedValue(selection);
    vi.mocked(api.confirmOpeningSelection).mockResolvedValue(response);
    const user = userEvent.setup();
    render(<OpeningsPanel {...props} />);

    await user.click(await screen.findByRole("button", { name: "Record decision" }));
    await user.click(screen.getAllByRole("button", { name: "Select" })[0]);
    await user.click(screen.getByRole("button", { name: "Confirm selection" }));
    expect(screen.getByText("Preparing outcome emails…")).toBeInTheDocument();

    streamController.enqueue(encoder.encode(
      `${JSON.stringify({ type: "progress", processed: 0, total: 2, sent: 0 })}\n`,
    ));
    expect(await screen.findByText("0 sent · 0 of 2 processed (0%)")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Outcome email progress" }))
      .toHaveAttribute("max", "2");
    streamController.enqueue(encoder.encode(
      `${JSON.stringify({ type: "progress", processed: 2, total: 2, sent: 2 })}\n`,
    ));
    expect(await screen.findByText("2 sent · 2 of 2 processed (100%)")).toBeInTheDocument();
    streamController.enqueue(encoder.encode(
      `${JSON.stringify({
        type: "summary",
        sent: 2,
        total: 2,
        selection: {
          ...selection,
          phase: "archived",
          selectedApplicationId: 1,
          selectedApplicantName: "Jordan Patel",
          candidates: selection.candidates.slice(1),
        },
      })}\n`,
    ));
    streamController.close();

    expect(await screen.findByText(
      "Successful applicant selected. 2 outcome emails were sent.",
    )).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Manage decision" })).toBeNull();
  });
});
