import type { AdminActions, Coverage, EmailDeliveryIssue, WorkflowState } from "../types";
import { getJson } from "./client";

export const fetchDashboard = (openingId: number) =>
  getJson<{ workflow: WorkflowState; coverage: Coverage; adminActions?: AdminActions | null }>(
    `/dashboard?opening_id=${openingId}`,
  );

export const fetchEmailDeliveryIssues = () =>
  getJson<{ items: EmailDeliveryIssue[] }>("/dashboard/email-deliveries");

// The whole pool, unpaginated — the client derives filtering/sorting/facets from it.
