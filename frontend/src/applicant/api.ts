import { request } from "../api/client";
import type { CanonicalApplicationAnswers, WorkingApplicationAnswers } from "./types";

export function fetchApplicantOpenings() {
  return request("/applicant/openings");
}

export function checkGuestSubmission(
  answers: WorkingApplicationAnswers,
  openingIds: number[],
) {
  return request(
    "/applicant/submissions/check",
    jsonRequest("POST", { answers, openingIds }),
  );
}

export type DraftIntent = "save" | "submit";

export function savePendingDraft(
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

export function deletePendingDraft(draftToken: string) {
  return request("/applicant/drafts", jsonRequest("DELETE", { token: draftToken }));
}

export function inspectAccessLink(token: string) {
  return request("/applicant/access-links/inspect", jsonRequest("POST", { token }));
}

export function openAccessLink(token: string, switchCurrent: boolean, rememberDevice: boolean) {
  return request(
    "/applicant/access-links/open",
    jsonRequest("POST", { token, switchCurrent, rememberDevice }),
  );
}

export function regenerateAccessLink(token: string) {
  return request(
    "/applicant/access-links/regenerate",
    jsonRequest("POST", { token }),
  );
}

export function requestReturnAccessLink(
  answers: WorkingApplicationAnswers,
  openingIds: number[],
  baseRevision: number | null,
) {
  return request(
    "/applicant/access-links/request",
    jsonRequest("POST", { answers, openingIds, baseRevision }),
  );
}

export function fetchApplication() {
  return request("/applicant/application");
}

export function fetchPendingCopy() {
  return request("/applicant/application/pending-copy");
}

export function reconcilePendingCopy(choice: "saved" | "guest") {
  return request(
    "/applicant/application/pending-copy",
    jsonRequest("POST", { choice }),
  );
}

export function requestEmailChange(newEmail: string) {
  return request(
    "/applicant/application/email-change",
    jsonRequest("POST", { newEmail }),
  );
}

export function cancelEmailChange() {
  return request("/applicant/application/email-change", { method: "DELETE" });
}

export function requestApplicantReauthentication() {
  return request(
    "/applicant/application/reauthentication",
    { method: "POST" },
  );
}

export function logoutApplicant() {
  return request("/applicant/auth/logout", { method: "POST" });
}

export function saveApplication(
  answers: WorkingApplicationAnswers,
  openingIds: number[],
  baseRevision: number,
) {
  return request(
    "/applicant/application",
    jsonRequest("PUT", { answers, openingIds, baseRevision }),
  );
}

export function revertApplication(baseRevision: number) {
  return request(
    "/applicant/application/revert",
    jsonRequest("POST", { baseRevision }),
  );
}

export function deleteApplication() {
  return request("/applicant/application", { method: "DELETE" });
}

export function submitApplication(
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

export function submitGuestApplication(
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
