import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import * as api from "../api/applications";
import { deferred } from "../testSupport";
import type { ApplicationDetail } from "../types";
import { useCandidateActions } from "./useCandidateActions";

vi.mock("../api/applications", () => ({
  overrideStatus: vi.fn(), savePrivateNote: vi.fn(),
  addCommitteeNote: vi.fn(), setStar: vi.fn(), setShortlist: vi.fn(),
}));

const detail = (id: number) => ({ id, status: "eligible" }) as ApplicationDetail;
function options(): Parameters<typeof useCandidateActions>[0] {
  return {
    openingId: 1, selectedApplication: detail(7), rankingLoaded: true,
    onApplicationUpdated: vi.fn(), onError: vi.fn(),
    refreshDashboard: vi.fn().mockResolvedValue(undefined),
    reloadApplications: vi.fn().mockResolvedValue(undefined),
    loadRanking: vi.fn().mockResolvedValue(true),
  };
}
beforeEach(() => vi.resetAllMocks());

it("refreshes every eligibility surface after a successful override", async () => {
  const initial = options();
  vi.mocked(api.overrideStatus).mockResolvedValue(Response.json({ application: detail(7) }));
  const { result } = renderHook(() => useCandidateActions(initial));
  await act(() => result.current.overrideStatus(7, "eligible"));
  expect(api.overrideStatus).toHaveBeenCalledWith(7, 1, "eligible");
  expect(initial.onApplicationUpdated).toHaveBeenCalledWith(detail(7));
  expect(initial.refreshDashboard).toHaveBeenCalledOnce();
  expect(initial.reloadApplications).toHaveBeenCalledOnce();
  expect(initial.loadRanking).toHaveBeenCalledOnce();
});

it("acknowledges a saved note without reopening a detail the member has left", async () => {
  const pending = deferred<Response>();
  vi.mocked(api.savePrivateNote).mockReturnValue(pending.promise);
  const initial = options();
  const { result, rerender } = renderHook((props) => useCandidateActions(props), { initialProps: initial });
  let save!: Promise<boolean>;
  act(() => { save = result.current.savePrivateNote(7, "Synthetic committee note"); });
  rerender({ ...initial, selectedApplication: detail(8) });
  await act(async () => {
    pending.resolve(Response.json({ application: detail(7) })); expect(await save).toBe(true);
  });
  expect(initial.onApplicationUpdated).not.toHaveBeenCalled();
  expect(initial.onError).not.toHaveBeenCalled();
});

it("ignores a completed write after switching openings", async () => {
  const pending = deferred<Response>();
  vi.mocked(api.overrideStatus).mockReturnValue(pending.promise);
  const initial = options();
  const { result, rerender } = renderHook((props) => useCandidateActions(props), { initialProps: initial });
  let save!: Promise<void>;
  act(() => { save = result.current.overrideStatus(7, "eligible"); });
  rerender({ ...initial, openingId: 2 });
  await act(async () => { pending.resolve(Response.json({ application: detail(7) })); await save; });
  expect(initial.onApplicationUpdated).not.toHaveBeenCalled();
  expect(initial.refreshDashboard).not.toHaveBeenCalled();
  expect(initial.reloadApplications).not.toHaveBeenCalled();
  expect(initial.loadRanking).not.toHaveBeenCalled();
});

it.each(["favourite", "shortlist"])("refreshes the full cached pool for a %s change made outside the list", async (view) => {
  const initial = { ...options(), selectedApplication: null };
  vi.mocked(api.setStar).mockResolvedValue(Response.json({ application: detail(7) }));
  vi.mocked(api.setShortlist).mockResolvedValue(Response.json({ application: detail(7) }));
  const { result } = renderHook(() => useCandidateActions(initial));
  await act(() => view === "favourite"
    ? result.current.toggleStar(7, true) : result.current.toggleShortlist(7, true));
  expect(initial.reloadApplications).toHaveBeenCalledOnce();
  expect(initial.loadRanking).toHaveBeenCalledOnce();
  expect(initial.onApplicationUpdated).not.toHaveBeenCalled();
});

it("reports a failed note save and leaves the loaded detail unchanged", async () => {
  const initial = options();
  vi.mocked(api.addCommitteeNote).mockResolvedValue(Response.json({ detail: "Locked" }, { status: 409 }));
  const { result } = renderHook(() => useCandidateActions(initial));
  await act(async () => { expect(await result.current.addCommitteeNote(7, "Synthetic note")).toBe(false); });
  expect(initial.onError).toHaveBeenCalledWith("Could not add the committee note.");
  expect(initial.onApplicationUpdated).not.toHaveBeenCalled();
});

it("serializes different writes for one applicant while allowing another applicant's save", async () => {
  const note = deferred<Response>();
  vi.mocked(api.savePrivateNote).mockReturnValueOnce(note.promise)
    .mockResolvedValueOnce(Response.json({ application: detail(8) }));
  const overridden = { ...detail(7), status: "ineligible" } as ApplicationDetail;
  vi.mocked(api.overrideStatus).mockResolvedValueOnce(Response.json({ application: overridden }));
  const initial = options();
  const { result } = renderHook(() => useCandidateActions(initial));
  let saving!: Promise<boolean>;
  let overriding!: Promise<void>;
  let other!: Promise<boolean>;
  await act(async () => {
    saving = result.current.savePrivateNote(7, "Synthetic note");
    overriding = result.current.overrideStatus(7, "ineligible");
    other = result.current.savePrivateNote(8, "Independent note");
  });
  expect(api.savePrivateNote).toHaveBeenCalledTimes(2);
  expect(api.overrideStatus).not.toHaveBeenCalled();
  await act(async () => {
    expect(await other).toBe(true);
    note.resolve(Response.json({ application: detail(7) }));
    expect(await saving).toBe(true);
    await overriding;
  });
  expect(initial.onApplicationUpdated).toHaveBeenLastCalledWith(overridden);
});

it("discards queued candidate writes for an opening the member has left", async () => {
  const first = deferred<Response>();
  vi.mocked(api.savePrivateNote).mockReturnValueOnce(first.promise);
  const initial = options();
  const { result, rerender } = renderHook((props) => useCandidateActions(props), { initialProps: initial });
  let saving!: Promise<boolean>;
  let overriding!: Promise<void>;
  await act(async () => {
    saving = result.current.savePrivateNote(7, "Synthetic note");
    overriding = result.current.overrideStatus(7, "ineligible");
  });
  rerender({ ...initial, openingId: 2 });
  await act(async () => {
    first.resolve(Response.json({ application: detail(7) }));
    await Promise.all([saving, overriding]);
  });
  expect(api.overrideStatus).not.toHaveBeenCalled();
  expect(initial.onApplicationUpdated).not.toHaveBeenCalled();
});
