import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { deferred } from "../testSupport";
import { emptyApplicantDraft } from "./applicationDraft";
import { captureApplicantStorage, clearApplicationDraft, clearApplicantStorage, loadApplicationDraft, rememberedStorageScope, saveApplicationDraft, setRememberDevice } from "./draftStorage";
import { useRememberedApplicantDraft } from "./useRememberedApplicantDraft";

const snapshot = {
  authenticated: true, applicationId: 1, workingRevision: 3,
  draft: emptyApplicantDraft(), openingIds: [11],
};

beforeEach(() => {
  window.localStorage.clear();
  vi.useFakeTimers();
  let tail = Promise.resolve();
  vi.stubGlobal("navigator", { locks: { request: vi.fn((_name, operation) => {
    const result = tail.then(operation);
    tail = result.then(() => {}, () => {});
    return result;
  }) } });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("clears only the captured unchanged record and preserves other applicants", async () => {
  const scope = (await setRememberDevice(true))!;
  await saveApplicationDraft(1, snapshot.draft, [11], 3, scope);
  await saveApplicationDraft(2, snapshot.draft, [12], 4, scope);
  const acknowledged = captureApplicantStorage();
  expect(await clearApplicationDraft(1, acknowledged)).toBe(true);
  expect(loadApplicationDraft(1)).toBeNull();
  expect(loadApplicationDraft(2)?.baseRevision).toBe(4);
});

it("invalid-date cleanup cannot delete a replacement queued ahead of its lock", async () => {
  const scope = (await setRememberDevice(true))!;
  await saveApplicationDraft(1, snapshot.draft, [11], 3, scope);
  const raw = JSON.parse(localStorage.getItem("penta-application-drafts-v5")!);
  raw["1"].savedAt = "invalid";
  localStorage.setItem("penta-application-drafts-v5", JSON.stringify(raw));
  const replacement = saveApplicationDraft(1, { ...snapshot.draft, pets: "Replacement" }, [11], 4, scope);
  expect(loadApplicationDraft(1)).toBeNull();
  await replacement;
  await act(() => vi.runAllTimersAsync());
  expect(loadApplicationDraft(1)?.draft.pets).toBe("Replacement");
});

it("rejects a queued save after consent is cleared, even before its storage event arrives", async () => {
  await setRememberDevice(true);
  const { result } = renderHook(() => useRememberedApplicantDraft(snapshot));
  await clearApplicantStorage();
  await act(() => vi.runAllTimersAsync());
  expect(window.localStorage.length).toBe(0);
  expect(result.current.savedAt).toBeNull();
  expect(result.current.currentDraftIsStored()).toBe(false);
});

it("does not revive an old save after another tab clears consent and opts in again", async () => {
  const oldScope = (await setRememberDevice(true))!;
  renderHook(() => useRememberedApplicantDraft(snapshot));
  await clearApplicantStorage();
  const nextScope = (await setRememberDevice(true))!;
  expect(nextScope).not.toBe(oldScope);
  await act(() => vi.runAllTimersAsync());
  expect(loadApplicationDraft(1)).toBeNull();
  expect(await saveApplicationDraft(1, snapshot.draft, [], 3, oldScope)).toBeNull();
});

it("reacts to another tab's storage reset without discarding this tab's answers", async () => {
  await setRememberDevice(true);
  const { result } = renderHook(() => useRememberedApplicantDraft(snapshot));
  act(() => window.dispatchEvent(new StorageEvent("storage", { storageArea: localStorage, key: null })));
  expect(result.current.rememberDevice).toBe(false);
  await act(() => vi.runAllTimersAsync());
  expect(loadApplicationDraft(1)).toBeNull();
  expect(snapshot.draft).toEqual(emptyApplicantDraft());
});

it("merges different applicants' writes under the shared browser lock", async () => {
  const scope = (await setRememberDevice(true))!;
  await Promise.all([
    saveApplicationDraft(1, snapshot.draft, [11], 3, scope),
    saveApplicationDraft(2, snapshot.draft, [12], 4, scope),
  ]);
  expect(loadApplicationDraft(1)?.openingIds).toEqual([11]);
  expect(loadApplicationDraft(2)?.openingIds).toEqual([12]);
});

it("revokes a recovery acknowledgement when another tab replaces the same applicant's draft", async () => {
  const scope = (await setRememberDevice(true))!;
  const { result } = renderHook(() => useRememberedApplicantDraft(snapshot));
  await act(() => vi.runAllTimersAsync());
  expect(result.current.currentDraftIsStored()).toBe(true);
  await saveApplicationDraft(1, { ...snapshot.draft, pets: "Other tab" }, [], 3, scope);
  // The leaving-page guard is correct even before the asynchronous storage event.
  expect(result.current.currentDraftIsStored()).toBe(false);
  act(() => window.dispatchEvent(new StorageEvent("storage", {
    storageArea: localStorage, key: "penta-application-drafts-v5",
  })));
  expect(result.current.savedAt).toBeNull();
  expect(result.current.rememberDevice).toBe(true);
});

it("keeps a recovery acknowledgement when another tab saves a different applicant", async () => {
  const scope = (await setRememberDevice(true))!;
  const { result } = renderHook(() => useRememberedApplicantDraft(snapshot));
  await act(() => vi.runAllTimersAsync());
  await saveApplicationDraft(2, snapshot.draft, [], 1, scope);
  act(() => window.dispatchEvent(new StorageEvent("storage", {
    storageArea: localStorage, key: "penta-application-drafts-v5",
  })));
  expect(result.current.savedAt).not.toBeNull();
  expect(result.current.currentDraftIsStored()).toBe(true);
});

it("keeps newer typing unacknowledged while an older browser save is waiting", async () => {
  await setRememberDevice(true);
  const gate = deferred<void>();
  void navigator.locks.request("penta-application-drafts-v5", () => gate.promise);
  const { result, rerender } = renderHook((props) => useRememberedApplicantDraft(props), { initialProps: snapshot });
  await act(() => vi.advanceTimersByTimeAsync(350));
  const newer = { ...snapshot, draft: { ...snapshot.draft, pets: "Synthetic newer answer" } };
  rerender(newer);
  await act(async () => { gate.resolve(); await Promise.resolve(); });
  expect(result.current.currentDraftIsStored()).toBe(false);
  await act(() => vi.runAllTimersAsync());
  expect(result.current.currentDraftIsStored()).toBe(true);
  expect(loadApplicationDraft(1)?.draft.pets).toBe(newer.draft.pets);
});

it("does not claim browser storage succeeded on quota failure", async () => {
  await setRememberDevice(true);
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("Synthetic quota", "QuotaExceededError"); });
  const { result } = renderHook(() => useRememberedApplicantDraft(snapshot));
  await act(() => vi.runAllTimersAsync());
  expect(result.current.savedAt).toBeNull();
  expect(result.current.currentDraftIsStored()).toBe(false);
});

