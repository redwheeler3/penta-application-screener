import type { ApplicationDetail, ApplicationSummary, CommitteeOpening } from "../types";
import { getJson, request } from "./client";

export type ApplicationsResponse = {
  applications: ApplicationSummary[];
  openings: CommitteeOpening[];
  selectedOpeningId: number | null;
};

export function fetchApplications(openingId?: number | null): Promise<ApplicationsResponse> {
  const query = openingId == null ? "" : `?opening_id=${openingId}`;
  return getJson<ApplicationsResponse>(`/applications${query}`);
}

export function fetchApplication(id: number, openingId: number): Promise<ApplicationDetail> {
  return getJson<{ application: ApplicationDetail }>(`/applications/${id}?opening_id=${openingId}`).then((p) => p.application);
}

export function fetchRetainedApplication(id: number): Promise<ApplicationDetail> {
  return getJson<{ application: ApplicationDetail }>(`/applications/${id}/retained`)
    .then((payload) => payload.application);
}


export function overrideStatus(id: number, openingId: number, status: string): Promise<Response> {
  return request(`/applications/${id}/status?opening_id=${openingId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
}

export function clearStatusOverride(id: number, openingId: number): Promise<Response> {
  return request(`/applications/${id}/status?opening_id=${openingId}`, { method: "DELETE" });
}

export function savePrivateNote(id: number, openingId: number, note: string): Promise<Response> {
  return request(`/applications/${id}/note?opening_id=${openingId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note }),
  });
}

// Toggle the current member's star on an applicant. PUT adds, DELETE removes —
// the row's existence is the state, so both are idempotent.
export function setStar(id: number, openingId: number, starred: boolean): Promise<Response> {
  return request(`/applications/${id}/star?opening_id=${openingId}`, {
    method: starred ? "PUT" : "DELETE",
  });
}

export function setShortlist(id: number, openingId: number, shortlisted: boolean): Promise<Response> {
  return request(`/applications/${id}/shortlist?opening_id=${openingId}`, {
    method: shortlisted ? "PUT" : "DELETE",
  });
}
