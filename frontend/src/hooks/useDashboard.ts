import { useCallback, useState } from "react";

import * as api from "../api/dashboard";
import { retryWithBackoff } from "../retry";
import type { AdminActions, Coverage, WorkflowState } from "../types";

const EMPTY_WORKFLOW: WorkflowState = {
  applicationsAvailable: false,
  screened: false,
  patternsDiscovered: false,
  candidatesScored: false,
  rankingCurrent: false,
};

export function useDashboard(openingId: number | null) {
  const [workflow, setWorkflow] = useState<WorkflowState>(EMPTY_WORKFLOW);
  const [coverage, setCoverage] = useState<Coverage>({});
  const [adminActions, setAdminActions] = useState<AdminActions | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");

  const apply = useCallback((payload: {
    workflow: WorkflowState;
    coverage?: Coverage;
    adminActions?: AdminActions | null;
  }) => {
    setWorkflow(payload.workflow);
    setCoverage(payload.coverage ?? {});
    setAdminActions(payload.adminActions ?? null);
    setLoadState("ready");
  }, []);

  const refresh = useCallback(() => {
    if (openingId === null) return Promise.resolve();
    return api.fetchDashboard(openingId).then(apply).catch(() => {});
  }, [apply, openingId]);

  const loadInitial = useCallback(async (): Promise<void> => {
    setLoadState("loading");
    if (openingId === null) return;
    try {
      apply(await retryWithBackoff(() => api.fetchDashboard(openingId), 5));
    } catch {
      setLoadState("error");
    }
  }, [apply, openingId]);

  return { workflow, coverage, adminActions, loadState, refresh, loadInitial };
}
