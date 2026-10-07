import { act, fireEvent, screen, within } from "@testing-library/react";
import { renderCommittee as render, deferred } from "../../testSupport";
import { beforeEach, expect, it, vi } from "vitest";
import { FeedbackPanel } from "./FeedbackPanel";

const api = vi.hoisted(() => ({
  fetchFeedback: vi.fn<ReturnType<typeof import("../../api/feedback").createApi>["fetchFeedback"]>(),
  resolveFeedback: vi.fn<ReturnType<typeof import("../../api/feedback").createApi>["resolveFeedback"]>(),
  reopenFeedback: vi.fn<ReturnType<typeof import("../../api/feedback").createApi>["reopenFeedback"]>(),
}));

vi.mock("../../api/feedback", () => ({
  createApi: () => api,
}));
const items = [1, 2].map((id) => ({ id, body: `Synthetic feedback ${id}`, userEmail: "member@example.com",
  userName: "Synthetic member", route: null, activeTab: null, analysisId: null, applicantId: null, openingId: null, retainedReview: false,
  applicantName: null, appVersion: "test", createdAt: "2026-10-03T00:00:00Z", resolvedAt: null }));
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.fetchFeedback).mockResolvedValue(items);
});

it("keeps each pending row busy independently and releases a failed row", async () => {
  const first = deferred<Response>();
  const second = deferred<Response>();
  vi.mocked(api.resolveFeedback).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  const onError = vi.fn();
  render(<FeedbackPanel onError={onError} onOpenApplicant={vi.fn()} onOpenView={vi.fn()} />);
  await screen.findByText("Synthetic feedback 1");
  const buttons = screen.getAllByRole("button", { name: "Mark resolved" });
  fireEvent.click(buttons[0]);
  fireEvent.click(buttons[1]);
  fireEvent.click(buttons[1]);
  expect(api.resolveFeedback).toHaveBeenCalledTimes(2);
  await act(async () => { first.resolve(new Response(null, { status: 200 })); });
  const row = screen.getByText("Synthetic feedback 2").closest("li")!;
  expect(within(row).getByRole("button", { name: "Mark resolved" })).toBeDisabled();
  await act(async () => { second.reject(new Error("Synthetic failure")); });
  expect(onError).toHaveBeenCalledOnce();
  expect(within(row).getByRole("button", { name: "Mark resolved" })).toBeEnabled();
});


it.each([false, true])("passes the reported applicant context to navigation (retained=%s)", async (retainedReview) => {
  api.fetchFeedback.mockResolvedValue([{ ...items[0], applicantId: 7, applicantName: "Synthetic applicant",
    openingId: retainedReview ? null : 12, retainedReview }]);
  const onOpenApplicant = vi.fn();
  render(<FeedbackPanel onError={vi.fn()} onOpenApplicant={onOpenApplicant} onOpenView={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Synthetic applicant" }));
  expect(onOpenApplicant).toHaveBeenCalledExactlyOnceWith(7, retainedReview ? null : 12, retainedReview);
});

it("passes the opening for a non-applicant context link", async () => {
  api.fetchFeedback.mockResolvedValue([{ ...items[0], activeTab: "ranking", openingId: 12 }]);
  const onOpenView = vi.fn();
  render(<FeedbackPanel onError={vi.fn()} onOpenApplicant={vi.fn()} onOpenView={onOpenView} />);
  fireEvent.click(await screen.findByRole("button", { name: "Ranking" }));
  expect(onOpenView).toHaveBeenCalledExactlyOnceWith("ranking", 12);
});
