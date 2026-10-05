import { act, renderHook, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { deferred } from "../testSupport";
import * as api from "./api";
import type { ApplicationResponse } from "./applicantPersistence";
import { emptyApplicantDraft, workingAnswers } from "./applicationDraft";
import { useApplicantPersistence } from "./useApplicantPersistence";

vi.mock("./api", async (original) => {
  const mocked = {
  ...await original<typeof import("./api")>(),
  fetchApplication: vi.fn(), fetchPendingCopy: vi.fn(), fetchApplicantOpenings: vi.fn(),
  saveApplication: vi.fn(), savePendingDraft: vi.fn(), submitGuestApplication: vi.fn(),
  requestReturnAccessLink: vi.fn(), logoutApplicant: vi.fn(),
  withdrawApplication: vi.fn(), requestEmailChange: vi.fn(), deletePendingDraft: vi.fn(),
  reconcilePendingCopy: vi.fn(),
  checkGuestSubmission: vi.fn(), submitApplication: vi.fn(), cancelEmailChange: vi.fn(),
  };
  return { ...mocked, createApi: () => mocked };
});

function initialDraft() {
  const draft = emptyApplicantDraft();
  draft.applicant.email = "review@example.com";
  return draft;
}

function application(workingRevision = 1): ApplicationResponse {
  const draft = initialDraft();
  return {
    applicationId: 1, primaryEmail: draft.applicant.email, googleSignInLinked: false,
    pendingEmailChange: null, answers: workingAnswers(draft), workingSavedAt: null,
    workingRevision, submitted: false, canEdit: true, openings: [],
  };
}

function renderPersistence(reactStrictMode = false) {
  return renderHook(() => {
    const [draft, setDraft] = useState(initialDraft);
    return { draft, setDraft, persistence: useApplicantPersistence(draft, setDraft, () => {}) };
  }, { reactStrictMode });
}

beforeEach(() => {
  vi.resetAllMocks();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
  vi.mocked(api.fetchApplication).mockImplementation(async () => Response.json(application()));
  vi.mocked(api.fetchPendingCopy).mockImplementation(async () => Response.json({ pendingCopy: null }));
  vi.mocked(api.fetchApplicantOpenings).mockImplementation(async () => Response.json({
    canStartApplication: true, openings: [],
  }));
});

it("restores the one-shot initial application when Strict Mode replays effects", async () => {
  const { result } = renderPersistence(true);
  await waitFor(() => expect(result.current.persistence.openingsLoaded).toBe(true));
  expect(result.current.persistence.authenticated).toBe(true);
  expect(api.fetchApplication).toHaveBeenCalledOnce();
});

it("keeps edits made during an authenticated save dirty and uses the returned revision", async () => {
  const saved = deferred<Response>();
  vi.mocked(api.saveApplication).mockReturnValue(saved.promise);
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.authenticated).toBe(true));
  let request!: Promise<void>;
  act(() => { request = result.current.persistence.start("save"); });
  act(() => result.current.setDraft((draft) => ({
    ...draft, essays: { ...draft.essays, whyCoop: "Edited while saving" },
  })));
  expect(vi.mocked(api.saveApplication).mock.calls[0][0].essays.whyCoop).toBe("");
  await act(async () => { saved.resolve(Response.json(application(2))); await request; });
  expect(result.current.persistence.hasUnsavedChanges).toBe(true);
  expect(result.current.persistence.workingRevision).toBe(2);
  expect(result.current.draft.essays.whyCoop).toBe("Edited while saving");
});

