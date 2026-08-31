import type { ApplicationDetail, ApplicationSummary, CommitteeOpening } from "../types";
import { getJson, request } from "./client";

export type ApplicationsResponse = {
  applications: ApplicationSummary[];
  openings: CommitteeOpening[];
};

export function fetchApplications(): Promise<ApplicationsResponse> {
  return getJson<ApplicationsResponse>("/applications");
}

export function fetchApplication(id: number): Promise<ApplicationDetail> {
  return getJson<{ application: ApplicationDetail }>(`/applications/${id}`).then((p) => p.application);
}

export function fetchRetainedApplication(id: number): Promise<ApplicationDetail> {
  return getJson<{ application: ApplicationDetail }>(`/applications/${id}/retained`)
    .then((payload) => payload.application);
}


export function overrideStatus(id: number, status: string): Promise<Response> {
  return request(`/applications/${id}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
}

export function clearStatusOverride(id: number): Promise<Response> {
  return request(`/applications/${id}/status`, { method: "DELETE" });
}

export function savePrivateNote(id: number, note: string): Promise<Response> {
  return request(`/applications/${id}/note`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note }),
  });
}

// Toggle the current member's star on an applicant. PUT adds, DELETE removes —
// the row's existence is the state, so both are idempotent.
export function setStar(id: number, starred: boolean): Promise<Response> {
  return request(`/applications/${id}/star`, {
    method: starred ? "PUT" : "DELETE",
  });
}

export function setShortlist(id: number, shortlisted: boolean): Promise<Response> {
  return request(`/applications/${id}/shortlist`, {
    method: shortlisted ? "PUT" : "DELETE",
  });
}
