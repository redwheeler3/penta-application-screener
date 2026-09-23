import type {
  AppFacets,
  AppFilter,
  ApplicationSummary,
  SortKey,
  SortState,
} from "../types";

function matchesSearch(application: ApplicationSummary, search: string): boolean {
  const term = search.trim().toLowerCase();
  if (!term) return true;
  return [application.applicantName, application.coApplicantName, application.primaryEmail]
    .some((value) => (value ?? "").toLowerCase().includes(term));
}

function matchesStatus(application: ApplicationSummary, filter: AppFilter): boolean {
  return !filter.status || application.status === filter.status;
}

function matchesStatusSource(application: ApplicationSummary, filter: AppFilter): boolean {
  return !filter.statusSource || application.statusSource === filter.statusSource;
}

function matchesSavedView(application: ApplicationSummary, filter: AppFilter): boolean {
  if (filter.savedView === "favourites") return application.starredByMe;
  if (filter.savedView === "shortlist") return application.shortlisted;
  return true;
}

const SORT_VALUE: Record<SortKey, (application: ApplicationSummary) => string | number | null> = {
  applicant: (application) => application.applicantName,
  co_applicant: (application) => application.coApplicantName,
  children: (application) => application.childCount,
  income: (application) => application.householdIncome,
  status: (application) => application.status,
};

export function sortApplications(
  applications: ApplicationSummary[],
  sort: SortState,
): ApplicationSummary[] {
  if (!sort) return applications;
  const value = SORT_VALUE[sort.key];
  const direction = sort.direction === "desc" ? -1 : 1;
  return [...applications].sort((left, right) => {
    const leftValue = value(left);
    const rightValue = value(right);
    // Missing values always sort last, regardless of direction.
    if (leftValue == null && rightValue == null) return 0;
    if (leftValue == null) return 1;
    if (rightValue == null) return -1;
    if (leftValue < rightValue) return -1 * direction;
    if (leftValue > rightValue) return direction;
    return 0;
  });
}

export function selectApplications(
  applications: ApplicationSummary[],
  filter: AppFilter,
  search: string,
  sort: SortState,
): ApplicationSummary[] {
  const filtered = applications.filter(
    (application) =>
      matchesSearch(application, search)
      && matchesStatus(application, filter)
      && matchesStatusSource(application, filter)
      && matchesSavedView(application, filter),
  );
  return sortApplications(filtered, sort);
}

export function deriveApplicationFacets(
  applications: ApplicationSummary[],
  filter: AppFilter,
  search: string,
): AppFacets {
  const searched = applications.filter((application) => matchesSearch(application, search));
  const inSavedView = searched.filter((application) => matchesSavedView(application, filter));
  const status: AppFacets["status"] = { eligible: 0, ineligible: 0 };
  const source: AppFacets["source"] = { untouched: 0, rules: 0, ai: 0, human: 0 };

  // Each facet ignores its own filter while respecting the other active filters.
  for (const application of inSavedView) {
    if (matchesStatusSource(application, filter)) status[application.status] += 1;
    if (matchesStatus(application, filter)) source[application.statusSource] += 1;
  }

  const inStatusAndSource = searched.filter(
    (application) =>
      matchesStatus(application, filter) && matchesStatusSource(application, filter),
  );
  return {
    status,
    source,
    favourites: inStatusAndSource.filter((application) => application.starredByMe).length,
    shortlist: inStatusAndSource.filter((application) => application.shortlisted).length,
  };
}