it.each(["save", "submit"] as const)("keeps edits and opening changes during a guest %s dirty", async (intent) => {
  vi.mocked(api.fetchApplication).mockImplementation(async () => new Response(null, { status: 401 }));
  const saved = deferred<Response>();
  vi.mocked(api.savePendingDraft).mockReturnValue(saved.promise);
  vi.mocked(api.submitGuestApplication).mockReturnValue(saved.promise);
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.openingsLoaded).toBe(true));
  let request!: Promise<void>;
  act(() => { request = result.current.persistence.start(intent); });
  act(() => {
    result.current.setDraft((draft) => ({ ...draft, pets: "A cat" }));
    result.current.persistence.setOpeningSelected(7, true);
  });
  await act(async () => {
    saved.resolve(Response.json({ draftToken: "synthetic-draft", emailSent: true, emailStatus: "sent" }));
    await request;
  });
  expect(result.current.persistence.hasUnsavedChanges).toBe(true);
  expect(result.current.persistence.openingIds).toEqual([7]);
});

it("acknowledges saved guest answers even if their access email fails", async () => {
  vi.mocked(api.fetchApplication).mockImplementation(async () => new Response(null, { status: 401 }));
  vi.mocked(api.savePendingDraft).mockResolvedValue(Response.json({
    draftToken: "synthetic-draft", emailSent: false, emailStatus: "failed",
  }));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.openingsLoaded).toBe(true));
  await act(() => result.current.persistence.start("save"));
  expect(result.current.persistence.phase).toBe("email_failed");
  expect(result.current.persistence.hasUnsavedChanges).toBe(false);
});

it("does not acknowledge edits made while requesting a return access link", async () => {
  const emailed = deferred<Response>();
  vi.mocked(api.requestReturnAccessLink).mockReturnValue(emailed.promise);
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.authenticated).toBe(true));
  let request!: Promise<boolean>;
  act(() => { request = result.current.persistence.emailReturnLink(); });
  act(() => result.current.setDraft((draft) => ({ ...draft, pets: "A cat" })));
  await act(async () => {
    emailed.resolve(Response.json({ currentAnswersSaved: true, workingRevision: 2, emailStatus: "sent" })); await request;
  });
  expect(result.current.persistence.hasUnsavedChanges).toBe(true);
  expect(result.current.persistence.workingRevision).toBe(2);
});
afterEach(() => vi.restoreAllMocks());

it.each(["signOut", "withdrawApplication"] as const)("finishes confirmed %s when browser cleanup fails and reports the remaining copy", async (action) => {
  vi.mocked(api.logoutApplicant).mockResolvedValue(new Response(null, { status: 204 }));
  vi.mocked(api.withdrawApplication).mockResolvedValue(Response.json({ withdrawn: true }));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.authenticated).toBe(true));
  vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => { throw new DOMException("Denied", "SecurityError"); });
  await act(async () => expect(await result.current.persistence[action]()).toBe(true));
  expect(result.current.persistence.authenticated).toBe(false);
  expect(result.current.persistence.browserStorageMessage).toContain("Could not clear");
  expect(result.current.persistence.withdrawalStatus).toBe("idle");
});

it("retains a saved guest draft when its discard is not acknowledged", async () => {
  vi.mocked(api.fetchApplication).mockResolvedValue(new Response(null, { status: 401 }));
  vi.mocked(api.savePendingDraft).mockResolvedValue(Response.json({ draftToken: "synthetic-draft", emailSent: true, emailStatus: "sent" }));
  vi.mocked(api.deletePendingDraft).mockResolvedValue(new Response(null, { status: 503 }));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.openingsLoaded).toBe(true));
  await act(() => result.current.persistence.start("save"));
  await act(async () => expect(await result.current.persistence.discardDraft()).toBe(false));
  expect(result.current.persistence.message).toContain("answers are still here");
  vi.mocked(api.deletePendingDraft).mockResolvedValue(new Response(null, { status: 204 }));
  await act(async () => expect(await result.current.persistence.discardDraft()).toBe(true));
  expect(api.deletePendingDraft).toHaveBeenCalledTimes(2);
});

