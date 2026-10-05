import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import * as api from "../api/applications";
import { deferred } from "../testSupport";
import { usePrivateNotes } from "./usePrivateNotes";

vi.mock("../api/applications", () => ({ savePrivateNote: vi.fn() }));
beforeEach(() => {
  vi.useFakeTimers();
  vi.mocked(api.savePrivateNote).mockReset().mockResolvedValue(new Response(null));
});
afterEach(() => vi.useRealTimers());

function workspace() {
  const onSaved = vi.fn();
  const onError = vi.fn();
  return { ...renderHook(() => usePrivateNotes({ onSaved, onError })), onSaved, onError };
}

function pageExit() {
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  return event.defaultPrevented;
}

it("saves a disposed editor's draft under its captured opening without blocking navigation", async () => {
  const { result, rerender } = workspace();
  act(() => result.current.editor(7, 1, "Saved").change("Draft before navigation"));
  rerender(); // The owner remains; there is no longer an editor for applicant 7.
  expect(api.savePrivateNote).not.toHaveBeenCalled();
  expect(pageExit()).toBe(true);
  await act(async () => { await vi.advanceTimersByTimeAsync(600); });
  expect(api.savePrivateNote).toHaveBeenCalledExactlyOnceWith(7, 1, "Draft before navigation");
  expect(result.current.hasUnconfirmed()).toBe(false);
  expect(pageExit()).toBe(false);
});

it("releases confirmed drafts after navigation so later detail reads can supply fresh notes", async () => {
  const { result } = workspace();
  act(() => result.current.editor(7, 1, "Original").change("Saved from this page"));
  await act(() => vi.advanceTimersByTimeAsync(600));
  expect(result.current.editor(7, 2, "Fresher note from another device").getSnapshot().body)
    .toBe("Fresher note from another device");
  expect(result.current.hasUnconfirmed()).toBe(false);
});

it("retains a failed draft across openings and exposes a successful explicit retry", async () => {
  vi.mocked(api.savePrivateNote).mockResolvedValueOnce(new Response(null, { status: 409 }));
  const { result, onError } = workspace();
  act(() => result.current.editor(7, 1, "Saved").change("Unsaved"));
  await act(async () => { await vi.advanceTimersByTimeAsync(600); });
  const restored = result.current.editor(7, 2, "Saved");
  expect(restored.getSnapshot().body).toBe("Unsaved");
  expect(restored.getSnapshot().status).toBe("error");
  expect(onError).toHaveBeenCalledOnce();
  expect(pageExit()).toBe(true);
  await act(async () => restored.flush());
  expect(api.savePrivateNote).toHaveBeenLastCalledWith(7, 2, "Unsaved");
  expect(result.current.editor(7, 2, "Saved").getSnapshot().status).toBe("saved");
});

it("orders writes across openings, skips middle drafts, and keeps the newest text on acknowledgement", async () => {
  const first = deferred<Response>();
  const last = deferred<Response>();
  vi.mocked(api.savePrivateNote).mockReturnValueOnce(first.promise).mockReturnValueOnce(last.promise);
  const { result, onSaved } = workspace();
  await act(async () => {
    result.current.editor(7, 1, "Saved").change("First");
    result.current.editor(7, 1, "Saved").flush();
  });
  for (const body of ["Middle", "Newest"]) {
    act(() => {
      result.current.editor(7, 2, "Saved").change(body);
      result.current.editor(7, 2, "Saved").flush();
    });
  }
  await act(async () => first.resolve(new Response(null)));
  expect(vi.mocked(api.savePrivateNote).mock.calls).toEqual([[7, 1, "First"], [7, 2, "Newest"]]);
  expect(onSaved).toHaveBeenCalledWith(7, "First");
  expect(result.current.editor(7, 2, "First").getSnapshot().body).toBe("Newest");
  expect(pageExit()).toBe(true);
  await act(async () => last.resolve(new Response(null)));
  expect(result.current.hasUnconfirmed()).toBe(false);
});

