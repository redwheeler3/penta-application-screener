import type {
  AdminActions,
  Coverage,
  EmailDeliveryIssue,
  SocketLabsQueueStatus,
  WorkflowState,
} from "../types";
import { getJson, request } from "./client";

export const fetchDashboard = (openingId: number) =>
  getJson<{ workflow: WorkflowState; coverage: Coverage; adminActions?: AdminActions | null }>(
    `/dashboard?opening_id=${openingId}`,
  );

export const fetchEmailDeliveryIssues = () =>
  getJson<{ items: EmailDeliveryIssue[]; socketlabs: SocketLabsQueueStatus }>(
    "/dashboard/email-deliveries",
  );

export async function refreshSocketLabsDeliveryStatus() {
  const response = await request("/dashboard/email-deliveries/socketlabs/refresh", {
    method: "POST",
  });
  if (!response.ok) throw new Error(`SocketLabs refresh failed (HTTP ${response.status})`);
  return (await response.json()) as SocketLabsQueueStatus;
}

// The whole pool, unpaginated — the client derives filtering/sorting/facets from it.
