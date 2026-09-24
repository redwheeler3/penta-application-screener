import { describe, expect, it } from "vitest";

import type { ApplicationSummary } from "../types";
import { deriveApplicationFacets, selectApplications, sortApplications } from "./applicationSelectors";

function application(
  id: number,
  overrides: Partial<ApplicationSummary> = {},
): ApplicationSummary {
  return {
    id,
    primaryEmail: `person${id}@example.com`,
    applicantName: `Applicant ${id}`,
    coApplicantName: null,
    status: "eligible",
    statusSource: "untouched",
    stale: false,
    hardFilterReasons: [],
    childCount: 1,
    householdIncome: 80_000,
    flagCount: null,
    flagCategories: null,
    starredByMe: false,
    shortlisted: false,
    selected: false,
    openingIds: [1],
    ...overrides,
  };
}

describe("application selectors", () => {
  const applications = [
    application(1, { applicantName: "Alex Chen", householdIncome: 90_000, starredByMe: true }),
    application(2, {
      applicantName: "Bea Singh",
      coApplicantName: "Casey Jones",
      status: "ineligible",
      statusSource: "rules",
      householdIncome: null,
      shortlisted: true,
    }),
    application(3, {
      applicantName: "Chris Martin",
      primaryEmail: "alex@example.net",
      statusSource: "ai",
      householdIncome: 70_000,
      starredByMe: true,
      shortlisted: true,
    }),
    application(4, {
      applicantName: "Dana Wu",
      status: "ineligible",
      statusSource: "human",
      householdIncome: 100_000,
      starredByMe: true,
    }),
  ];

  it("combines search, filters, saved views, and sorting", () => {
    expect(
      selectApplications(applications, { savedView: "shortlist" }, "casey", null)
        .map(({ id }) => id),
    ).toEqual([2]);
    expect(
      selectApplications(
        applications,
        { status: "eligible", savedView: "favourites" },
        "",
        { key: "income", direction: "asc" },
      ).map(({ id }) => id),
    ).toEqual([3, 1]);
  });

  it("makes each facet ignore only its own filter", () => {
    expect(
      deriveApplicationFacets(
        applications,
        { status: "ineligible", statusSource: "rules" },
        "",
      ),
    ).toEqual({
      status: { eligible: 0, ineligible: 1 },
      source: { untouched: 0, rules: 1, ai: 0, human: 1 },
      favourites: 0,
      shortlist: 1,
    });

    expect(
      deriveApplicationFacets(applications, { savedView: "favourites" }, "alex"),
    ).toEqual({
      status: { eligible: 2, ineligible: 0 },
      source: { untouched: 1, rules: 0, ai: 1, human: 0 },
      favourites: 2,
      shortlist: 1,
    });
  });

  it("sorts missing values last in either direction without mutating the input", () => {
    const original = [...applications];
    expect(sortApplications(applications, { key: "income", direction: "desc" }).map(({ id }) => id))
      .toEqual([4, 1, 3, 2]);
    expect(applications).toEqual(original);
  });

  it("filters selected households by their underlying eligibility", () => {
    const selectedEligible = application(5, { selected: true, status: "eligible" });
    const selectedIneligible = application(6, { selected: true, status: "ineligible" });

    expect(
      selectApplications(
        [selectedEligible, selectedIneligible],
        { status: "eligible" },
        "",
        null,
      ).map(({ id }) => id),
    ).toEqual([5]);
    expect(
      deriveApplicationFacets([selectedEligible, selectedIneligible], {}, "").status,
    ).toEqual({ eligible: 1, ineligible: 1 });
  });
});
