import { useCallback, useMemo, useState } from "react";
import * as api from "../api";
import { retryWithBackoff } from "../retry";
import type {
  AppFacets,
  AppFilter,
  ApplicationSummary,
  CommitteeOpening,
  SortKey,
  SortState,
} from "../types";

export interface ApplicationsState {
  /** The filtered + sorted list the UI renders (derived from the full pool). */
  applications: ApplicationSummary[];
  openings: CommitteeOpening[];
  selectedOpeningIds: number[];
  /** Shared opening scope consumed by both this list and the ranking view. */
  applicationIdsInOpeningScope: Set<number>;
  /** Distinguishes initial loading, a settled list (including an empty one), and a
   * definitively failed initial load. */
  applicationsLoadState: "loading" | "ready" | "error";
  /** Facet counts (status/source/favourites) derived from the full pool, each
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
  setSelectedOpeningIds: (openingIds: number[]) => void;
  search: (value: string) => void;
}

/** The applications-list view state. The whole pool (a few hundred rows at most) is held
 * client-side; filtering, sorting, opening scope, and facet counts are derived here with no server
 * round-trips — so a filter/sort/favourites toggle is instant. Only a data-changing
 * action (screen, status override, star) triggers a refetch. The selected
 * candidate detail is NOT here: it's cross-cutting (tab switches, overrides, settings
 * save all clear it), so it stays in App. */
export function useApplications(): ApplicationsState {
  const [allApplications, setAllApplications] = useState<ApplicationSummary[]>([]);
  const [openings, setOpenings] = useState<CommitteeOpening[]>([]);
  const [selectedOpeningIds, setSelectedOpeningIds] = useState<number[]>([]);
  const [applicationsLoadState, setApplicationsLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [appFilter, setAppFilter] = useState<AppFilter>({});
  const [appSearch, setAppSearch] = useState("");
  const [appSort, setAppSort] = useState<SortState>(null);

  const acceptApplications = useCallback((response: Awaited<ReturnType<typeof api.fetchApplications>>) => {
    setAllApplications(response.applications);
    setOpenings(response.openings);
    const currentOpeningIds = new Set(
      response.openings
        .filter((opening) => opening.phase !== "archived")
        .map((opening) => opening.id),
    );
    setSelectedOpeningIds((selected) => (
      selected.filter((openingId) => currentOpeningIds.has(openingId))
    ));
    setApplicationsLoadState("ready");
  }, []);

  const reloadApplications = useCallback(() => {
    return api
      .fetchApplications()
      .then((response) => {
        acceptApplications(response);
      })
      // Keep the last successful list visible when a background refresh fails. Initial loading
      // uses loadInitialApplications so it can recover deliberately instead of spinning forever.
      .catch(() => {});
  }, [acceptApplications]);

  const loadInitialApplications = useCallback(async (): Promise<void> => {
    setApplicationsLoadState("loading");
    try {
      const response = await retryWithBackoff(api.fetchApplications, 5);
      acceptApplications(response);
    } catch {
      setApplicationsLoadState("error");
    }
  }, [acceptApplications]);

  // Everything below is derived from the full pool — no fetch on filter/sort/search.
  const searchTerm = appSearch.trim().toLowerCase();
  const matchesSearch = (a: ApplicationSummary) =>
    !searchTerm ||
    [a.applicantName, a.coApplicantName, a.primaryEmail].some((v) =>
      (v ?? "").toLowerCase().includes(searchTerm),
    );
  const matchesOpening = (a: ApplicationSummary) =>
    selectedOpeningIds.length === 0 ||
    selectedOpeningIds.some((openingId) => a.openingIds.includes(openingId));
  const applicationIdsInOpeningScope = useMemo(
    () => new Set(allApplications.filter(matchesOpening).map((application) => application.id)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [allApplications, selectedOpeningIds],
  );

  // Facets reflect every active filter EXCEPT their own group (like the server did),
  // so the two filter rows stay mutually consistent. Search + favourites apply to both.
  const appFacets = useMemo<AppFacets>(() => {
    const base = allApplications.filter(
      (application) => matchesSearch(application) && matchesOpening(application),
    );
    const favBase = appFilter.favourites ? base.filter((a) => a.starredByMe) : base;
    const status: Record<string, number> = { eligible: 0, ineligible: 0 };
    const source: Record<string, number> = { untouched: 0, rules: 0, ai: 0, human: 0 };
    // Status facet ignores the status filter but honours source (+ search/favourites).
    for (const a of favBase.filter(
      (a) => !appFilter.statusSource || a.statusSource === appFilter.statusSource,
    )) {
      status[a.status] = (status[a.status] ?? 0) + 1;
    }
    // Source facet ignores the source filter but honours status (+ search/favourites).
    for (const a of favBase.filter((a) => !appFilter.status || a.status === appFilter.status)) {
      source[a.statusSource] = (source[a.statusSource] ?? 0) + 1;
    }
    // Favourites count ignores the favourites filter but honours status + source.
    const favourites = base.filter(
      (a) =>
        a.starredByMe &&
        (!appFilter.status || a.status === appFilter.status) &&
        (!appFilter.statusSource || a.statusSource === appFilter.statusSource),
    ).length;
    return {
      status: status as AppFacets["status"],
      source: source as AppFacets["source"],
      favourites,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allApplications, appFilter, searchTerm, selectedOpeningIds]);

  const applications = useMemo(() => {
    const filtered = allApplications.filter(
      (a) =>
        matchesSearch(a) &&
        (!appFilter.status || a.status === appFilter.status) &&
        (!appFilter.statusSource || a.statusSource === appFilter.statusSource) &&
        (!appFilter.favourites || a.starredByMe) &&
        matchesOpening(a),
    );
    return appSort ? sortApplications(filtered, appSort) : filtered;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allApplications, appFilter, searchTerm, appSort, selectedOpeningIds]);

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
    selectedOpeningIds,
    applicationIdsInOpeningScope,
    applicationsLoadState,
    appFacets,
    appFilter,
    appSearch,
    appSort,
    reloadApplications,
    loadInitialApplications,
    toggleSort,
    applyFilter: setAppFilter,
    setSelectedOpeningIds,
    search: setAppSearch,
  };
}

// Sort keys map to a comparable value; missing values sort last in both directions.
const SORT_VALUE: Record<SortKey, (a: ApplicationSummary) => string | number | null> = {
  applicant: (a) => a.applicantName,
  co_applicant: (a) => a.coApplicantName,
  children: (a) => a.childCount,
  income: (a) => a.householdIncome,
  status: (a) => a.status,
};

function sortApplications(rows: ApplicationSummary[], sort: SortState): ApplicationSummary[] {
  if (!sort) return rows;
  const value = SORT_VALUE[sort.key];
  const dir = sort.direction === "desc" ? -1 : 1;
  return [...rows].sort((a, b) => {
    const va = value(a);
    const vb = value(b);
    // Missing values always sort last, regardless of direction.
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    if (va < vb) return -1 * dir;
    if (va > vb) return 1 * dir;
    return 0;
  });
}