it.each(["sent", "recent", "failed"])("acknowledges the return-link save when email status is %s", async (emailStatus) => {
  vi.mocked(api.requestReturnAccessLink).mockResolvedValue(Response.json({
    currentAnswersSaved: true, workingRevision: 2, emailStatus,
  }));
  vi.mocked(api.saveApplication).mockResolvedValue(Response.json(application(3)));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.authenticated).toBe(true));
  act(() => result.current.setDraft((draft) => ({ ...draft, pets: "A cat" })));
  await act(() => result.current.persistence.emailReturnLink());
  expect(result.current.persistence.workingRevision).toBe(2);
  expect(result.current.persistence.hasUnsavedChanges).toBe(false);
  await act(() => result.current.persistence.start("save"));
  expect(vi.mocked(api.saveApplication).mock.calls[0][2]).toBe(2);
});

it("requesting entry with another email does not mutate the application draft", async () => {
  vi.mocked(api.requestReturnAccessLink).mockResolvedValue(Response.json({ emailStatus: "sent" }));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.authenticated).toBe(true));
  await act(() => result.current.persistence.requestEntryLink("other@example.com"));
  expect(result.current.draft.applicant.email).toBe("review@example.com");
  expect(vi.mocked(api.requestReturnAccessLink).mock.calls[0][0].applicant.email).toBe("other@example.com");
});

it("discards a lifecycle response started before a successful save", async () => {
  const lifecycle = deferred<Response>();
  vi.mocked(api.saveApplication).mockResolvedValue(Response.json(application(2)));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.authenticated).toBe(true));
  vi.mocked(api.fetchApplication).mockReturnValueOnce(lifecycle.promise);
  act(() => document.dispatchEvent(new Event("visibilitychange")));
  await act(() => result.current.persistence.start("save"));
  await act(async () => { lifecycle.resolve(Response.json(application(1))); });
  expect(result.current.persistence.workingRevision).toBe(2);
  expect(result.current.persistence.phase).toBe("saved");
});

it("clears authenticated state and pending reconciliation when signing out", async () => {
  vi.mocked(api.fetchPendingCopy).mockResolvedValue(Response.json({
    pendingCopy: { savedAnswers: workingAnswers(initialDraft()), savedOpeningIds: [],
      guestAnswers: workingAnswers(initialDraft()), guestOpeningIds: [] },
  }));
  vi.mocked(api.logoutApplicant).mockResolvedValue(new Response(null, { status: 204 }));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.pendingCopy).not.toBeNull());
  await act(() => result.current.persistence.signOut());
  expect(result.current.persistence.authenticated).toBe(false);
  expect(result.current.persistence.workingRevision).toBeNull();
  expect(result.current.persistence.pendingCopy).toBeNull();
});

it("does not restore a pending copy when its response arrives after sign-out", async () => {
  const pending = deferred<Response>();
  vi.mocked(api.fetchPendingCopy).mockReturnValue(pending.promise);
  vi.mocked(api.logoutApplicant).mockResolvedValue(new Response(null, { status: 204 }));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.authenticated).toBe(true));
  await act(() => result.current.persistence.signOut());
  await act(async () => {
    pending.resolve(Response.json({ pendingCopy: {
      savedAnswers: workingAnswers(initialDraft()), savedOpeningIds: [],
      guestAnswers: workingAnswers(initialDraft()), guestOpeningIds: [],
    } }));
  });
  expect(result.current.persistence.pendingCopy).toBeNull();
  expect(result.current.persistence.authenticated).toBe(false);
});

it("a retained save action uses the latest revision and opening choices", async () => {
  vi.mocked(api.saveApplication).mockResolvedValueOnce(Response.json(application(2)))
    .mockResolvedValueOnce(Response.json(application(3)));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.authenticated).toBe(true));
  const save = result.current.persistence.start;
  await act(() => save("save"));
  act(() => result.current.persistence.setOpeningSelected(7, true));
  await act(() => save("save"));
  expect(vi.mocked(api.saveApplication).mock.calls[1].slice(1)).toEqual([[7], 2]);
  expect(result.current.persistence.workingRevision).toBe(3);
});

