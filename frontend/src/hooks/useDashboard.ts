import { useCallback, useState } from "react";

import * as api from "../api";
import { retryWithBackoff } from "../retry";
import type { AdminActions, Coverage, WorkflowState } from "../types";

const EMPTY_WORKFLOW: WorkflowState = {
  applicationsAvailable: false,
  screened: false,
  patternsDiscovered: false,
  candidatesScored: false,
  rankingCurrent: false,
};

export function useDashboard() {
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
    return api.fetchDashboard().then(apply).catch(() => {});
  }, [apply]);

  const loadInitial = useCallback(async (): Promise<void> => {
    setLoadState("loading");
    try {
      apply(await retryWithBackoff(api.fetchDashboard, 5));
    } catch {
      setLoadState("error");
    }
  }, [apply]);

  return { workflow, coverage, adminActions, loadState, refresh, loadInitial };
}
