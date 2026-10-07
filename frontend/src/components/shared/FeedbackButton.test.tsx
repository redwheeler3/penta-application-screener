import { act, fireEvent, screen } from "@testing-library/react";
import { renderCommittee as render, deferred } from "../../testSupport";
import { beforeEach, expect, it, vi } from "vitest";
import { FeedbackButton } from "./FeedbackButton";

const api = vi.hoisted(() => ({
  submitFeedback: vi.fn<ReturnType<typeof import("../../api/feedback").createApi>["submitFeedback"]>(),
}));

vi.mock("../../api/feedback", () => ({
  createApi: () => api,
}));
function setup() {
  const onToast = vi.fn();
  const onError = vi.fn();
  render(<FeedbackButton activeTab="ranking" analysisId={1} applicantId={null} openingId={null} retainedReview={false} onToast={onToast} onError={onError} />);
  fireEvent.click(screen.getByRole("button", { name: "Feedback" }));
  return { onToast, onError };
}
beforeEach(() => vi.resetAllMocks());

it("retains newer feedback typed while an earlier submission is pending", async () => {
  const pending = deferred<Response>();
  vi.mocked(api.submitFeedback).mockReturnValue(pending.promise);
  const { onToast } = setup();
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "Submitted draft" } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "Newer draft" } });
  await act(async () => { pending.resolve(new Response(null, { status: 201 })); });
  expect(screen.getByRole("textbox")).toHaveValue("Newer draft");
  expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
  expect(onToast).toHaveBeenCalledWith("Feedback sent. Your newer text hasn’t been sent yet.");
});

it("releases a failed submission and leaves its draft available for retry", async () => {
  vi.mocked(api.submitFeedback).mockRejectedValue(new Error("Synthetic failure"));
  const { onError } = setup();
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "Keep this feedback" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Send" })); });
  expect(onError).toHaveBeenCalledOnce();
  expect(screen.getByRole("textbox")).toHaveValue("Keep this feedback");
  expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
});

it("does not close or release a new composer when a cancelled submission finishes", async () => {
  const first = deferred<Response>();
  const second = deferred<Response>();
  vi.mocked(api.submitFeedback).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  setup();
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "Old submission" } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(screen.getByRole("button", { name: "Feedback" }));
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "New submission" } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await act(async () => { first.resolve(new Response(null, { status: 201 })); });
  expect(screen.getByRole("textbox")).toHaveValue("New submission");
  expect(screen.getByRole("button", { name: "Sending" })).toBeDisabled();
  await act(async () => { second.resolve(new Response(null, { status: 201 })); });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