it("ignores an identity response captured before this browser's own save", async () => {
  const identity = deferred<Response>();
  vi.mocked(api.saveApplication).mockResolvedValue(Response.json(application(2)));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.authenticated).toBe(true));
  vi.mocked(api.fetchApplication).mockReturnValueOnce(identity.promise);
  let refresh!: Promise<void>;
  act(() => { refresh = result.current.persistence.refreshEmailIdentity(); });
  await act(() => result.current.persistence.start("save"));
  await act(async () => { identity.resolve(Response.json(application(1))); await refresh; });
  expect(result.current.persistence.workingRevision).toBe(2);
  expect(result.current.persistence.phase).toBe("saved");
});

it("does not restore email identity after sign-out clears the session", async () => {
  const identity = deferred<Response>();
  vi.mocked(api.logoutApplicant).mockResolvedValue(new Response(null, { status: 204 }));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.authenticated).toBe(true));
  vi.mocked(api.fetchApplication).mockReturnValueOnce(identity.promise);
  let refresh!: Promise<void>;
  act(() => { refresh = result.current.persistence.refreshEmailIdentity(); });
  await act(() => result.current.persistence.signOut());
  act(() => result.current.setDraft(emptyApplicantDraft()));
  await act(async () => { identity.resolve(Response.json(application())); await refresh; });
  expect(result.current.persistence.primaryEmail).toBeNull();
  expect(result.current.persistence.workingRevision).toBeNull();
  expect(result.current.draft.applicant.email).toBe("");
});

it("invalidates identity reads started while a save was in flight", async () => {
  const identity = deferred<Response>();
  const saved = deferred<Response>();
  vi.mocked(api.saveApplication).mockReturnValueOnce(saved.promise);
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.authenticated).toBe(true));
  let saving!: Promise<void>;
  act(() => { saving = result.current.persistence.start("save"); });
  vi.mocked(api.fetchApplication).mockReturnValueOnce(identity.promise);
  let refresh!: Promise<void>;
  act(() => { refresh = result.current.persistence.refreshEmailIdentity(); });
  await act(async () => { saved.resolve(Response.json(application(2))); await saving; });
  await act(async () => { identity.resolve(Response.json(application(1))); await refresh; });
  expect(result.current.persistence.workingRevision).toBe(2);
  expect(result.current.persistence.phase).toBe("saved");
});

it("email confirmation updates identity without acknowledging unsaved essay edits", async () => {
  vi.mocked(api.fetchApplication).mockResolvedValueOnce(Response.json({
    ...application(), googleSignInLinked: true,
  }));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.authenticated).toBe(true));
  act(() => result.current.setDraft((draft) => ({
    ...draft, essays: { ...draft.essays, whyCoop: "Unsaved synthetic edit" },
  })));
  vi.mocked(api.fetchApplication).mockResolvedValueOnce(Response.json({
    ...application(), primaryEmail: "changed@example.com", googleSignInLinked: false,
  }));
  await act(() => result.current.persistence.refreshEmailIdentity());
  expect(result.current.draft.applicant.email).toBe("changed@example.com");
  expect(result.current.draft.essays.whyCoop).toBe("Unsaved synthetic edit");
  expect(result.current.persistence.hasUnsavedChanges).toBe(true);
  expect(result.current.persistence.emailChangeStatus).toBe("confirmed");
  expect(result.current.persistence.googleDisconnectedByEmailChange).toBe(true);
});

it.each(["signOut", "withdrawApplication"] as const)("ignores a pending save after %s", async (exit) => {
  const saved = deferred<Response>();
  vi.mocked(api.saveApplication).mockReturnValue(saved.promise);
  vi.mocked(api.logoutApplicant).mockResolvedValue(new Response(null, { status: 204 }));
  vi.mocked(api.withdrawApplication).mockResolvedValue(new Response(null, { status: 204 }));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.authenticated).toBe(true));
  let request!: Promise<void>;
  act(() => { request = result.current.persistence.start("save"); });
  await act(() => result.current.persistence[exit]());
  await act(async () => { saved.resolve(Response.json(application(2))); await request; });
  expect(result.current.persistence.authenticated).toBe(false);
  expect(result.current.persistence.workingRevision).toBeNull();
  expect(result.current.persistence.phase).toBe(exit === "signOut" ? "idle" : "withdrawn");
});

