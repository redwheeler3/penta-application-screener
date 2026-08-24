import { request } from "../api";
import type { CanonicalApplicationAnswers, WorkingApplicationAnswers } from "./types";

export type DraftIntent = "save" | "submit";

export function savePendingDraft(
  answers: WorkingApplicationAnswers,
  intent: DraftIntent,
  draftToken: string | null,
) {
  return request("/applicant/drafts", jsonRequest("POST", {
    answers,
    intent,
    draftToken,
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

export function requestReturnAccessLink(answers: WorkingApplicationAnswers) {
  return request(
    "/applicant/access-links/request",
    jsonRequest("POST", { answers }),
  );
}

export function fetchApplication() {
  return request("/applicant/application");
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

export function saveApplication(answers: WorkingApplicationAnswers) {
  return request("/applicant/application", jsonRequest("PUT", { answers }));
}

export function submitApplication(
  answers: CanonicalApplicationAnswers,
  declarationAccepted: boolean,
) {
  return request(
    "/applicant/application/submit",
    jsonRequest("POST", { answers, declarationAccepted }),
  );
}

function jsonRequest(method: string, body: object): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}
