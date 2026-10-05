import { useCommitteeApi } from "../api/identity";
import { useCallback, useState } from "react";

import * as dashboardApi from "../api/dashboard";
import { retryWithBackoff } from "../retry";
import type { AdminActions, Coverage, WorkflowState } from "../types";
import { useRequestScope } from "./useRequestScope";

const EMPTY_WORKFLOW: WorkflowState = {
  applicationsAvailable: false,
  screened: false,
  patternsDiscovered: false,
  candidatesScored: false,
  rankingCurrent: false,
};

export function useDashboard(openingId: number | null) {
  const api = useCommitteeApi(dashboardApi);

  const [workflow, setWorkflow] = useState<WorkflowState>(EMPTY_WORKFLOW);
  const [coverage, setCoverage] = useState<Coverage>({});
  const [adminActions, setAdminActions] = useState<AdminActions | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const requests = useRequestScope(openingId);

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
    if (openingId === null || !requests.isFor(openingId)) return Promise.resolve();
    const isCurrent = requests.begin();
    return api.fetchDashboard(openingId).then((payload) => {
      if (isCurrent()) apply(payload);
    }).catch(() => {});
  }, [apply, openingId, requests, api]);

  const loadInitial = useCallback(async (): Promise<void> => {
    if (!requests.isFor(openingId)) return;
    setLoadState("loading");
    if (openingId === null) return;
    const isCurrent = requests.begin();
    try {
      const payload = await retryWithBackoff(() => api.fetchDashboard(openingId), 5);
      if (isCurrent()) apply(payload);
    } catch {
      if (isCurrent()) setLoadState("error");
    }
  }, [apply, openingId, requests, api]);

  return { workflow, coverage, adminActions, loadState, refresh, loadInitial };
}
