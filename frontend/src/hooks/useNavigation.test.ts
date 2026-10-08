import type { ApplicationsResponse } from "../api/applications";
import { act, waitFor } from "@testing-library/react";
import { renderCommitteeHook as renderHook, deferred } from "../testSupport";
import { beforeEach, expect, it, vi } from "vitest";
import type { ApplicationDetail } from "../types";
import { useNavigation } from "./useNavigation";
import { useApplications } from "./useApplications";

const api = vi.hoisted(() => ({
  fetchApplication: vi.fn<ReturnType<typeof import("../api/applications").createApi>["fetchApplication"]>(),
  fetchRetainedApplication: vi.fn<ReturnType<typeof import("../api/applications").createApi>["fetchRetainedApplication"]>(),
  fetchApplications: vi.fn<ReturnType<typeof import("../api/applications").createApi>["fetchApplications"]>(),
}));

vi.mock("../api/applications", () => ({
  createApi: () => api,
}));

beforeEach(() => {
  vi.resetAllMocks();
  window.localStorage.clear();
});

it("does not reopen an applicant after navigating away from a pending detail request", async () => {
  const response = deferred<ApplicationDetail>();
  vi.mocked(api.fetchApplication).mockReturnValue(response.promise);
  const { result } = renderHook(() => useNavigation({ openingId: 1, selectOpening: vi.fn().mockResolvedValue(true), loadRanking: vi.fn(), onError: vi.fn() }));
  let request!: Promise<void>;
  act(() => { request = result.current.viewApplication(1); });
  act(() => result.current.navigateToView("adminSettings"));
  await act(async () => { response.resolve({ id: 1 } as ApplicationDetail); await request; });
  expect(result.current.selectedApplication).toBeNull();
  expect(result.current.activeTab).toBe("adminSettings");
  expect(window.history.state.applicantId).toBeUndefined();
});

it("confirms note authority only for an accepted fresh detail read", async () => {
  const delayed = deferred<ApplicationDetail>();
  const application = { id: 7, selected: false } as ApplicationDetail;
  api.fetchApplication.mockReturnValueOnce(delayed.promise).mockResolvedValueOnce(application);
  const accepted = vi.fn();
  const { result } = renderHook(() => useNavigation({ openingId: 1, selectOpening: vi.fn().mockResolvedValue(true),
    loadRanking: vi.fn(), onError: vi.fn(), onApplicationLoaded: accepted }));
  let old!: Promise<void>;
  act(() => { old = result.current.viewApplication(7); });
  act(() => result.current.navigateToView("applications"));
  await act(async () => { delayed.resolve(application); await old; });
  expect(accepted).not.toHaveBeenCalled();
  await act(() => result.current.viewApplication(7));
  expect(accepted).toHaveBeenCalledExactlyOnceWith(application, 1, false);
  act(() => result.current.updateSelectedApplication({ id: 7, privateNote: "Save receipt" }));
  expect(accepted).toHaveBeenCalledOnce();
});

it("refreshes displayed evidence in place and retains acknowledgements received during the read", async () => {
  const original = { ...detail(7), normalized: { household_income: 80000 }, privateNote: "Original" };
  const reply = deferred<ApplicationDetail>();
  api.fetchApplication.mockResolvedValueOnce(original).mockReturnValueOnce(reply.promise);
  const accepted = vi.fn();
  const { result } = renderHook(() => useNavigation({ openingId: 1, selectOpening: vi.fn(),
    loadRanking: vi.fn(), onError: vi.fn(), onApplicationLoaded: accepted }));
  await act(() => result.current.viewApplication(7));
  let reading!: Promise<void>;
  act(() => { reading = result.current.refreshApplication(7, 1); });
  expect(result.current.selectedApplication).toEqual(original);
  act(() => result.current.updateSelectedApplication({ id: 7, privateNote: "New saved note" }, 1));
  await act(async () => { reply.resolve({ ...original, normalized: { household_income: 100 } }); await reading; });
  expect(result.current.selectedApplication?.normalized.household_income).toBe(100);
  expect(result.current.selectedApplication?.privateNote).toBe("New saved note");
  expect(accepted).toHaveBeenCalledTimes(2);
});

