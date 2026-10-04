import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import * as api from "../api/applications";
import { deferred } from "../testSupport";
import { useApplications } from "./useApplications";

vi.mock("../api/applications", () => ({ fetchApplications: vi.fn() }));
const payload = (selectedOpeningId: number): api.ApplicationsResponse => ({
  applications: [], openings: [], selectedOpeningId,
});

beforeEach(() => { vi.resetAllMocks(); window.localStorage.clear(); });
afterEach(() => vi.restoreAllMocks());

it.each(["getItem", "setItem"] as const)("loads the workspace when optional browser %s is denied", async (operation) => {
  vi.spyOn(Storage.prototype, operation).mockImplementation(() => { throw new DOMException("Denied", "SecurityError"); });
  vi.mocked(api.fetchApplications).mockResolvedValue(payload(1));
  const { result } = renderHook(() => useApplications());
  await act(() => result.current.loadInitialApplications());
  expect(result.current.applicationsLoadState).toBe("ready");
  expect(result.current.selectedOpeningId).toBe(1);
});

it("ignores an old background refresh after selecting another opening", async () => {
  const old = deferred<api.ApplicationsResponse>();
  vi.mocked(api.fetchApplications).mockResolvedValueOnce(payload(1))
    .mockReturnValueOnce(old.promise).mockResolvedValueOnce(payload(2));
  const { result } = renderHook(() => useApplications());
  await act(() => result.current.selectOpening(1));
  let refresh!: Promise<void>;
  act(() => { refresh = result.current.reloadApplications(); });
  await act(() => result.current.selectOpening(2));
  await act(async () => { old.resolve(payload(1)); await refresh; });
  expect(result.current.selectedOpeningId).toBe(2);
  expect(window.localStorage.getItem("penta-selected-opening")).toBe("2");
});

it("keeps the latest requested selection and skips background reads while selecting", async () => {
  const first = deferred<api.ApplicationsResponse>();
  const second = deferred<api.ApplicationsResponse>();
  vi.mocked(api.fetchApplications).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  const { result } = renderHook(() => useApplications());
  let selectionOne!: Promise<boolean>;
  let selectionTwo!: Promise<boolean>;
  act(() => { selectionOne = result.current.selectOpening(1); });
  await act(() => result.current.reloadApplications());
  act(() => { selectionTwo = result.current.selectOpening(2); });
  expect(api.fetchApplications).toHaveBeenCalledTimes(2);
  await act(async () => { second.resolve(payload(2)); expect(await selectionTwo).toBe(true); });
  await act(async () => { first.resolve(payload(1)); expect(await selectionOne).toBe(false); });
  expect(result.current.selectedOpeningId).toBe(2);
  expect(result.current.applicationsLoadState).toBe("ready");
});

it("preserves the loaded opening when its background refresh fails", async () => {
  vi.mocked(api.fetchApplications).mockResolvedValueOnce(payload(1)).mockRejectedValueOnce(new Error("offline"));
  const { result } = renderHook(() => useApplications());
  await act(() => result.current.selectOpening(1));
  await act(() => result.current.reloadApplications());
  expect(result.current.selectedOpeningId).toBe(1);
  expect(result.current.applicationsLoadState).toBe("ready");
});
