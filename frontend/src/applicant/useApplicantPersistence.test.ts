import { act, renderHook, waitFor } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import { deferred } from "../testSupport";
import * as api from "./api";
import type { ApplicationResponse } from "./applicantPersistence";
import { emptyApplicantDraft, workingAnswers } from "./types";
import { useApplicantPersistence } from "./useApplicantPersistence";

vi.mock("./api", async (original) => ({
  ...await original<typeof import("./api")>(),
  fetchApplication: vi.fn(), fetchPendingCopy: vi.fn(), fetchApplicantOpenings: vi.fn(),
  saveApplication: vi.fn(), savePendingDraft: vi.fn(), submitGuestApplication: vi.fn(),
  requestReturnAccessLink: vi.fn(), logoutApplicant: vi.fn(),
}));

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
    emailed.resolve(Response.json({ currentAnswersSaved: true, emailStatus: "sent" })); await request;
  });
  expect(result.current.persistence.hasUnsavedChanges).toBe(true);
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