it("does not restore an email-change response after signing out", async () => {
  const emailed = deferred<Response>();
  vi.mocked(api.requestEmailChange).mockReturnValue(emailed.promise);
  vi.mocked(api.logoutApplicant).mockResolvedValue(new Response(null, { status: 204 }));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.authenticated).toBe(true));
  let request!: Promise<void>;
  act(() => { request = result.current.persistence.beginEmailChange("new@example.com"); });
  await act(() => result.current.persistence.signOut());
  await act(async () => {
    emailed.resolve(Response.json({ emailSent: true, emailStatus: "sent", pendingEmail: "new@example.com" }));
    await request;
  });
  expect(result.current.persistence.pendingEmailChange).toBeNull();
  expect(result.current.persistence.emailChangeStatus).toBe("idle");
});

it("ignores a pending guest draft acknowledgement after discarding it", async () => {
  vi.mocked(api.fetchApplication).mockResolvedValue(new Response(null, { status: 401 }));
  const saved = deferred<Response>();
  vi.mocked(api.savePendingDraft).mockReturnValue(saved.promise);
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.openingsLoaded).toBe(true));
  let request!: Promise<void>;
  act(() => { request = result.current.persistence.start("save"); });
  await act(() => result.current.persistence.discardDraft());
  await act(async () => {
    saved.resolve(Response.json({ draftToken: "obsolete-token", emailSent: true, emailStatus: "sent" }));
    await request;
  });
  expect(result.current.persistence.phase).toBe("idle");
  expect(result.current.persistence.hasUnsavedChanges).toBe(true);
});

it("signs out without waiting for the public openings refresh", async () => {
  vi.mocked(api.logoutApplicant).mockResolvedValue(new Response(null, { status: 204 }));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.authenticated).toBe(true));
  const openings = deferred<Response>();
  vi.mocked(api.fetchApplicantOpenings).mockReturnValue(openings.promise);
  await act(async () => { expect(await result.current.persistence.signOut()).toBe(true); });
  expect(result.current.persistence.authenticated).toBe(false);
  await act(async () => { openings.resolve(Response.json({ canStartApplication: true, openings: [] })); });
});

it("does not enter review when its save completes after session exit", async () => {
  const saved = deferred<Response>();
  vi.mocked(api.saveApplication).mockReturnValue(saved.promise);
  vi.mocked(api.logoutApplicant).mockResolvedValue(new Response(null, { status: 204 }));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.authenticated).toBe(true));
  let request!: Promise<boolean>;
  act(() => { request = result.current.persistence.saveForReview(); });
  await act(() => result.current.persistence.signOut());
  await act(async () => { saved.resolve(Response.json(application(2))); expect(await request).toBe(false); });
  expect(result.current.persistence.authenticated).toBe(false);
});

it("keeps confirmed sign-out when the background openings refresh fails", async () => {
  vi.mocked(api.logoutApplicant).mockResolvedValue(new Response(null, { status: 204 }));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.authenticated).toBe(true));
  vi.mocked(api.fetchApplicantOpenings).mockRejectedValue(new Error("Synthetic network failure"));
  await act(async () => { expect(await result.current.persistence.signOut()).toBe(true); });
  expect(result.current.persistence.authenticated).toBe(false);
  expect(result.current.persistence.message).not.toBe("");
});

