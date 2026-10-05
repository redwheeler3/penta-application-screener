import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import * as applicationApi from "./api/applications";
import * as settingsApi from "./api/settings";
import { CommitteeWorkspace } from "./CommitteeWorkspace";
import type { CandidateDetail } from "./components/applications/CandidateDetail";
import { deferred } from "./testSupport";
import type { CurrentUser, SettingsResponse } from "./types";

// Keep the real navigation, settings, note writer, admin section chooser, and
// configuration form. Unrelated resources have their own suites and no I/O here.
vi.mock("./api/settings", () => ({ fetchSettings: vi.fn(), saveSettings: vi.fn() }));
vi.mock("./api/applications", () => ({ fetchApplication: vi.fn(), savePrivateNote: vi.fn() }));
vi.mock("./hooks/useApplications", () => ({ useApplications: () => ({
  applications: [], openings: [], selectedOpeningId: 1, applicationsLoadState: "ready",
  reloadApplications: vi.fn().mockResolvedValue(undefined), loadInitialApplications: vi.fn(), selectOpening: vi.fn(),
}) }));
vi.mock("./hooks/useDashboard", () => ({ useDashboard: () => ({
  loadState: "ready", refresh: vi.fn().mockResolvedValue(undefined), loadInitial: vi.fn(),
}) }));
vi.mock("./hooks/useRanking", () => ({ useRanking: () => ({
  rankingRun: null, ranking: null, refreshRankingRun: vi.fn().mockResolvedValue(null), checkForStaleRanking: vi.fn(),
}) }));
vi.mock("./hooks/useAiRuns", () => ({ useAiRuns: () => ({ resetEstimates: vi.fn() }) }));
vi.mock("./components/workflow/WorkflowBar", () => ({ WorkflowBar: () => null }));
vi.mock("./components/applications/ApplicationsList", () => ({
  ApplicationsList: ({ onSelectApplication }: { onSelectApplication: (id: number) => void }) =>
    <button onClick={() => onSelectApplication(7)}>Open synthetic applicant</button>,
}));
vi.mock("./components/applications/CandidateDetail", () => ({
  CandidateDetail: ({ privateNoteEditor }: ComponentProps<typeof CandidateDetail>) =>
    <textarea aria-label="Private note" value={privateNoteEditor?.body ?? ""}
      onChange={(event) => privateNoteEditor?.change(event.target.value)} />,
}));
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
  fireEvent.change(screen.getByRole("textbox", { name: "Private note" }), { target: { value: "Unsaved" } });
  fireEvent.click(screen.getByRole("button", { name: /Sign out/ }));
  expect(confirm).toHaveBeenCalledOnce();
  expect(logout).not.toHaveBeenCalled();
  expect(screen.getByRole("textbox", { name: "Private note" })).toHaveValue("Unsaved");
  await act(() => vi.advanceTimersByTimeAsync(600));
  expect(applicationApi.savePrivateNote).toHaveBeenCalledExactlyOnceWith(7, 1, "Unsaved");
});

it("resumes note saving if an explicitly confirmed sign-out fails", async () => {
  const logout = vi.fn().mockResolvedValue("Could not sign out.");
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<CommitteeWorkspace user={user} logout={logout} />);
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Open synthetic applicant" })));
  fireEvent.change(screen.getByRole("textbox", { name: "Private note" }), { target: { value: "Unsaved" } });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: /Sign out/ })));
  expect(logout).toHaveBeenCalledOnce();
  expect(applicationApi.savePrivateNote).toHaveBeenCalledExactlyOnceWith(7, 1, "Unsaved");
  expect(screen.getByText("Could not sign out.")).toBeInTheDocument();
});
