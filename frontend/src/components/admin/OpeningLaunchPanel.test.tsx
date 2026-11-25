import { act, fireEvent, screen } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { deferred, renderCommittee as render } from "../../testSupport";
import type { Opening, SocketLabsUsage } from "../../types";
import { OpeningLaunchPanel } from "./OpeningLaunchPanel";

const api = vi.hoisted(() => ({ previewOpening: vi.fn(), fetchOpeningEmailUsage: vi.fn(), openApplications: vi.fn() }));
vi.mock("../../api/openings", () => ({ createApi: () => api }));
const opening: Opening = { id: 7, intakeMode: "applications", unitSizeBedrooms: 2, minChildren: 1, maxChildren: null, householdSummary: "One or two adults plus 1 or more children under 18", housingChargeCents: 100000,
  applicationOpenDate: null, applicationCloseDate: "2027-01-01", moveInDate: "2027-02-01", phase: "preparing",
  publishedAt: null, submissionCount: 0, selectedApplicationId: null, selectedApplicantName: null,
  noHouseholdSelected: false, needsDecision: false, createdAt: "2026-11-14", updatedAt: "2026-11-14" };
const props = { opening, onSaved: vi.fn(), onCancel: vi.fn(), onError: vi.fn() };
function Harness() {
  const [busy, setBusy] = useState(false);
  return <OpeningLaunchPanel {...props} busy={busy} setBusy={setBusy} />;
}
beforeEach(() => {
  vi.resetAllMocks();
  api.previewOpening.mockResolvedValue({ audienceCount: 3, subscriberOnlyCount: 3, applicationOnlyCount: 0, overlapCount: 0, variants: [] });
  api.fetchOpeningEmailUsage.mockResolvedValue({ available: false });
});

it("previews the saved opening and allows launch while email usage is pending", async () => {
  const usage = deferred<SocketLabsUsage>();
  api.fetchOpeningEmailUsage.mockReturnValue(usage.promise);
  api.openApplications.mockResolvedValue(Response.json({ openings: [], queuedNotificationCount: 3 }));
  render(<Harness />);
  await screen.findByText("Ready to open applications");
  expect(screen.getByText(/Checking current email usage/)).toBeInTheDocument();
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Open applications and notify applicants" })));
  expect(api.openApplications).toHaveBeenCalledWith(7, expect.objectContaining({ applicationOpenDate: null, applicationCloseDate: "2027-01-01" }), []);
  expect(props.onSaved).toHaveBeenCalledOnce();
});

it("refreshes a changed audience and does not report a failed launch as saved", async () => {
  api.openApplications.mockResolvedValue(Response.json({ code: "opening_audience_changed", detail: "The audience changed." }, { status: 409 }));
  render(<Harness />);
  await screen.findByText("Ready to open applications");
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Open applications and notify applicants" })));
  expect(props.onSaved).not.toHaveBeenCalled();
  expect(props.onError).toHaveBeenCalled();
  expect(api.previewOpening).toHaveBeenCalledTimes(2);
});
