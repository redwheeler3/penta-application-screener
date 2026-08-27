import type { FeedbackItem } from "../types";
import { getJson, request } from "./client";

// --- Feedback (submit: any member; read/resolve: admin only) ----------------

export function submitFeedback(payload: {
  body: string;
  route: string | null;
  activeTab: string | null;
  analysisId: number | null;
  applicantId: number | null;
}): Promise<Response> {
  return request("/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export const fetchFeedback = (includeResolved: boolean) =>
  getJson<{ items: FeedbackItem[] }>(
    `/feedback${includeResolved ? "?includeResolved=true" : ""}`,
  ).then((p) => p.items);

export const resolveFeedback = (id: number) =>
  request(`/feedback/${id}/resolve`, { method: "POST" });

export const reopenFeedback = (id: number) =>
  request(`/feedback/${id}/reopen`, { method: "POST" });