it("fences background evidence refresh when the member navigates away", async () => {
  const reply = deferred<ApplicationDetail>();
  api.fetchApplication.mockResolvedValueOnce({ id: 7 } as ApplicationDetail).mockReturnValueOnce(reply.promise);
  const accepted = vi.fn();
  const { result } = renderHook(() => useNavigation({ openingId: 1, selectOpening: vi.fn(),
    loadRanking: vi.fn(), onError: vi.fn(), onApplicationLoaded: accepted }));
  await act(() => result.current.viewApplication(7));
  let reading!: Promise<void>;
  act(() => { reading = result.current.refreshApplication(7, 1); });
  act(() => result.current.navigateToView("adminSettings"));
  await act(async () => { reply.resolve({ id: 7 } as ApplicationDetail); await reading; });
  expect(result.current.selectedApplication).toBeNull();
  expect(result.current.activeTab).toBe("adminSettings");
  expect(accepted).toHaveBeenCalledOnce();
});

it("retains the saved decision and older evidence when background refresh fails", async () => {
  const original = { id: 7, status: "eligible", statusSource: "human", stale: true } as ApplicationDetail;
  api.fetchApplication.mockResolvedValueOnce(original).mockRejectedValueOnce(new Error("Synthetic timeout"));
  const onError = vi.fn();
  const { result } = renderHook(() => useNavigation({ openingId: 1, selectOpening: vi.fn(), loadRanking: vi.fn(), onError }));
  await act(() => result.current.viewApplication(7));
  await act(() => result.current.refreshApplication(7, 1));
  expect(result.current.selectedApplication).toEqual(original);
  expect(onError).toHaveBeenCalledWith(expect.stringContaining("Your decision is saved"));
});

it("preserves a deliberate cross-opening detail request as React renders the selected opening", async () => {
  const response = deferred<ApplicationDetail>();
  vi.mocked(api.fetchApplication).mockReturnValue(response.promise);
  const { result, rerender } = renderHook(({ openingId }) => useNavigation({
    openingId, selectOpening: vi.fn().mockResolvedValue(true), loadRanking: vi.fn(), onError: vi.fn(),
  }), { initialProps: { openingId: 1 } });
  let request!: Promise<void>;
  act(() => { request = result.current.viewApplication(7, 2); });
  rerender({ openingId: 2 });
  await act(async () => { response.resolve({ id: 7 } as ApplicationDetail); await request; });
  expect(result.current.selectedApplication?.id).toBe(7);
});

it("does not cancel navigation when an earlier applicant's note acknowledgement arrives", async () => {
  const response = deferred<ApplicationDetail>();
  vi.mocked(api.fetchApplication).mockResolvedValueOnce({ id: 7, privateNote: "Original" } as ApplicationDetail)
    .mockReturnValueOnce(response.promise);
  const { result } = renderHook(() => useNavigation({ openingId: 1, selectOpening: vi.fn().mockResolvedValue(true), loadRanking: vi.fn(), onError: vi.fn() }));
  await act(() => result.current.viewApplication(7));
  let request!: Promise<void>;
  act(() => { request = result.current.viewApplication(8); });
  act(() => result.current.updateSelectedApplication({ id: 7, privateNote: "Saved" }));
  await act(async () => { response.resolve({ id: 8 } as ApplicationDetail); await request; });
  expect(result.current.selectedApplication?.id).toBe(8);
});

const pool = (selectedOpeningId: number): ApplicationsResponse => ({ selectedOpeningId, applications: [], openings: [] });
const detail = (id: number): ApplicationDetail => ({
  id, primaryEmail: "synthetic@example.com", applicantName: "Synthetic", coApplicantName: null,
  status: "eligible", statusSource: "untouched", stale: false, hardFilterReasons: [],
  childCount: 0, householdIncome: 80000, flagCount: 0, flagCategories: [],
  starredByMe: false, shortlisted: false, selected: false, openingIds: [1],
  findingsFingerprint: "1".repeat(64), autoStatus: "eligible", autoStatusSource: "untouched",
  firstSubmittedAt: null, lastSubmittedAt: null, submissionVersionCount: 1,
  normalized: {}, essays: [], flags: [], privateNote: "", committeeNotes: [],
});

async function workspace() {
  vi.mocked(api.fetchApplications).mockImplementation(async (id) => pool(id ?? 1));
  vi.mocked(api.fetchApplication).mockImplementation(async (id) => detail(id));
  vi.mocked(api.fetchRetainedApplication).mockImplementation(async (id) => detail(id));
  const onError = vi.fn();
  const loadRanking = vi.fn().mockResolvedValue(true);
  const view = renderHook(() => {
    const applications = useApplications();
    const navigation = useNavigation({ openingId: applications.selectedOpeningId,
      selectOpening: applications.selectOpening, loadRanking, onError });
    return { ...applications, ...navigation };
  });
  await act(() => view.result.current.loadInitialApplications());
  return { ...view, onError, loadRanking };
}

