import { useMemo, useState } from "react";
import * as api from "../api";
import type {
  AppFacets,
  AppFilter,
  ApplicationSummary,
  SortKey,
  SortState,
} from "../types";

export interface ApplicationsState {
  /** The filtered + sorted list the UI renders (derived from the full pool). */
  applications: ApplicationSummary[];
  /** Facet counts (status/source/favourites) derived from the full pool, each
   * reflecting the OTHER active filters so the groups stay consistent. */
  appFacets: AppFacets;
  appFilter: AppFilter;
  appSearch: string;
  appSort: SortState;
  /** (Re)fetch the whole pool. Called after sync/screen/override so the list reflects
   * server truth; filtering/sorting then happen client-side with no further fetches. */
  reloadApplications: () => void;
  toggleSort: (key: SortKey) => void;
  applyFilter: (next: AppFilter) => void;
  search: (value: string) => void;
}

/** The applications-list view state. The whole pool (a few hundred rows at most) is held
 * client-side; filtering, sorting, and facet counts are derived here with no server
 * round-trips — so a filter/sort/favourites toggle is instant. Only a data-changing
 * action (sync, screen, status override, star) triggers a refetch. The selected
 * candidate detail is NOT here: it's cross-cutting (tab switches, overrides, settings
 * save all clear it), so it stays in App. */
export function useApplications(): ApplicationsState {
  const [allApplications, setAllApplications] = useState<ApplicationSummary[]>([]);
  const [appFilter, setAppFilter] = useState<AppFilter>({});
  const [appSearch, setAppSearch] = useState("");
  const [appSort, setAppSort] = useState<SortState>(null);

  function reloadApplications() {
    api.fetchApplications().then(setAllApplications);
  }

  // Everything below is derived from the full pool — no fetch on filter/sort/search.
  const searchTerm = appSearch.trim().toLowerCase();
  const matchesSearch = (a: ApplicationSummary) =>
    !searchTerm ||
    [a.applicantName, a.coApplicantName, a.primaryEmail].some((v) =>
      (v ?? "").toLowerCase().includes(searchTerm),
    );

  // Facets reflect every active filter EXCEPT their own group (like the server did),
  // so the two filter rows stay mutually consistent. Search + favourites apply to both.
  const appFacets = useMemo<AppFacets>(() => {
    const base = allApplications.filter(matchesSearch);
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
  }, [allApplications, appFilter, searchTerm]);

  const applications = useMemo(() => {
    const filtered = allApplications.filter(
      (a) =>
        matchesSearch(a) &&
        (!appFilter.status || a.status === appFilter.status) &&
        (!appFilter.statusSource || a.statusSource === appFilter.statusSource) &&
        (!appFilter.favourites || a.starredByMe),
    );
    return appSort ? sortApplications(filtered, appSort) : filtered;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allApplications, appFilter, searchTerm, appSort]);

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
    appFacets,
    appFilter,
    appSearch,
    appSort,
    reloadApplications,
    toggleSort,
    applyFilter: setAppFilter,
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
