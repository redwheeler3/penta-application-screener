import { ChevronDown, ChevronUp } from "lucide-react";
import { type ReactNode } from "react";
import { SOURCE_LABELS, STATUS_LABELS } from "../constants";
import { flagCategoryLabel } from "../format";
import type { AppFacets, AppFilter, ApplicationSummary, DashboardCounts, SortKey, SortState } from "../types";

export function ApplicationsList(props: {
  applications: ApplicationSummary[];
  appFilter: AppFilter;
  appFacets: AppFacets | null;
  dashboardCounts: DashboardCounts;
  appSearch: string;
  appSort: SortState;
  appPage: number;
  appPageSize: number;
  appTotal: number;
  onApplyFilter: (next: AppFilter) => void;
  onSearch: (value: string) => void;
  onToggleSort: (key: SortKey) => void;
  onSelectApplication: (id: number) => void;
  onChangePageSize: (size: number) => void;
  onGoToPage: (page: number) => void;
}): ReactNode {
  const { applications, appFilter, appFacets, dashboardCounts, appSort, appPage, appPageSize, appTotal } = props;

  // Counts are faceted: each group reflects the OTHER group's active filter (plus
  // search). "All"/"Any" sums the facet.
  const statusFacet = appFacets?.status ?? dashboardCounts.status;
  const sourceFacet = appFacets?.source ?? dashboardCounts.source;
  const sum = (counts: Record<string, number>) => Object.values(counts).reduce((a, b) => a + b, 0);
  const statusOptions = [
    { label: "All", value: undefined, count: sum(statusFacet) },
    { label: "Eligible", value: "eligible" as const, count: statusFacet.eligible },
    { label: "Ineligible", value: "ineligible" as const, count: statusFacet.ineligible },
  ];
  const sourceOptions = [
    { label: "Any", value: undefined, count: sum(sourceFacet) },
    { label: "Rules", value: "rules" as const, count: sourceFacet.rules },
    { label: "AI", value: "ai" as const, count: sourceFacet.ai },
    { label: "Reviewer", value: "human" as const, count: sourceFacet.human },
  ];
  const totalPages = Math.ceil(appTotal / appPageSize) || 1;

  return (
    <>
      <div className="app-controls">
        {/* Each group toggles one axis of the filter, preserving the other, so
            Status and "Decided by" combine (AND). */}
        <div className="filter-group">
          <span className="filter-group-label">Status</span>
          <div className="app-tabs">
            {statusOptions.map((opt) => (
              <button
                key={opt.label}
                className={`tab-button ${appFilter.status === opt.value ? "active" : ""}`}
                onClick={() => props.onApplyFilter({ ...appFilter, status: opt.value })}
              >
                {opt.label} ({opt.count})
              </button>
            ))}
          </div>
        </div>
        <div className="filter-group">
          <span className="filter-group-label">Decided by</span>
          <div className="app-tabs">
            {sourceOptions.map((opt) => (
              <button
                key={opt.label}
                className={`tab-button ${appFilter.statusSource === opt.value ? "active" : ""}`}
                onClick={() => props.onApplyFilter({ ...appFilter, statusSource: opt.value })}
              >
                {opt.label} ({opt.count})
              </button>
            ))}
          </div>
        </div>
        <input
          className="app-search"
          type="search"
          placeholder="Search by name or email"
          value={props.appSearch}
          onChange={(event) => props.onSearch(event.target.value)}
        />
      </div>

      {applications.length === 0 ? (
        <div className="empty-state">
          <p>
            {appFilter.status || appFilter.statusSource
              ? "No applications match this filter."
              : "No applications imported yet."}
          </p>
        </div>
      ) : (
        <>
          <table className="app-table">
            <thead>
              <tr>
                {(
                  [
                    { label: "Applicant", key: "applicant" },
                    { label: "Co-applicant", key: "co_applicant" },
                    { label: "Children", key: "children" },
                    { label: "Income", key: "income" },
                    { label: "Status", key: "status" },
                  ] as Array<{ label: string; key: SortKey }>
                ).map((col) => (
                  <th key={col.key}>
                    <button
                      type="button"
                      className={`sort-header ${appSort?.key === col.key ? "active" : ""}`}
                      onClick={() => props.onToggleSort(col.key)}
                    >
                      <span>{col.label}</span>
                      {appSort?.key === col.key ? (
                        appSort.direction === "asc" ? <ChevronUp size={14} /> : <ChevronDown size={14} />
                      ) : null}
                    </button>
                  </th>
                ))}
                <th>Decided by</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {applications.map((app) => {
                // Reason cell shows the machine's "why" for an exclusion: rules
                // reasons, or AI flag categories. Human overrides show neither.
                const reason =
                  app.statusSource === "rules"
                    ? app.hardFilterReasons.map((r) => r.message).join("; ")
                    : app.statusSource === "ai"
                      ? (app.flagCategories ?? []).map(flagCategoryLabel).join("; ")
                      : "—";
                return (
                  <tr
                    key={app.id}
                    data-app-id={app.id}
                    onClick={() => props.onSelectApplication(app.id)}
                    className="clickable-row"
                  >
                    <td>{app.applicantName || app.primaryEmail}</td>
                    <td>{app.coApplicantName || "—"}</td>
                    <td>{app.childCount ?? "?"}</td>
                    <td>{app.householdIncome != null ? `$${app.householdIncome.toLocaleString()}` : "?"}</td>
                    <td>
                      <span className={`status-badge status-${app.status}`}>{STATUS_LABELS[app.status]}</span>
                    </td>
                    <td>
                      {app.statusSource === "untouched" ? (
                        "—"
                      ) : (
                        <span className={`source-badge source-${app.statusSource}`}>
                          {SOURCE_LABELS[app.statusSource]}
                        </span>
                      )}
                      {app.stale ? (
                        <span className="stale-badge" title="New AI findings since last review">
                          stale
                        </span>
                      ) : null}
                    </td>
                    <td className="reason-cell">{reason}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="pagination">
            <div className="pagination-size">
              <span>Rows:</span>
              <select value={appPageSize} onChange={(event) => props.onChangePageSize(Number(event.target.value))}>
                <option value="10">10</option>
                <option value="25">25</option>
                <option value="50">50</option>
                <option value="100">100</option>
              </select>
            </div>
            <div className="pagination-pages">
              <button disabled={appPage <= 1} onClick={() => props.onGoToPage(1)}>
                «
              </button>
              <button disabled={appPage <= 1} onClick={() => props.onGoToPage(appPage - 1)}>
                ‹
              </button>
              <span>
                Page {appPage} of {totalPages}
              </span>
              <button disabled={appPage >= totalPages} onClick={() => props.onGoToPage(appPage + 1)}>
                ›
              </button>
              <button disabled={appPage >= totalPages} onClick={() => props.onGoToPage(totalPages)}>
                »
              </button>
            </div>
          </div>
        </>
      )}
    </>
  );
}
