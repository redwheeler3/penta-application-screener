import type { AdminActions, Coverage, WorkflowState } from "../types";
import { getJson } from "./client";

export const fetchDashboard = () =>
  getJson<{ workflow: WorkflowState; coverage: Coverage; adminActions?: AdminActions | null }>(
    "/dashboard",
  );

// The whole pool, unpaginated — the client derives filtering/sorting/facets from it.
