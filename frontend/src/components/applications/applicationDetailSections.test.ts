import { describe, expect, it } from "vitest";

import type { ApplicationDetail } from "../../types";
import { buildDetailSections } from "./applicationDetailSections";

function application(overrides: Partial<ApplicationDetail>): ApplicationDetail {
  return {
    id: 1,
    primaryEmail: "alex@example.com",
    applicantName: "Alex Chen",
    coApplicantName: null,
    status: "eligible",
    statusSource: "untouched",
    stale: false,
    hardFilterReasons: [],
    childCount: 0,
    householdIncome: 80_000,
    flagCount: null,
    flagCategories: null,
    starredByMe: false,
    shortlisted: false,
    selected: false,
    openingIds: [1],
    autoStatus: "eligible",
    autoStatusSource: "untouched",
    firstSubmittedAt: null,
    lastSubmittedAt: null,
    submissionVersionCount: 1,
    normalized: {},
    essays: [],
    flags: null,
    privateNote: "",
    committeeNotes: [],
    ...overrides,
  };
}

describe("buildDetailSections", () => {
  it("uses the structured built-in application mapping", () => {
    const sections = buildDetailSections(application({
      normalized: { applicant_age: 36, household_income: 80_000 },
      rawRow: {
        applicant: {
          first_name: "Alex",
          last_name: "Chen",
          birth_date: "1990-01-02",
          email: "alex@example.com",
        },
        current_address: { city: "Vancouver", country: "Canada" },
      },
    }));

    expect(sections.map(({ title }) => title)).toEqual([
      "Applicant",
      "Household",
      "Current housing",
      "Income",
      "Submission",
    ]);
    expect(sections[0].fields.map(({ label }) => label)).toContain("Date of birth (age)");
  });

  it("keeps retained external-form questions in their legacy mapping", () => {
    const essayQuestion = "Why a co-op?";
    const sections = buildDetailSections(application({
      applicantName: "Alex Chen",
      normalized: { applicant_name: "Alex Chen" },
      essays: [{ label: essayQuestion, question: essayQuestion, answer: "Community." }],
      rawRow: {
        "First name": "Alex",
        "Last name": "Chen",
        "Phone number (xxx-xxx-xxxx)": "604-555-0100",
        "Unmapped answer": "Keep me",
        Declaration: "Do not display",
        [essayQuestion]: "Community.",
      },
    }));

    const applicantFields = sections.find(({ title }) => title === "Applicant")?.fields ?? [];
    const submissionFields = sections.find(({ title }) => title === "Submission")?.fields ?? [];
    expect(applicantFields.map(({ label }) => label)).toEqual(["Name", "Phone number"]);
    expect(submissionFields.map(({ label }) => label)).toEqual(["Unmapped Answer"]);
  });
});
