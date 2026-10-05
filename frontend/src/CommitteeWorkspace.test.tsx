import { act, fireEvent, screen } from "@testing-library/react";
import { renderCommittee as render, deferred } from "./testSupport";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CommitteeWorkspace } from "./CommitteeWorkspace";
import type { CandidateDetail } from "./components/applications/CandidateDetail";
import type { CurrentUser, SettingsResponse } from "./types";

const applicationApi = vi.hoisted(() => ({
  fetchApplication: vi.fn<ReturnType<typeof import("./api/applications").createApi>["fetchApplication"]>(),
  savePrivateNote: vi.fn<ReturnType<typeof import("./api/applications").createApi>["savePrivateNote"]>(),
}));
const settingsApi = vi.hoisted(() => ({
  fetchSettings: vi.fn<ReturnType<typeof import("./api/settings").createApi>["fetchSettings"]>(),
  saveSettings: vi.fn<ReturnType<typeof import("./api/settings").createApi>["saveSettings"]>(),
}));

vi.mock("./api/cachedResults", () => ({ createApi: () => ({ refreshCachedResults: vi.fn().mockResolvedValue(false) }) }));

// Keep the real navigation, settings, note writer, admin section chooser, and
// configuration form. Unrelated resources have their own suites and no I/O here.
vi.mock("./api/settings", () => ({
  createApi: () => settingsApi,
}));
vi.mock("./api/applications", () => ({
  createApi: () => applicationApi,
}));
vi.mock("./hooks/useApplications", () => ({ useApplications: () => ({
  applications: [], openings: [], selectedOpeningId: 1, applicationsLoadState: "ready",
  reloadApplications: vi.fn().mockResolvedValue(undefined), loadInitialApplications: vi.fn(), selectOpening: vi.fn(),
}) }));
vi.mock("./hooks/useDashboard", () => ({ useDashboard: () => ({
  loadState: "ready", refresh: vi.fn().mockResolvedValue(undefined), loadInitial: vi.fn(),
}) }));
vi.mock("./hooks/useRanking", () => ({ useRanking: () => ({
  rankingRun: null, ranking: null, refreshRankingRun: vi.fn().mockResolvedValue({ status: "loaded", run: null }), checkForStaleRanking: vi.fn(),
}) }));
vi.mock("./hooks/useAiRuns", () => ({ useAiRuns: () => ({ resetEstimates: vi.fn() }) }));
vi.mock("./components/workflow/WorkflowBar", () => ({ WorkflowBar: () => null }));
vi.mock("./components/applications/ApplicationsList", () => ({
  ApplicationsList: ({ onSelectApplication }: { onSelectApplication: (id: number) => void }) =>
    <button onClick={() => onSelectApplication(7)}>Open synthetic applicant</button>,
}));
vi.mock("./components/applications/CandidateDetail", async () => {
  const { CandidateNotes } = await import("./components/applications/CandidateNotes");
  return { CandidateDetail: (props: ComponentProps<typeof CandidateDetail>) =>
    <CandidateNotes applicationId={props.app.id} privateNote={props.app.privateNote} committeeNotes={[]}
      privateNoteEditor={props.privateNoteEditor} onAddCommitteeNote={props.onAddCommitteeNote}
      onUpdateCommitteeNote={props.onUpdateCommitteeNote} onDeleteCommitteeNote={props.onDeleteCommitteeNote} /> };
});
vi.mock("./components/admin/OpeningsPanel", () => ({ OpeningsPanel: () => <h3>Openings data</h3> }));
vi.mock("./components/admin/AccessPanel", () => ({ AccessPanel: () => <h3>Access data</h3> }));
vi.mock("./components/admin/VacancyNotificationsPanel", () => ({ VacancyNotificationsPanel: () => <h3>Notifications data</h3> }));
vi.mock("./components/admin/EmailDeliveryPanel", () => ({ EmailDeliveryPanel: () => <h3>Email Delivery data</h3> }));
vi.mock("./components/admin/FeedbackPanel", () => ({ FeedbackPanel: () => <h3>Feedback data</h3> }));

const user: CurrentUser = { id: 1, email: "synthetic@example.com", displayName: "Synthetic",
  avatarUrl: null, role: "admin" };
const configuration: SettingsResponse = { settings: { ai: {
  region: "test", screeningModel: "test", screeningReasoningEffort: "none",
  dimensionScoringModel: "test", dimensionScoringReasoningEffort: "none",
  discoveryModel: "test", discoveryReasoningEffort: "none",
  decomposeModel: "test", decomposeReasoningEffort: "none",
  matchModel: "test", matchReasoningEffort: "none",
  consolidateModel: "test", consolidateReasoningEffort: "none",
  discoveryFanOut: 5, consolidateCorrelationThreshold: 0.9, spendingCapUsd: 10, maxWorkers: 3,
} }, aiPasses: [], aiModelOptions: [] };

