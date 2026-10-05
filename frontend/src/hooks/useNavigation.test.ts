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
const detail = (id: number) => ({ id, privateNote: "" }) as ApplicationDetail;

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

it("reconciles successful writes with an overlapping same-app detail read", async () => {
  const response = deferred<ApplicationDetail>();
  vi.mocked(api.fetchApplication).mockReturnValue(response.promise);
  const { result } = renderHook(() => useNavigation({ openingId: 1,
    selectOpening: vi.fn(), loadRanking: vi.fn(), onError: vi.fn() }));
  let reading!: Promise<void>;
  act(() => { reading = result.current.viewApplication(7); });
  act(() => {
    result.current.updateSelectedApplication({ id: 7, privateNote: "Confirmed" });
    result.current.updateSelectedApplication({ id: 7, status: "ineligible" }, 1);
    result.current.updateSelectedApplication({ id: 7, shortlisted: true }, 2);
  });
  await act(async () => {
    response.resolve({ id: 7, privateNote: "Old", status: "eligible", shortlisted: false } as ApplicationDetail);
    await reading;
  });
  expect(result.current.selectedApplication).toMatchObject({ privateNote: "Confirmed",
    status: "ineligible", shortlisted: false });
});