it("lets other applicants save while one applicant's request is pending", async () => {
  const first = deferred<Response>();
  vi.mocked(api.savePrivateNote).mockReturnValueOnce(first.promise).mockResolvedValueOnce(new Response(null));
  const { result } = workspace();
  await act(async () => {
    result.current.editor(7, 1, "").change("First applicant");
    result.current.editor(7, 1, "").flush();
    result.current.editor(8, 2, "").change("Second applicant");
    result.current.editor(8, 2, "").flush();
  });
  expect(api.savePrivateNote).toHaveBeenCalledTimes(2);
  expect(result.current.editor(8, 2, "").getSnapshot().status).toBe("saved");
  await act(async () => first.resolve(new Response(null)));
});

it("fences queued writes and acknowledgements before logout changes credentials", async () => {
  const first = deferred<Response>();
  vi.mocked(api.savePrivateNote).mockReturnValueOnce(first.promise);
  const { result, onSaved } = workspace();
  await act(async () => {
    result.current.editor(7, 1, "").change("Sent under original account");
    result.current.editor(7, 1, "").flush();
  });
  act(() => {
    result.current.editor(7, 1, "").change("Queued under original account");
    result.current.editor(7, 1, "").flush();
    result.current.suspendWrites();
  });
  await act(async () => {
    first.resolve(new Response(null));
    await vi.advanceTimersByTimeAsync(1_000);
  });
  expect(api.savePrivateNote).toHaveBeenCalledOnce();
  expect(onSaved).not.toHaveBeenCalled();
  await act(async () => result.current.resumeWrites()); // Logout failed; original account remains.
  expect(api.savePrivateNote).toHaveBeenLastCalledWith(7, 1, "Queued under original account");
  expect(result.current.hasUnconfirmed()).toBe(false);
});

it("cancels debounce and queued work when the account workspace unmounts", async () => {
  const first = deferred<Response>();
  vi.mocked(api.savePrivateNote).mockReturnValueOnce(first.promise);
  const old = workspace();
  await act(async () => {
    old.result.current.editor(7, 1, "").change("Sent");
    old.result.current.editor(7, 1, "").flush();
  });
  act(() => {
    old.result.current.editor(7, 1, "").change("Queued");
    old.result.current.editor(7, 1, "").flush();
    old.result.current.editor(8, 1, "").change("Debounced");
  });
  old.unmount();
  const fresh = workspace();
  await act(async () => {
    first.resolve(new Response(null));
    await vi.advanceTimersByTimeAsync(1_000);
  });
  expect(api.savePrivateNote).toHaveBeenCalledOnce();
  expect(old.onSaved).not.toHaveBeenCalled();
  expect(fresh.result.current.editor(7, 1, "Fresh account").getSnapshot().body).toBe("Fresh account");
  expect(fresh.result.current.hasUnconfirmed()).toBe(false);
});

it("retains a blocked draft for copying and explicit discard without retrying", async () => {
  vi.mocked(api.savePrivateNote).mockResolvedValue(new Response(null, { status: 404 }));
  const { result } = workspace();
  const editor = result.current.editor(7, 1, "Saved");
  act(() => editor.change("Keep this unsaved text"));
  await act(() => vi.advanceTimersByTimeAsync(600));
  expect(editor.getSnapshot()).toEqual({ body: "Keep this unsaved text", status: "blocked" });
  act(() => editor.flush());
  expect(api.savePrivateNote).toHaveBeenCalledOnce();
  expect(pageExit()).toBe(true);
  act(() => editor.discard());
  expect(editor.getSnapshot()).toEqual({ body: "Saved", status: "saved" });
  expect(pageExit()).toBe(false);
});

it("stops a debounced draft when the application becomes read-only", async () => {
  const { result } = workspace();
  const editor = result.current.editor(7, 1, "Saved");
  act(() => { editor.change("Draft"); editor.block(); });
  await act(() => vi.advanceTimersByTimeAsync(600));
  expect(api.savePrivateNote).not.toHaveBeenCalled();
  expect(editor.getSnapshot().status).toBe("blocked");
});
