import { type ApiClient } from "./client";
import type {
  AdminActions,
  Coverage,
  EmailDeliveryIssue,
  SocketLabsQueueStatus,
  WorkflowState,
} from "../types";

export function createApi(client: ApiClient) {
  const { getJson, request } = client;
  const fetchDashboard = (openingId: number) =>
    getJson<{ workflow: WorkflowState; coverage: Coverage; adminActions?: AdminActions | null }>(
      `/dashboard?opening_id=${openingId}`,
    );

  const fetchEmailDeliveryIssues = () =>
    getJson<{ items: EmailDeliveryIssue[]; socketlabs: SocketLabsQueueStatus }>(
      "/dashboard/email-deliveries",
    );

  async function refreshSocketLabsDeliveryStatus() {
    const response = await request("/dashboard/email-deliveries/socketlabs/refresh", {
      method: "POST",
    });
    if (!response.ok) throw new Error(`SocketLabs refresh failed (HTTP ${response.status})`);
    return (await response.json()) as SocketLabsQueueStatus;
  }
  return {
    fetchDashboard, fetchEmailDeliveryIssues, refreshSocketLabsDeliveryStatus,
  };
}