function pop(location: unknown) {
  window.history.replaceState(location, "", window.location.pathname);
  window.dispatchEvent(new PopStateEvent("popstate", { state: location }));
}

it("records the chosen opening in the initial list entry", async () => {
  await workspace();
  expect(window.history.state).toEqual({ screenerLocation: true, tab: "applications", openingId: 1 });
});

it("installs the available opening in a root history entry recorded before any opening existed", async () => {
  const { result } = await workspace();
  await act(async () => pop({ screenerLocation: true, tab: "applications", openingId: null }));
  expect(result.current.selectedOpeningId).toBe(1);
  expect(window.history.state.openingId).toBe(1);
});

it("keeps the history entry truthful when a saved action closes applicant detail", async () => {
  const { result } = await workspace();
  await act(() => result.current.viewRetainedApplication(42));
  act(() => result.current.clearSelectedApplication());
  expect(result.current.selectedApplication).toBeNull();
  expect(result.current.selectedApplicationReadOnly).toBe(false);
  expect(window.history.state).toEqual({ screenerLocation: true, tab: "adminSettings", openingId: 1 });
});

it.each(["both openings", "only the recorded opening"])("restores Back/Forward context for an applicant in %s", async (membership) => {
  const { result, onError } = await workspace();
  await act(() => result.current.viewApplication(42));
  const first = window.history.state;
  await act(() => result.current.changeOpening(2));
  if (membership === "both openings") await act(() => result.current.viewApplication(42));
  const second = window.history.state;
  if (membership === "only the recorded opening") {
    vi.mocked(api.fetchApplication).mockImplementation(async (id, openingId) => {
      if (openingId !== 1) throw new Error("not linked");
      return detail(id);
    });
  }
  await act(async () => pop(first));
  await waitFor(() => expect(result.current.selectedApplication?.id).toBe(42));
  expect(result.current.selectedOpeningId).toBe(1);
  expect(api.fetchApplication).toHaveBeenLastCalledWith(42, 1);
  expect(window.localStorage.getItem("penta-selected-opening")).toBe("1");
  await act(async () => pop(second));
  await waitFor(() => expect(result.current.selectedOpeningId).toBe(2));
  expect(result.current.selectedApplication?.id ?? null).toBe(membership === "both openings" ? 42 : null);
  expect(onError).not.toHaveBeenCalled();
});

it("changes history and read-only mode when the same applicant is opened through a regular opening", async () => {
  const { result } = await workspace();
  await act(() => result.current.viewRetainedApplication(42));
  const retained = window.history.state;
  expect(result.current.activeTab).toBe("adminSettings");
  expect(result.current.selectedApplicationReadOnly).toBe(true);
  await act(() => result.current.viewApplication(42));
  const regular = window.history.state;
  expect(regular.retainedApplicant).toBeUndefined();
  expect(result.current.selectedApplicationReadOnly).toBe(false);
  await act(async () => pop(retained));
  expect(result.current.selectedApplicationReadOnly).toBe(true);
  await act(async () => pop(regular));
  expect(result.current.selectedApplicationReadOnly).toBe(false);
});

it("publishes detail only after opening restoration, with list and detail reads in parallel", async () => {
  const { result } = await workspace();
  const opening = deferred<ApplicationsResponse>();
  vi.mocked(api.fetchApplications).mockReturnValueOnce(opening.promise);
  let request!: Promise<void>;
  await act(async () => { request = result.current.viewApplication(42, 2); });
  expect(api.fetchApplication).toHaveBeenCalledWith(42, 2);
  expect(result.current.selectedApplication).toBeNull();
  await act(async () => { opening.resolve(pool(2)); await request; });
  expect(result.current.selectedOpeningId).toBe(2);
  expect(result.current.selectedApplication?.id).toBe(42);
  expect(window.history.state.openingId).toBe(2);
});

it("cancels a pending history opening restoration when the member navigates elsewhere", async () => {
  const { result, onError } = await workspace();
  await act(() => result.current.viewApplication(42));
  const first = window.history.state;
  await act(() => result.current.changeOpening(2));
  const opening = deferred<ApplicationsResponse>();
  vi.mocked(api.fetchApplications).mockReturnValueOnce(opening.promise);
  await act(async () => pop(first));
  act(() => result.current.navigateToView("adminSettings"));
  await act(async () => opening.resolve(pool(1)));
  expect(result.current.selectedOpeningId).toBe(2);
  expect(result.current.selectedApplication).toBeNull();
  expect(result.current.activeTab).toBe("adminSettings");
  expect(result.current.applicationsLoadState).toBe("ready");
  expect(window.history.state.openingId).toBe(2);
  expect(onError).not.toHaveBeenCalled();
});