it.each(["stale_application", "pending_copy_changed"])("refreshes the comparison after %s without replacing the local draft", async (code) => {
  const original = { baseRevision: 1, guestSavedAt: "2026-10-03T00:00:00Z",
    savedAnswers: workingAnswers(initialDraft()), savedOpeningIds: [],
    guestAnswers: workingAnswers(initialDraft()), guestOpeningIds: [] };
  const latest = { ...original, baseRevision: 2, guestSavedAt: "2026-10-03T00:00:01Z" };
  vi.mocked(api.fetchPendingCopy).mockResolvedValueOnce(Response.json({ pendingCopy: original }))
    .mockResolvedValueOnce(Response.json({ pendingCopy: latest }));
  vi.mocked(api.reconcilePendingCopy).mockResolvedValue(Response.json({ code, detail: "Compare the current copies again." }, { status: 409 }));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.pendingCopy).toEqual(original));
  act(() => result.current.setDraft((draft) => ({ ...draft, pets: "Unsaved local edit" })));
  await act(() => result.current.persistence.reconcilePendingCopy("guest"));
  expect(api.reconcilePendingCopy).toHaveBeenCalledWith("guest", 1, original.guestSavedAt);
  expect(result.current.persistence.pendingCopy).toEqual(latest);
  expect(result.current.persistence.busy).toBe(false);
  expect(result.current.draft.pets).toBe("Unsaved local edit");
});

it("retains unsaved edits and the acknowledged revision after a failed save, then allows retry", async () => {
  vi.mocked(api.saveApplication).mockRejectedValueOnce(new Error("Synthetic network failure"))
    .mockResolvedValueOnce(Response.json(application(2)));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.authenticated).toBe(true));
  act(() => result.current.setDraft((draft) => ({ ...draft, pets: "Keep this edit" })));
  await act(() => result.current.persistence.start("save"));
  expect(result.current.persistence.phase).toBe("error");
  expect(result.current.persistence.busy).toBe(false);
  expect(result.current.persistence.workingRevision).toBe(1);
  expect(result.current.persistence.hasUnsavedChanges).toBe(true);
  expect(result.current.draft.pets).toBe("Keep this edit");
  await act(() => result.current.persistence.start("save"));
  expect(result.current.persistence.phase).toBe("saved");
  expect(result.current.persistence.workingRevision).toBe(2);
  expect(result.current.persistence.hasUnsavedChanges).toBe(false);
});

it.each(["save", "submit"] as const)("releases a guest %s after network failure without acknowledging its draft", async (intent) => {
  vi.mocked(api.fetchApplication).mockResolvedValue(new Response(null, { status: 401 }));
  vi.mocked(api.savePendingDraft).mockRejectedValue(new Error("Synthetic network failure"));
  vi.mocked(api.submitGuestApplication).mockRejectedValue(new Error("Synthetic network failure"));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.openingsLoaded).toBe(true));
  await act(() => result.current.persistence.start(intent));
  expect(intent === "save" ? api.savePendingDraft : api.submitGuestApplication).toHaveBeenCalledOnce();
  expect(result.current.persistence.busy).toBe(false);
  expect(result.current.persistence.phase).toBe("error");
  expect(result.current.persistence.hasUnsavedChanges).toBe(true);
  expect(result.current.draft.applicant.email).toBe("review@example.com");
});

it("blocks review when its save cannot be confirmed", async () => {
  vi.mocked(api.saveApplication).mockRejectedValue(new Error("Synthetic network failure"));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.authenticated).toBe(true));
  await act(async () => { expect(await result.current.persistence.saveForReview()).toBe(false); });
  expect(result.current.persistence.busy).toBe(false);
});

it("recovers a guest review check that fails before the server responds", async () => {
  vi.mocked(api.fetchApplication).mockResolvedValue(new Response(null, { status: 401 }));
  vi.mocked(api.checkGuestSubmission).mockRejectedValue(new Error("Synthetic network failure"));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.openingsLoaded).toBe(true));
  await act(async () => { expect(await result.current.persistence.prepareGuestReview()).toBe(false); });
  expect(result.current.persistence.busy).toBe(false);
  expect(result.current.persistence.phase).toBe("error");
});

