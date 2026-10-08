import { type ApiClient } from "./client";
import type { ApplicationDetail, ApplicationSummary, CommitteeOpening } from "../types";

export type ApplicationsResponse = {
  applications: ApplicationSummary[];
  openings: CommitteeOpening[];
  selectedOpeningId: number | null;
};

export function createApi(client: ApiClient) {
  const { getJson, request } = client;
  function fetchApplications(openingId?: number | null): Promise<ApplicationsResponse> {
    const query = openingId == null ? "" : `?opening_id=${openingId}`;
    return getJson<ApplicationsResponse>(`/applications${query}`);
  }

  function fetchApplication(id: number, openingId: number): Promise<ApplicationDetail> {
    return getJson<{ application: ApplicationDetail }>(`/applications/${id}?opening_id=${openingId}`).then((p) => p.application);
  }

  function fetchRetainedApplication(id: number): Promise<ApplicationDetail> {
    return getJson<{ application: ApplicationDetail }>(`/applications/${id}/retained`)
      .then((payload) => payload.application);
  }

  function overrideStatus(id: number, openingId: number, status: string, reviewedFingerprint: string): Promise<Response> {
    return request(`/applications/${id}/status?opening_id=${openingId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, reviewedFingerprint }),
    });
  }

  function clearStatusOverride(id: number, openingId: number): Promise<Response> {
    return request(`/applications/${id}/status?opening_id=${openingId}`, { method: "DELETE" });
  }

  function savePrivateNote(id: number, openingId: number, note: string): Promise<Response> {
    return request(`/applications/${id}/note?opening_id=${openingId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note }),
    });
  }

  function addCommitteeNote(id: number, openingId: number, body: string, creationKey: string): Promise<Response> {
    return request(`/applications/${id}/committee-notes?opening_id=${openingId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body, creationKey }),
    });
  }

  function updateCommitteeNote(
    id: number,
    openingId: number,
    noteId: number,
    body: string,
  ): Promise<Response> {
    return request(`/applications/${id}/committee-notes/${noteId}?opening_id=${openingId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body }),
    });
  }

  function deleteCommitteeNote(
    id: number,
    openingId: number,
    noteId: number,
  ): Promise<Response> {
    return request(`/applications/${id}/committee-notes/${noteId}?opening_id=${openingId}`, {
      method: "DELETE",
    });
  }

  // Toggle the current member's star on an applicant. PUT adds, DELETE removes —
  // the row's existence is the state, so both are idempotent.
  function setStar(id: number, openingId: number, starred: boolean): Promise<Response> {
    return request(`/applications/${id}/star?opening_id=${openingId}`, {
      method: starred ? "PUT" : "DELETE",
    });
  }

  function setShortlist(id: number, openingId: number, shortlisted: boolean): Promise<Response> {
    return request(`/applications/${id}/shortlist?opening_id=${openingId}`, {
      method: shortlisted ? "PUT" : "DELETE",
    });
  }
  return {
    fetchApplications, fetchApplication, fetchRetainedApplication, overrideStatus,
    clearStatusOverride, savePrivateNote, addCommitteeNote, updateCommitteeNote,
    deleteCommitteeNote, setStar, setShortlist,
  };
}