it("does not restore stale detail after a newer history target", async () => {
  const { result } = await workspace();
  const first = deferred<ApplicationDetail>();
  vi.mocked(api.fetchApplication).mockReturnValueOnce(first.promise).mockResolvedValueOnce(detail(8));
  await act(async () => pop({ screenerLocation: true, tab: "applications", openingId: 1, applicantId: 7 }));
  await act(async () => pop({ screenerLocation: true, tab: "applications", openingId: 1, applicantId: 8 }));
  await act(async () => first.resolve(detail(7)));
  expect(result.current.selectedApplication?.id).toBe(8);
  expect(window.history.state.applicantId).toBe(8);
});

it("keeps the newest opening when overlapping cross-opening detail requests finish out of order", async () => {
  const { result } = await workspace();
  const second = deferred<ApplicationsResponse>();
  const third = deferred<ApplicationsResponse>();
  vi.mocked(api.fetchApplications).mockReturnValueOnce(second.promise).mockReturnValueOnce(third.promise);
  let old!: Promise<void>;
  let newest!: Promise<void>;
  await act(async () => { old = result.current.viewApplication(7, 2); });
  await act(async () => { newest = result.current.viewApplication(8, 3); });
  await act(async () => { third.resolve(pool(3)); await newest; });
  await act(async () => { second.resolve(pool(2)); await old; });
  expect(result.current.selectedOpeningId).toBe(3);
  expect(result.current.selectedApplication?.id).toBe(8);
  expect(window.history.state).toEqual({ screenerLocation: true, tab: "applications", openingId: 3, applicantId: 8 });
});

it("fences a pending list selection if the parallel applicant read fails", async () => {
  const { result, onError } = await workspace();
  const opening = deferred<ApplicationsResponse>();
  vi.mocked(api.fetchApplications).mockReturnValueOnce(opening.promise);
  vi.mocked(api.fetchApplication).mockRejectedValueOnce(new Error("not linked"));
  await act(() => result.current.viewApplication(42, 2));
  await act(async () => opening.resolve(pool(2)));
  expect(result.current.selectedOpeningId).toBe(1);
  expect(result.current.selectedApplication).toBeNull();
  expect(onError).toHaveBeenCalledOnce();
  expect(window.history.state.openingId).toBe(1);
});

it("handles an unavailable historical opening without substituting a different pool", async () => {
  const { result, onError } = await workspace();
  vi.mocked(api.fetchApplications).mockResolvedValueOnce(pool(1));
  await act(async () => pop({ screenerLocation: true, tab: "applications", openingId: 99, applicantId: 42 }));
  expect(result.current.selectedOpeningId).toBe(1);
  expect(result.current.selectedApplication).toBeNull();
  expect(onError).toHaveBeenCalledExactlyOnceWith("Couldn't load that view. Please try again.");
  expect(window.history.state).toEqual({ screenerLocation: true, tab: "applications", openingId: 1 });
});

it("ignores an opening's late ranking redirect after navigating to another tab", async () => {
  const { result } = await workspace();
  act(() => result.current.navigateToView("ranking"));
  act(() => result.current.navigateToView("adminSettings"));
  act(() => result.current.onOpeningRankingLoaded(1, false));
  expect(result.current.activeTab).toBe("adminSettings");
  expect(window.history.state.tab).toBe("adminSettings");
});

it("keeps a ranking applicant restoration when its independent criteria refresh fails", async () => {
  const { result } = await workspace();
  const pending = deferred<ApplicationDetail>();
  vi.mocked(api.fetchApplication).mockReturnValueOnce(pending.promise);
  await act(async () => pop({ screenerLocation: true, tab: "ranking", openingId: 1, applicantId: 42 }));
  act(() => result.current.onOpeningRankingLoaded(1, false));
  await act(async () => pending.resolve(detail(42)));
  expect(result.current.activeTab).toBe("ranking");
  expect(result.current.selectedApplication?.id).toBe(42);
});