it("keeps an email change available when sending or cancellation fails", async () => {
  vi.mocked(api.requestEmailChange).mockRejectedValueOnce(new Error("Synthetic network failure"))
    .mockResolvedValueOnce(Response.json({ pendingEmail: "new@example.com", emailSent: true, emailStatus: "sent" }));
  vi.mocked(api.cancelEmailChange).mockRejectedValue(new Error("Synthetic network failure"));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.authenticated).toBe(true));
  await act(() => result.current.persistence.beginEmailChange("new@example.com"));
  expect(result.current.persistence.emailChangeStatus).toBe("error");
  expect(result.current.persistence.primaryEmail).toBe("review@example.com");
  await act(() => result.current.persistence.beginEmailChange("new@example.com"));
  await act(async () => { expect(await result.current.persistence.stopEmailChange()).toBe(false); });
  expect(result.current.persistence.pendingEmailChange).toBe("new@example.com");
  expect(result.current.persistence.emailChangeStatus).toBe("error");
});

it.each(["signOut", "withdrawApplication"] as const)("retains the session when %s cannot be confirmed", async (exit) => {
  vi.mocked(api.logoutApplicant).mockRejectedValue(new Error("Synthetic network failure"));
  vi.mocked(api.withdrawApplication).mockRejectedValue(new Error("Synthetic network failure"));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.authenticated).toBe(true));
  await act(async () => { expect(await result.current.persistence[exit]()).toBe(false); });
  expect(result.current.persistence.authenticated).toBe(true);
  expect(result.current.persistence.workingRevision).toBe(1);
  expect(result.current.persistence.busy).toBe(false);
  if (exit === "withdrawApplication") expect(result.current.persistence.withdrawalStatus).toBe("error");
});

it("ignores a save failure arriving after confirmed sign-out", async () => {
  const save = deferred<Response>();
  vi.mocked(api.saveApplication).mockReturnValue(save.promise);
  vi.mocked(api.logoutApplicant).mockResolvedValue(new Response(null, { status: 204 }));
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.authenticated).toBe(true));
  let saving!: Promise<void>;
  act(() => { saving = result.current.persistence.start("save"); });
  await act(() => result.current.persistence.signOut());
  await act(async () => { save.reject(new Error("Synthetic network failure")); await saving; });
  expect(result.current.persistence.authenticated).toBe(false);
  expect(result.current.persistence.phase).toBe("idle");
  expect(result.current.persistence.message).toBe("");
});

it("releases a rejected save when the follow-up lifecycle read also fails", async () => {
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.authenticated).toBe(true));
  vi.mocked(api.saveApplication).mockResolvedValue(Response.json({ code: "applications_closed", detail: "Applications are closed." }, { status: 409 }));
  vi.mocked(api.fetchApplication).mockRejectedValue(new Error("Synthetic network failure"));
  await act(() => result.current.persistence.start("save"));
  expect(result.current.persistence.busy).toBe(false);
  expect(result.current.persistence.phase).toBe("error");
  expect(result.current.persistence.message).toBe("Applications are closed.");
});

it("rejects another application's lifecycle even when its revision matches", async () => {
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.applicationId).toBe(1));
  const originalDraft = result.current.draft;
  vi.mocked(api.fetchApplication).mockResolvedValue(Response.json({ ...application(1), applicationId: 2 }));
  await act(async () => window.dispatchEvent(new Event("focus")));
  expect(result.current.persistence.phase).toBe("session_expired");
  expect(result.current.persistence.applicationId).toBe(1);
  expect(result.current.draft).toEqual(originalDraft);
});

it("resumes the original application after reauthentication without replacing its unsaved answers", async () => {
  const { result } = renderPersistence();
  await waitFor(() => expect(result.current.persistence.applicationId).toBe(1));
  act(() => result.current.setDraft((draft) => ({ ...draft, pets: "Keep this unsaved answer" })));
  vi.mocked(api.fetchApplication).mockResolvedValue(Response.json({ ...application(), applicationId: 2 }));
  await act(async () => window.dispatchEvent(new Event("focus")));
  expect(result.current.persistence.phase).toBe("session_expired");
  vi.mocked(api.fetchApplication).mockResolvedValue(Response.json(application()));
  await act(async () => window.dispatchEvent(new Event("focus")));
  expect(result.current.persistence.phase).toBe("idle");
  expect(result.current.draft.pets).toBe("Keep this unsaved answer");
  expect(result.current.persistence.hasUnsavedChanges).toBe(true);
});
