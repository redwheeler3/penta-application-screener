import type { Opening, OpeningSelection, OpeningWrite } from "../types";
import { getJson, request } from "./client";

// --- Openings (admin only) --------------------------------------------------

export const fetchOpenings = () =>
  getJson<{ openings: Opening[] }>("/openings").then((payload) => payload.openings);

export function createOpening(opening: OpeningWrite): Promise<Response> {
  return request("/openings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(opening),
  });
}

export function updateOpening(id: number, opening: OpeningWrite): Promise<Response> {
  return request(`/openings/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(opening),
  });
}

export const publishOpening = (id: number) =>
  request(`/openings/${id}/publish`, { method: "POST" });

export const fetchOpeningSelection = (id: number) =>
  getJson<OpeningSelection>(`/openings/${id}/selection`);

export function confirmOpeningSelection(id: number, applicationId: number): Promise<Response> {
  return request(`/openings/${id}/selection`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ applicationId }),
  });
}

export const confirmNoHouseholdSelected = (id: number) =>
  request(`/openings/${id}/selection/no-household`, { method: "POST" });

export const undoOpeningSelection = (id: number) =>
  request(`/openings/${id}/selection`, { method: "DELETE" });