it("reconciles note receipts with an overlapping same-app navigation read", async () => {
  const response = deferred<ApplicationDetail>();
  vi.mocked(api.fetchApplication).mockReturnValue(response.promise);
  const { result } = renderHook(() => useNavigation({ openingId: 1,
    selectOpening: vi.fn(), loadRanking: vi.fn(), onError: vi.fn() }));
  let reading!: Promise<void>;
  act(() => { reading = result.current.viewApplication(7); });
  act(() => {
    result.current.updateSelectedApplication({ id: 7, privateNote: "Confirmed" });
    result.current.updateSelectedApplication({ id: 7, shortlisted: true }, 2);
  });
  await act(async () => {
    response.resolve({ id: 7, privateNote: "Old", status: "eligible", shortlisted: false } as ApplicationDetail);
    await reading;
  });
  expect(result.current.selectedApplication).toMatchObject({ privateNote: "Confirmed",
    status: "eligible", shortlisted: false });
});

it("keeps unseen eligibility evidence out of detail while refreshing it in the background", async () => {
  const original = detail(7);
  const reply = deferred<ApplicationDetail>();
  api.fetchApplication.mockResolvedValueOnce(original).mockReturnValueOnce(reply.promise);
  const { result } = renderHook(() => useNavigation({ openingId: 1, selectOpening: vi.fn(), loadRanking: vi.fn(), onError: vi.fn() }));
  await act(() => result.current.viewApplication(7));
  const newer = { ...original, statusSource: "human" as const, stale: true, findingsFingerprint: "2".repeat(64),
    normalized: { household_income: 100 }, hardFilterReasons: [{ code: "income_below_range", message: "New income", details: {} }] };
  act(() => result.current.updateSelectedApplication({ id: 7, status: "eligible", statusSource: "human", stale: true,
    findingsFingerprint: newer.findingsFingerprint, hardFilterReasons: newer.hardFilterReasons }, 1));
  expect(result.current.selectedApplication?.statusSource).toBe("human");
  expect(result.current.selectedApplication?.stale).toBe(true);
  expect(result.current.selectedApplication?.findingsFingerprint).toBe(original.findingsFingerprint);
  expect(result.current.selectedApplication?.hardFilterReasons).toEqual([]);
  await act(async () => reply.resolve(newer));
  expect(result.current.selectedApplication?.findingsFingerprint).toBe(newer.findingsFingerprint);
  expect(result.current.selectedApplication?.normalized.household_income).toBe(100);
});

it.each(["navigation", "background"])("supersedes older captured findings after a later status receipt (%s)", async (mode) => {
  const original = detail(7);
  const olderRead = deferred<ApplicationDetail>();
  const latestRead = deferred<ApplicationDetail>();
  api.fetchApplication.mockResolvedValueOnce(original).mockReturnValueOnce(olderRead.promise).mockReturnValueOnce(latestRead.promise);
  const { result } = renderHook(() => useNavigation({ openingId: 1, selectOpening: vi.fn(), loadRanking: vi.fn(), onError: vi.fn() }));
  await act(() => result.current.viewApplication(7));
  if (mode === "navigation") act(() => result.current.navigateToView("applications"));
  let reading!: Promise<void>;
  act(() => { reading = mode === "navigation" ? result.current.viewApplication(7) : result.current.refreshApplication(7, 1); });
  act(() => result.current.updateSelectedApplication({ id: 7, status: "eligible", statusSource: "human", stale: false,
    findingsFingerprint: original.findingsFingerprint, autoStatus: "eligible", autoStatusSource: "untouched", hardFilterReasons: [] }, 1));
  await act(async () => {
    olderRead.resolve({ ...original, findingsFingerprint: "2".repeat(64),
      hardFilterReasons: [{ code: "income_below_range", message: "Superseded finding", details: {} }] });
    await reading;
  });
  expect(result.current.selectedApplication?.findingsFingerprint).not.toBe("2".repeat(64));
  expect(api.fetchApplication).toHaveBeenCalledTimes(3);
  await act(async () => latestRead.resolve({ ...original, statusSource: "human", stale: false }));
  expect(result.current.selectedApplication?.findingsFingerprint).toBe(original.findingsFingerprint);
  expect(result.current.selectedApplication?.hardFilterReasons).toEqual([]);
  expect(result.current.selectedApplication?.stale).toBe(false);
  expect(window.history.state.applicantId).toBe(7);
});


it("opens a non-applicant feedback view in its recorded opening", async () => {
  const { result } = await workspace();
  act(() => result.current.navigateToView("observability", 2));
  await waitFor(() => expect(result.current.selectedOpeningId).toBe(2));
  expect(result.current.activeTab).toBe("observability");
  expect(window.history.state).toEqual({ screenerLocation: true, tab: "observability", openingId: 2 });
});