beforeEach(() => {
  vi.useFakeTimers();
  vi.resetAllMocks();
  vi.mocked(settingsApi.fetchSettings).mockReturnValue(deferred<SettingsResponse>().promise);
  vi.mocked(applicationApi.fetchApplication).mockResolvedValue({ id: 7, privateNote: "Saved" } as Awaited<ReturnType<typeof applicationApi.fetchApplication>>);
  vi.mocked(applicationApi.savePrivateNote).mockResolvedValue(new Response(null));
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

it.each(["pending", "failed"])("keeps every independent admin section available when configuration is %s", async (state) => {
  if (state === "failed") vi.mocked(settingsApi.fetchSettings).mockRejectedValue(new Error("offline"));
  render(<CommitteeWorkspace user={user} logout={vi.fn()} />);
  fireEvent.click(screen.getByRole("tab", { name: "Admin Settings" }));
  if (state === "failed") {
    await act(() => vi.advanceTimersByTimeAsync(20_000));
    // Dashboard readiness grants one recovery cycle after the first failure.
    await act(() => vi.advanceTimersByTimeAsync(20_000));
  }
  expect(screen.getByRole("heading", { name: "Configuration" })).toBeInTheDocument();
  expect(screen.getByText(state === "failed" ? "Couldn't load configuration. Please try again." : "Loading configuration…"))
    .toBeInTheDocument();
  for (const section of ["Openings", "Notifications", "Email Delivery", "Access", "Feedback"]) {
    fireEvent.click(screen.getByRole("tab", { name: section }));
    expect(screen.getByRole("heading", { name: `${section} data` })).toBeInTheDocument();
    expect(screen.queryByText(/load configuration|Loading configuration/)).toBeNull();
  }
  fireEvent.click(screen.getByRole("tab", { name: "Configuration" }));
  if (state === "failed") {
    vi.mocked(settingsApi.fetchSettings).mockResolvedValue(configuration);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Retry" })));
    expect(screen.getByRole("button", { name: "Save configuration" })).toBeInTheDocument();
    const cap = screen.getByRole("textbox", { name: /Spending cap \(USD per run\)/ });
    fireEvent.change(cap, { target: { value: "18" } });
    fireEvent.click(screen.getByRole("tab", { name: "Openings" }));
    fireEvent.click(screen.getByRole("tab", { name: "Configuration" }));
    expect(screen.getByRole("textbox", { name: /Spending cap \(USD per run\)/ })).toHaveValue("18");
  }
});

it("keeps admin sections unavailable to a committee member", () => {
  render(<CommitteeWorkspace user={{ ...user, role: "member" }} logout={vi.fn()} />);
  expect(screen.queryByRole("tab", { name: "Admin Settings" })).toBeNull();
  expect(screen.queryByRole("tab", { name: "Openings" })).toBeNull();
});

it("lets a member cancel sign-out while a private note is unconfirmed", async () => {
  const logout = vi.fn().mockResolvedValue(null);
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<CommitteeWorkspace user={user} logout={logout} />);
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Open synthetic applicant" })));
  fireEvent.change(screen.getByRole("textbox", { name: "My private notes" }), { target: { value: "Unsaved" } });
  fireEvent.click(screen.getByRole("button", { name: /Sign out/ }));
  expect(confirm).toHaveBeenCalledOnce();
  expect(logout).not.toHaveBeenCalled();
  expect(screen.getByRole("textbox", { name: "My private notes" })).toHaveValue("Unsaved");
  await act(() => vi.advanceTimersByTimeAsync(600));
  expect(applicationApi.savePrivateNote).toHaveBeenCalledExactlyOnceWith(7, 1, "Unsaved");
});

it("resumes note saving if an explicitly confirmed sign-out fails", async () => {
  const logout = vi.fn().mockResolvedValue("Could not sign out.");
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<CommitteeWorkspace user={user} logout={logout} />);
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Open synthetic applicant" })));
  fireEvent.change(screen.getByRole("textbox", { name: "My private notes" }), { target: { value: "Unsaved" } });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: /Sign out/ })));
  expect(logout).toHaveBeenCalledOnce();
  expect(applicationApi.savePrivateNote).toHaveBeenCalledExactlyOnceWith(7, 1, "Unsaved");
  expect(screen.getByText("Could not sign out.")).toBeInTheDocument();
});

it("pauses session-changed work and preserves private notes until explicit continuation", async () => {
  const onContinueSession = vi.fn().mockResolvedValue(undefined);
  vi.spyOn(window, "confirm").mockReturnValue(false);
  const clipboard = { writeText: vi.fn().mockResolvedValue(undefined) };
  const descriptor = Object.getOwnPropertyDescriptor(navigator, "clipboard");
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: clipboard });
  try {
    const { rerender } = render(<CommitteeWorkspace user={user} logout={vi.fn()} onContinueSession={onContinueSession} />);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Open synthetic applicant" })));
    fireEvent.change(screen.getByRole("textbox", { name: "My private notes" }), { target: { value: "Unsaved personal draft" } });
    rerender(<CommitteeWorkspace user={user} logout={vi.fn()} sessionChanged onContinueSession={onContinueSession} />);
    await act(() => vi.advanceTimersByTimeAsync(600));
    expect(applicationApi.savePrivateNote).not.toHaveBeenCalled();
    expect(document.querySelector("main")?.hasAttribute("inert")).toBe(true);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Copy unsaved private notes" })));
    expect(clipboard.writeText).toHaveBeenCalledWith("Applicant 7\nUnsaved personal draft");
    fireEvent.click(screen.getByRole("button", { name: "Continue with current session" }));
    expect(onContinueSession).not.toHaveBeenCalled();
  } finally {
    if (descriptor) Object.defineProperty(navigator, "clipboard", descriptor);
    else Reflect.deleteProperty(navigator, "clipboard");
  }
});
