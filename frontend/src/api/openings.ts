import { type ApiClient, publicClient } from "./client";
import type {
  DirectSelectionOpeningCreate,
  Opening,
  OpeningCreate,
  OpeningPreview,
  OpeningSelection,
  OpeningSelectionCandidate,
  OpeningWrite,
  SocketLabsUsage,
} from "../types";

export function createApi(client: ApiClient) {
  const { getJson, request } = client;
  // --- Openings (admin only) --------------------------------------------------

  const fetchOpenings = () =>
    getJson<{ openings: Opening[] }>("/openings").then((payload) => payload.openings);

  const fetchOpeningEmailUsage = (audienceCount: number) =>
    getJson<SocketLabsUsage>(`/openings/email-usage?audience_count=${audienceCount}`);

  function previewOpening(opening: OpeningCreate): Promise<OpeningPreview> {
    return request("/openings/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(opening),
    }).then(async (response) => {
      if (!response.ok) throw new Error("Could not preview opening.");
      return (await response.json()) as OpeningPreview;
    });
  }

  function createOpening(
    opening: OpeningCreate,
    expectedAudienceCount: number,
    publicationRequestId: string,
  ): Promise<Response> {
    return request("/openings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...opening, expectedAudienceCount, publicationRequestId }),
    });
  }

  function updateOpening(id: number, original: OpeningWrite, changes: OpeningWrite): Promise<Response> {
    return request(`/openings/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ original, changes }),
    });
  }

  const fetchOpeningSelection = (id: number) =>
    getJson<OpeningSelection>(`/openings/${id}/selection`);

  function searchPreviousApplicants(query: string): Promise<OpeningSelectionCandidate[]> {
    return request("/openings/previous-applicants/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    }).then(async (response) => {
      if (!response.ok) throw new Error("Could not search previous applicants.");
      const payload = (await response.json()) as { candidates: OpeningSelectionCandidate[] };
      return payload.candidates;
    });
  }

  function createDirectSelectionOpening(
    opening: DirectSelectionOpeningCreate,
  ): Promise<Response> {
    return request("/openings/direct-selection", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(opening),
    });
  }

  function confirmOpeningSelection(id: number, applicationId: number): Promise<Response> {
    return request(`/openings/${id}/selection`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ applicationId }),
    });
  }

  const confirmNoHouseholdSelected = (id: number) =>
    request(`/openings/${id}/selection/no-household`, { method: "POST" });
  return {
    fetchOpenings, fetchOpeningEmailUsage, previewOpening, createOpening, updateOpening,
    fetchOpeningSelection, searchPreviousApplicants, createDirectSelectionOpening,
    confirmOpeningSelection, confirmNoHouseholdSelected,
  };
}

// Public/bootstrap callers and manual harnesses use the unbound client.
export const {
  fetchOpenings, fetchOpeningEmailUsage, previewOpening, createOpening, updateOpening,
  fetchOpeningSelection, searchPreviousApplicants, createDirectSelectionOpening,
  confirmOpeningSelection, confirmNoHouseholdSelected,
} = createApi(publicClient);
