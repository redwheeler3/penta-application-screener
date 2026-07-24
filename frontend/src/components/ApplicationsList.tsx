import { ChevronDown, ChevronUp, Star } from "lucide-react";
import { type ReactNode } from "react";
import { SOURCE_LABELS, STATUS_LABELS } from "../constants";
import { flagCategoryLabel } from "../format";
import type { AppFacets, AppFilter, ApplicationSummary, SortKey, SortState } from "../types";
import { StarButton } from "./StarButton";

export function ApplicationsList(props: {
  applications: ApplicationSummary[];
  appFilter: AppFilter;
  appFacets: AppFacets;
  appSearch: string;
  appSort: SortState;
  onApplyFilter: (next: AppFilter) => void;
  onSearch: (value: string) => void;
  onToggleSort: (key: SortKey) => void;
  onSelectApplication: (id: number) => void;
  onToggleStar: (id: number, starred: boolean) => void;
}): ReactNode {
  const { applications, appFilter, appFacets, appSort } = props;

  // Counts are faceted: each group reflects the OTHER group's active filter (plus
  // search). "All"/"Any" sums the facet.
  const { status: statusFacet, source: sourceFacet } = appFacets;
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
        <div className="filter-group">
          <span className="filter-group-label">Show</span>
          <button
            type="button"
            className={`tab-button favourites-toggle ${appFilter.favourites ? "active" : ""}`}
            aria-pressed={!!appFilter.favourites}
            disabled={appFacets.favourites === 0 && !appFilter.favourites}
            onClick={() => props.onApplyFilter({ ...appFilter, favourites: !appFilter.favourites })}
          >
            <Star size={13} fill={appFilter.favourites ? "currentColor" : "none"} strokeWidth={2} />
            <span>Favourites ({appFacets.favourites})</span>
          </button>
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
            {appFilter.favourites
              ? "You haven't favourited any applicants yet."
              : appFilter.status || appFilter.statusSource
                ? "No applications match this filter."
                : "No applications imported yet."}
          </p>
        </div>
      ) : (
        <table className="app-table">
          <thead>
            <tr>
              <th className="star-col" aria-label="Favourite" />
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
                  <td className="star-col">
                    <StarButton
                      starred={app.starredByMe}
                      onToggle={(next) => props.onToggleStar(app.id, next)}
                      stopPropagation
                    />
                  </td>
                  <td className="applicant-cell">{app.applicantName || app.primaryEmail}</td>
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
      )}
    </>
  );
}
