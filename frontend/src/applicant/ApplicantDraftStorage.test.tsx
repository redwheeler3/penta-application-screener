import { act, render } from "@testing-library/react";
import type { Dispatch, SetStateAction } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ApplicantApp } from "./ApplicantApp";
import { INITIAL_APPLICANT_PERSISTENCE_STATE } from "./applicantPersistenceState";
import { emptyApplicantDraft } from "./applicationDraft";
import { clearApplicantStorage, setRememberDevice } from "./draftStorage";
import type { ApplicantDraft } from "./types";

const controls = vi.hoisted(() => ({ setDraft: null as Dispatch<SetStateAction<ApplicantDraft>> | null }));
vi.mock("../hooks/useEmailDeliveryStatus", () => ({ useEmailDeliveryStatus: () => false }));
vi.mock("./useApplicantPersistence", () => ({
  useApplicantPersistence: (_draft: ApplicantDraft, setDraft: Dispatch<SetStateAction<ApplicantDraft>>) => {
    controls.setDraft = setDraft;
    return { ...INITIAL_APPLICANT_PERSISTENCE_STATE, authenticated: true, applicationId: 1,
      workingRevision: 1, openingsLoaded: true, hasUnsavedChanges: true, phase: "applications_unavailable" };
  },
}));

beforeEach(async () => {
  localStorage.clear();
  vi.useFakeTimers();
  let tail = Promise.resolve();
  vi.stubGlobal("navigator", { locks: { request: (_name: string, operation: () => unknown) => {
    const result = tail.then(operation);
    tail = result.then(() => {}, () => {});
    return result;
  } } });
  await setRememberDevice(true);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function typeAnswer() {
  act(() => controls.setDraft!({ ...emptyApplicantDraft(), pets: "Synthetic private answer" }));
}

function leavingIsPrevented() {
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  return event.defaultPrevented;
}

it("warns until the exact current answers are stored, even with remember-device enabled", async () => {
  render(<ApplicantApp />);
  typeAnswer();
  expect(leavingIsPrevented()).toBe(true);
  await act(() => vi.advanceTimersByTimeAsync(350));
  expect(leavingIsPrevented()).toBe(false);
  typeAnswer();
  expect(leavingIsPrevented()).toBe(true);
});

it("does not restore cleared storage and resumes the leaving warning", async () => {
  render(<ApplicantApp />);
  typeAnswer();
  await clearApplicantStorage();
  act(() => window.dispatchEvent(new StorageEvent("storage", { key: null, storageArea: localStorage })));
  await act(() => vi.advanceTimersByTimeAsync(350));
  expect(localStorage.length).toBe(0);
  expect(leavingIsPrevented()).toBe(true);
});

it("warns when a browser-storage write fails instead of promising recovery", async () => {
  render(<ApplicantApp />);
  typeAnswer();
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("Synthetic quota", "QuotaExceededError"); });
  await act(() => vi.advanceTimersByTimeAsync(350));
  expect(leavingIsPrevented()).toBe(true);
});
