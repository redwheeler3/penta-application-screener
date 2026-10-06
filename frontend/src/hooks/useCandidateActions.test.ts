import { act } from "@testing-library/react";
import { renderCommitteeHook as renderHook, deferred } from "../testSupport";
import { beforeEach, expect, it, vi } from "vitest";
import type { ApplicationDetail, ApplicationUpdate, CommitteeActionResult } from "../types";
import { useCandidateActions } from "./useCandidateActions";

const api = vi.hoisted(() => ({
  overrideStatus: vi.fn<ReturnType<typeof import("../api/applications").createApi>["overrideStatus"]>(),
  addCommitteeNote: vi.fn<ReturnType<typeof import("../api/applications").createApi>["addCommitteeNote"]>(),
  setStar: vi.fn<ReturnType<typeof import("../api/applications").createApi>["setStar"]>(),
  setShortlist: vi.fn<ReturnType<typeof import("../api/applications").createApi>["setShortlist"]>(),
}));

vi.mock("../api/applications", () => ({
  createApi: () => api,
}));

const detail = (id: number): ApplicationDetail => ({
  id, primaryEmail: "synthetic@example.com", applicantName: "Synthetic", coApplicantName: null,
  status: "eligible", statusSource: "untouched", stale: false, hardFilterReasons: [],
  childCount: 0, householdIncome: null, flagCount: 0, flagCategories: [],
  starredByMe: false, shortlisted: false, selected: false, openingIds: [1],
  autoStatus: "eligible", autoStatusSource: "untouched", firstSubmittedAt: "2026-10-01T12:00:00Z",
  lastSubmittedAt: "2026-10-01T12:00:00Z", submissionVersionCount: 1,
  normalized: {}, essays: [], flags: [], rawRow: {}, dimensionScores: [],
  privateNote: "", committeeNotes: [],
});
function options(): Parameters<typeof useCandidateActions>[0] {
  return {
    openingId: 1, rankingLoaded: true,
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
  expect(initial.onApplicationUpdated).toHaveBeenCalledWith(detail(7), 1);
  expect(initial.refreshDashboard).toHaveBeenCalledOnce();
  expect(initial.reloadApplications).toHaveBeenCalledOnce();
  expect(initial.loadRanking).toHaveBeenCalledOnce();
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
  expect(initial.onApplicationUpdated).toHaveBeenCalledWith(detail(7), 1);
});

it("reports a failed note save and leaves the loaded detail unchanged", async () => {
  const initial = options();
  vi.mocked(api.addCommitteeNote).mockResolvedValue(Response.json({ detail: "Locked" }, { status: 409 }));
  const { result } = renderHook(() => useCandidateActions(initial));
  await act(async () => { expect(await result.current.addCommitteeNote(7, "Synthetic note", "synthetic-creation-key")).toBe("rejected"); });
  expect(initial.onError).toHaveBeenCalledWith("Could not add the committee note.");
  expect(initial.onApplicationUpdated).not.toHaveBeenCalled();
});

it("lets independent fields save concurrently without rolling back newer state", async () => {
  const note = deferred<Response>();
  vi.mocked(api.addCommitteeNote).mockReturnValueOnce(note.promise);
  const overridden = { id: 7, status: "ineligible" };
  vi.mocked(api.overrideStatus).mockResolvedValueOnce(Response.json({ application: overridden }));
  let displayed: ApplicationDetail = { ...detail(7), committeeNotes: [] };
  const initial = { ...options(), onApplicationUpdated: (update: ApplicationUpdate) => {
    displayed = { ...displayed, ...update };
  } };
  const { result } = renderHook(() => useCandidateActions(initial));
  let saving!: Promise<CommitteeActionResult>;
  let overriding!: Promise<void>;
  await act(async () => {
    saving = result.current.addCommitteeNote(7, "Synthetic note", "synthetic-creation-key");
    overriding = result.current.overrideStatus(7, "ineligible");
    await overriding;
  });
  expect(api.overrideStatus).toHaveBeenCalledOnce();
  expect(displayed.status).toBe("ineligible");
  await act(async () => {
    note.resolve(Response.json({ application: { id: 7, committeeNotes: [{ id: 1, body: "Synthetic note" }] } }));
    expect(await saving).toBe("saved");
  });
  expect(displayed.status).toBe("ineligible");
  expect(displayed.committeeNotes).toEqual([{ id: 1, body: "Synthetic note" }]);
});

it("discards queued candidate writes for an opening the member has left", async () => {
  const first = deferred<Response>();
  vi.mocked(api.addCommitteeNote).mockReturnValueOnce(first.promise);
  const initial = options();
  const { result, rerender } = renderHook((props) => useCandidateActions(props), { initialProps: initial });
  let saving!: Promise<CommitteeActionResult>;
  let second!: Promise<CommitteeActionResult>;
  await act(async () => {
    saving = result.current.addCommitteeNote(7, "Synthetic note", "synthetic-creation-key");
    second = result.current.addCommitteeNote(7, "Later note", "synthetic-creation-key");
  });
  rerender({ ...initial, openingId: 2 });
  await act(async () => {
    first.resolve(Response.json({ application: detail(7) }));
    await Promise.all([saving, second]);
  });
  expect(api.addCommitteeNote).toHaveBeenCalledOnce();
  expect(initial.onApplicationUpdated).not.toHaveBeenCalled();
});

it("sends opposing edits to the same field in order", async () => {
  const first = deferred<Response>();
  vi.mocked(api.setStar).mockReturnValueOnce(first.promise).mockResolvedValueOnce(
    Response.json({ application: { id: 7, starredByMe: false } }),
  );
  const initial = options();
  const { result } = renderHook(() => useCandidateActions(initial));
  let starred!: Promise<void>;
  let unstarred!: Promise<void>;
  await act(async () => {
    starred = result.current.toggleStar(7, true);
    unstarred = result.current.toggleStar(7, false);
  });
  expect(api.setStar).toHaveBeenCalledExactlyOnceWith(7, 1, true);
  await act(async () => {
    first.resolve(Response.json({ application: { id: 7, starredByMe: true } }));
    await Promise.all([starred, unstarred]);
  });
  expect(api.setStar).toHaveBeenLastCalledWith(7, 1, false);
  expect(initial.onApplicationUpdated).toHaveBeenLastCalledWith({ id: 7, starredByMe: false }, 1);
});


it.each([new Response("", { status: 503 }), Response.json({})])("retains an uncertain note attempt for transport or incomplete acknowledgement", async (response) => {
  api.addCommitteeNote.mockResolvedValue(response);
  const initial = options();
  const { result } = renderHook(() => useCandidateActions(initial));
  await act(async () => expect(await result.current.addCommitteeNote(7, "Synthetic note", "synthetic-key")).toBe("unconfirmed"));
  expect(initial.onApplicationUpdated).not.toHaveBeenCalled();
});
