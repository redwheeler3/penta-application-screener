import { useState } from "react";

import * as api from "../api";
import { retryWithBackoff } from "../retry";
import type { Coverage, DashboardCounts, WorkflowState } from "../types";

const EMPTY_COUNTS: DashboardCounts = {
  submitted: 0,
  status: { eligible: 0, ineligible: 0 },
  source: { untouched: 0, rules: 0, ai: 0, human: 0 },
};

const EMPTY_WORKFLOW: WorkflowState = {
  synced: false,
  importCurrent: true,
  screened: false,
  patternsDiscovered: false,
  candidatesScored: false,
  rankingCurrent: false,
};

export function useDashboard() {
  const [counts, setCounts] = useState<DashboardCounts>(EMPTY_COUNTS);
  const [workflow, setWorkflow] = useState<WorkflowState>(EMPTY_WORKFLOW);
  const [coverage, setCoverage] = useState<Coverage>({});
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");

  function apply(payload: {
    counts: DashboardCounts;
    workflow: WorkflowState;
    coverage?: Coverage;
  }) {
    setCounts(payload.counts);
    setWorkflow(payload.workflow);
    setCoverage(payload.coverage ?? {});
    setLoadState("ready");
  }

  function refresh() {
    api.fetchDashboard().then(apply).catch(() => {});
  }

  async function loadInitial(): Promise<void> {
    setLoadState("loading");
    try {
      apply(await retryWithBackoff(api.fetchDashboard, 5));
    } catch {
      setLoadState("error");
    }
  }

  return { counts, workflow, coverage, loadState, refresh, loadInitial };
}
