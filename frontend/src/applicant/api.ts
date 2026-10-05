import { url } from "../api/client";

import type { CanonicalApplicationAnswers, WorkingApplicationAnswers } from "./types";

const APPLICANT_GOOGLE_ACCESS_RESULTS = [
  "denied",
  "identity_conflict",
  "applications_closed",
  "selected",
  "session_conflict",
] as const;

export type ApplicantGoogleAccessResult = typeof APPLICANT_GOOGLE_ACCESS_RESULTS[number];

export type DraftIntent = "save" | "submit";
import { type ApiClient, credentialRequest, publicClient, signalSessionChange } from "../api/client";

export function createApi(client: ApiClient) {
  const { request } = client;
  function fetchApplicantOpenings(signal?: AbortSignal) {
    return request("/applicant/openings", { signal });
  }

  function applicantGoogleSignInUrl(rememberDevice = false): string {
    return url(`/applicant/auth/google/login?remember_device=${rememberDevice}`);
  }

  function isApplicantGoogleAccessResult(value: string): value is ApplicantGoogleAccessResult {
    return APPLICANT_GOOGLE_ACCESS_RESULTS.some((result) => result === value);
  }

  function takeApplicantGoogleAccessResult(): ApplicantGoogleAccessResult | null {
    const query = new URLSearchParams(window.location.search);
    const value = query.get("google_access");
    if (value === null) return null;
    query.delete("google_access");
    const remaining = query.toString();
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${remaining ? `?${remaining}` : ""}${window.location.hash}`,
    );
    return isApplicantGoogleAccessResult(value) ? value : null;
  }

  function checkGuestSubmission(
    answers: WorkingApplicationAnswers,
    openingIds: number[],
  ) {
    return request(
      "/applicant/submissions/check",
      jsonRequest("POST", { answers, openingIds }),
    );
  }

  function savePendingDraft(
    answers: WorkingApplicationAnswers,
    intent: DraftIntent,
    draftToken: string | null,
    openingIds: number[],
  ) {
    return request("/applicant/drafts", jsonRequest("POST", {
      answers,
      intent,
      draftToken,
      openingIds,
    }));
  }

  function deletePendingDraft(draftToken: string) {
    return request("/applicant/drafts", jsonRequest("DELETE", { token: draftToken }));
  }

  function inspectAccessLink(token: string) {
    return request("/applicant/access-links/inspect", jsonRequest("POST", { token }));
  }

  function openAccessLink(token: string, switchCurrent: boolean, rememberDevice: boolean) {
    return credentialRequest("applicant",
      "/applicant/access-links/open",
      jsonRequest("POST", { token, switchCurrent, rememberDevice }), client,
    );
  }

  function regenerateAccessLink(token: string) {
    return request(
      "/applicant/access-links/regenerate",
      jsonRequest("POST", { token }),
    );
  }

  function requestReturnAccessLink(
    answers: WorkingApplicationAnswers,
    openingIds: number[],
    baseRevision: number | null,
  ) {
    return request(
      "/applicant/access-links/request",
      jsonRequest("POST", { answers, openingIds, baseRevision }),
    );
  }

  function fetchApplication(signal?: AbortSignal) {
    return request("/applicant/application", { signal });
  }

  function fetchPendingCopy() {
    return request("/applicant/application/pending-copy");
  }

  function reconcilePendingCopy(choice: "saved" | "guest", baseRevision: number, guestSavedAt: string) {
    return request(
      "/applicant/application/pending-copy",
      jsonRequest("POST", { choice, baseRevision, guestSavedAt }),
    );
  }

  function requestEmailChange(newEmail: string) {
    return request(
      "/applicant/application/email-change",
      jsonRequest("POST", { newEmail }),
    );
  }

  function cancelEmailChange() {
    return request("/applicant/application/email-change", { method: "DELETE" });
  }

  async function logoutApplicant() {
    const response = await request("/applicant/auth/logout", { method: "POST" });
    if (response.ok) signalSessionChange("applicant");
    return response;
  }

  function saveApplication(
    answers: WorkingApplicationAnswers,
    openingIds: number[],
    baseRevision: number,
  ) {
    return request(
      "/applicant/application",
      jsonRequest("PUT", { answers, openingIds, baseRevision }),
    );
  }

  function withdrawApplication() {
    return request("/applicant/application/withdraw", { method: "POST" });
  }

  function submitApplication(
    answers: CanonicalApplicationAnswers,
    declarationAccepted: boolean,
    openingIds: number[],
    baseRevision: number,
  ) {
    return request(
      "/applicant/application/submit",
      jsonRequest("POST", { answers, declarationAccepted, openingIds, baseRevision }),
    );
  }

  function submitGuestApplication(
    answers: CanonicalApplicationAnswers,
    declarationAccepted: boolean,
    openingIds: number[],
    draftToken: string | null,
  ) {
    return request(
      "/applicant/submissions",
      jsonRequest("POST", { answers, declarationAccepted, openingIds, draftToken }),
    );
  }

  function jsonRequest(method: string, body: object): RequestInit {
    return {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    };
  }
  return {
    fetchApplicantOpenings, applicantGoogleSignInUrl, takeApplicantGoogleAccessResult,
    checkGuestSubmission, savePendingDraft, deletePendingDraft, inspectAccessLink, openAccessLink,
    regenerateAccessLink, requestReturnAccessLink, fetchApplication, fetchPendingCopy,
    reconcilePendingCopy, requestEmailChange, cancelEmailChange, logoutApplicant, saveApplication,
    withdrawApplication, submitApplication, submitGuestApplication,
  };
}

// Public/bootstrap callers and manual harnesses use the unbound client.
export const {
  fetchApplicantOpenings, applicantGoogleSignInUrl, takeApplicantGoogleAccessResult,
  checkGuestSubmission, savePendingDraft, deletePendingDraft, inspectAccessLink, openAccessLink,
  regenerateAccessLink, requestReturnAccessLink, fetchApplication, fetchPendingCopy,
  reconcilePendingCopy, requestEmailChange, cancelEmailChange, logoutApplicant, saveApplication,
  withdrawApplication, submitApplication, submitGuestApplication,
} = createApi(publicClient);
