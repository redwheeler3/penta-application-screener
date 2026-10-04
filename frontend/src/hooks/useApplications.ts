import { useCallback, useMemo, useRef, useState } from "react";
import * as api from "../api/applications";
import { retryWithBackoff } from "../retry";
import type {
  AppFacets,
  AppFilter,
  ApplicationSummary,
  CommitteeOpening,
  SortKey,
  SortState,
} from "../types";
import { deriveApplicationFacets, selectApplications } from "./applicationSelectors";
import { useRequestScope } from "./useRequestScope";

export interface ApplicationsState {
  /** The filtered + sorted list the UI renders (derived from the full pool). */
  applications: ApplicationSummary[];
  openings: CommitteeOpening[];
  selectedOpeningId: number | null;
  /** Distinguishes initial loading, a settled list (including an empty one), and a
   * definitively failed initial load. */
  applicationsLoadState: "loading" | "ready" | "error";
  /** Facet counts (status/source/saved views) derived from the full pool, each
   * reflecting the OTHER active filters so the groups stay consistent. */
  appFacets: AppFacets;
  appFilter: AppFilter;
  appSearch: string;
  appSort: SortState;
  /** (Re)fetch the whole pool. Called after screen/override or by the intake refresh so the list reflects
   * server truth; filtering/sorting then happen client-side with no further fetches. */
  reloadApplications: () => Promise<void>;
  /** Recover the initial list load after its automatic retries were exhausted. */
  loadInitialApplications: () => Promise<void>;
  toggleSort: (key: SortKey) => void;
  applyFilter: (next: AppFilter) => void;
  selectOpening: (openingId: number) => Promise<boolean>;
  search: (value: string) => void;
}

/** The applications-list view state. The whole pool (a few hundred rows at most) is held
 * client-side; filtering, sorting, opening scope, and facet counts are derived here with no server
 * round-trips — so a filter/sort/saved-view change is instant. Only a data-changing
 * action (screen, status override, star, shortlist) triggers a refetch. The selected
 * candidate detail is NOT here: it's cross-cutting (tab switches, overrides, settings
 * save all clear it), so it stays in App. */
export function useApplications(): ApplicationsState {
  const [allApplications, setAllApplications] = useState<ApplicationSummary[]>([]);
  const [openings, setOpenings] = useState<CommitteeOpening[]>([]);
  const [selectedOpeningId, setSelectedOpeningId] = useState<number | null>(null);
  const [applicationsLoadState, setApplicationsLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [appFilter, setAppFilter] = useState<AppFilter>({});
  const [appSearch, setAppSearch] = useState("");
  const [appSort, setAppSort] = useState<SortState>(null);
  const requests = useRequestScope();
  const selectingOpening = useRef(false);
  const selectedOpeningRef = useRef(selectedOpeningId);
  selectedOpeningRef.current = selectedOpeningId;

  const acceptApplications = useCallback((response: Awaited<ReturnType<typeof api.fetchApplications>>) => {
    setAllApplications(response.applications);
    setOpenings(response.openings);
    setSelectedOpeningId(response.selectedOpeningId);
    selectedOpeningRef.current = response.selectedOpeningId;
    try {
      if (response.selectedOpeningId !== null) {
        window.localStorage.setItem("penta-selected-opening", String(response.selectedOpeningId));
      }
    } catch { /* The optional browser preference must not fail a loaded workspace. */ }
    setApplicationsLoadState("ready");
  }, []);

  const reloadApplications = useCallback(() => {
    if (selectingOpening.current) return Promise.resolve();
    const isCurrent = requests.begin();
    return api
      .fetchApplications(selectedOpeningRef.current)
      .then((response) => {
        if (isCurrent()) acceptApplications(response);
      })
      // Keep the last successful list visible when a background refresh fails. Initial loading
      // uses loadInitialApplications so it can recover deliberately instead of spinning forever.
      .catch(() => {});
  }, [acceptApplications, requests]);

  const loadInitialApplications = useCallback(async (): Promise<void> => {
    setApplicationsLoadState("loading");
    const isCurrent = requests.begin();
    selectingOpening.current = true;
    try {
      let stored = 0;
      try { stored = Number(window.localStorage.getItem("penta-selected-opening")); }
      catch { /* Let the server choose an opening when browser storage is denied. */ }
      const requestedOpening = Number.isInteger(stored) && stored > 0 ? stored : null;
      const response = await retryWithBackoff(
        () => api.fetchApplications(requestedOpening),
        5,
      );
      if (isCurrent()) acceptApplications(response);
    } catch {
      if (isCurrent()) setApplicationsLoadState("error");
    } finally {
      if (isCurrent()) selectingOpening.current = false;
    }
  }, [acceptApplications, requests]);

  // Everything below is derived from the full pool — no fetch on filter/sort/search.
  const appFacets = useMemo<AppFacets>(
    () => deriveApplicationFacets(allApplications, appFilter, appSearch),
    [allApplications, appFilter, appSearch],
  );

  const applications = useMemo(
    () => selectApplications(allApplications, appFilter, appSearch, appSort),
    [allApplications, appFilter, appSearch, appSort],
  );

  async function selectOpening(openingId: number): Promise<boolean> {
    const isCurrent = requests.begin();
    selectingOpening.current = true;
    setApplicationsLoadState("loading");
    try {
      const response = await api.fetchApplications(openingId);
      if (!isCurrent()) return false;
      acceptApplications(response);
      return true;
    } catch (error) {
      if (!isCurrent()) return false;
      setApplicationsLoadState("ready");
      throw error;
    } finally {
      if (isCurrent()) selectingOpening.current = false;
    }
  }

  function toggleSort(key: SortKey) {
    // First click sorts ascending; clicking the active column flips direction.
    setAppSort((prev) =>
      prev?.key === key
        ? { key, direction: prev.direction === "asc" ? "desc" : "asc" }
        : { key, direction: "asc" },
    );
  }

  return {
    applications,
    openings,
    selectedOpeningId,
    applicationsLoadState,
    appFacets,
    appFilter,
    appSearch,
    appSort,
    reloadApplications,
    loadInitialApplications,
    toggleSort,
    applyFilter: setAppFilter,
    selectOpening,
    search: setAppSearch,
  };
}
