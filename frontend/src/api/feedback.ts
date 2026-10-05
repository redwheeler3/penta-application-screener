import { type ApiClient } from "./client";
import type { FeedbackItem } from "../types";

export function createApi(client: ApiClient) {
  const { request, getJson } = client;
  // --- Feedback (submit: any member; read/resolve: admin only) ----------------

  function submitFeedback(payload: {
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

  const fetchFeedback = (includeResolved: boolean) =>
    getJson<{ items: FeedbackItem[] }>(
      `/feedback${includeResolved ? "?includeResolved=true" : ""}`,
    ).then((p) => p.items);

  const resolveFeedback = (id: number) =>
    request(`/feedback/${id}/resolve`, { method: "POST" });

  const reopenFeedback = (id: number) =>
    request(`/feedback/${id}/reopen`, { method: "POST" });
  return {
    submitFeedback, fetchFeedback, resolveFeedback, reopenFeedback,
  };
}
