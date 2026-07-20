import { useState } from "react";
import * as api from "../api";
import type {
  AppFacets,
  AppFilter,
  ApplicationSummary,
  SortKey,
  SortState,
} from "../types";

export interface ApplicationsList {
  applications: ApplicationSummary[];
  appTotal: number;
  appPage: number;
  appPageSize: number;
  appFilter: AppFilter;
  appFacets: AppFacets | null;
  appSearch: string;
  appSort: SortState;
  /** Single entry point for loading the list; every list-affecting control routes
   * through here so the request always reflects current filter/search/sort/paging
   * (args default to current state when omitted). */
  loadApplications: (args: {
    filter?: AppFilter;
    page?: number;
    search?: string;
    pageSize?: number;
    sort?: SortState;
  }) => void;
  toggleSort: (key: SortKey) => void;
  applyFilter: (next: AppFilter) => void;
  search: (value: string) => void;
}

/** The applications-list view state: the fetched page, its facet counts, and the
 * filter/search/sort/paging that produced it. Self-contained — talks only to the api
 * layer. The selected candidate detail is NOT here: it's cross-cutting (tab switches,
 * status overrides, and settings-save all clear it), so it stays in App. */
export function useApplications(): ApplicationsList {
  const [applications, setApplications] = useState<ApplicationSummary[]>([]);
  const [appTotal, setAppTotal] = useState(0);
  const [appPage, setAppPage] = useState(1);
  const [appPageSize, setAppPageSize] = useState(25);
  // Filter mirrors the real columns. A tab sets one of these (or neither for All).
  const [appFilter, setAppFilter] = useState<AppFilter>({});
  // Faceted option counts from the latest list response (reflect the cross-group filter).
  const [appFacets, setAppFacets] = useState<AppFacets | null>(null);
  const [appSearch, setAppSearch] = useState("");
  const [appSort, setAppSort] = useState<SortState>(null);

  function loadApplications(args: {
    filter?: AppFilter;
    page?: number;
    search?: string;
    pageSize?: number;
    sort?: SortState;
  }) {
    const filter = args.filter ?? appFilter;
    const search = args.search ?? appSearch;
    const pageSize = args.pageSize ?? appPageSize;
    const sort = args.sort ?? appSort;
    api.fetchApplications({ filter, page: args.page ?? 1, search, pageSize, sort }).then((payload) => {
      setApplications(payload.applications);
      setAppTotal(payload.total);
      setAppPage(payload.page);
      setAppPageSize(payload.pageSize);
      setAppFacets(payload.facets);
    });
  }

  function toggleSort(key: SortKey) {
    // First click sorts ascending; clicking the active column flips direction.
    const next: SortState =
      appSort?.key === key
        ? { key, direction: appSort.direction === "asc" ? "desc" : "asc" }
        : { key, direction: "asc" };
    setAppSort(next);
    loadApplications({ page: 1, sort: next });
  }

  function applyFilter(next: AppFilter) {
    setAppFilter(next);
    loadApplications({ filter: next, page: 1 });
  }

  function search(value: string) {
    setAppSearch(value);
    loadApplications({ page: 1, search: value });
  }

  return {
    applications,
    appTotal,
    appPage,
    appPageSize,
    appFilter,
    appFacets,
    appSearch,
    appSort,
    loadApplications,
    toggleSort,
    applyFilter,
    search,
  };
}