it("declines persistent browser writes when cross-tab locking is unavailable", async () => {
  vi.stubGlobal("navigator", {});
  expect(await setRememberDevice(true)).toBeNull();
  expect(await saveApplicationDraft(1, snapshot.draft, [], 3, "expired consent")).toBeNull();
  expect(window.localStorage.length).toBe(0);
});

it("keeps browser persistence off when the browser denies storage reads", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new DOMException("Synthetic denied", "SecurityError"); });
  const { result } = renderHook(() => useRememberedApplicantDraft(snapshot));
  expect(result.current.rememberDevice).toBe(false);
  expect(result.current.currentDraftIsStored()).toBe(false);
});

it("handles a rejected consent write without claiming that remembering is enabled", async () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("Synthetic quota", "QuotaExceededError"); });
  const { result } = renderHook(() => useRememberedApplicantDraft(snapshot));
  await act(() => result.current.changeRememberDevice(true));
  expect(result.current.rememberDevice).toBe(false);
  expect(result.current.currentDraftIsStored()).toBe(false);
});

it("an older exit preserves a new consent lifetime and its newer draft", async () => {
  const oldScope = (await setRememberDevice(true))!;
  await saveApplicationDraft(1, snapshot.draft, [], 3, oldScope);
  const exiting = captureApplicantStorage();
  const nextScope = (await setRememberDevice(true))!;
  const newer = { ...snapshot.draft, pets: "Newer lifetime" };
  await saveApplicationDraft(1, newer, [], 4, nextScope);
  await clearApplicantStorage(exiting);
  expect(rememberedStorageScope()).toBe(nextScope);
  expect(loadApplicationDraft(1)?.draft.pets).toBe(newer.pets);
});

it("a delayed consent acknowledgement cannot restore a reset view", async () => {
  const { result } = renderHook(() => useRememberedApplicantDraft(snapshot));
  const gate = deferred<void>();
  void navigator.locks.request("penta-application-drafts-v5", () => gate.promise);
  let changing!: Promise<void>;
  act(() => { changing = result.current.changeRememberDevice(true); });
  act(() => result.current.reset());
  await act(async () => { gate.resolve(); await changing; });
  expect(result.current.rememberDevice).toBe(false);
  expect(result.current.currentDraftIsStored()).toBe(false);
});
