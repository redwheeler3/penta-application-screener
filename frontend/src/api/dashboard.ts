import type { AdminActions, Coverage, EmailDeliveryIssue, WorkflowState } from "../types";
import { getJson } from "./client";

export const fetchDashboard = () =>
  getJson<{ workflow: WorkflowState; coverage: Coverage; adminActions?: AdminActions | null }>(
    "/dashboard",
  );

export const fetchEmailDeliveryIssues = () =>
  getJson<{ items: EmailDeliveryIssue[] }>("/dashboard/email-deliveries");

// The whole pool, unpaginated — the client derives filtering/sorting/facets from it.
