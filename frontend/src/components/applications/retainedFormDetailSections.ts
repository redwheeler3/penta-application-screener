import { fieldLabel } from "../../format";
import type { ApplicationDetail } from "../../types";
import type { DetailSection } from "./applicationDetailSections";

type RetainedApplicationField = {
  key: string;
  label?: string;
  normalizedKey?: string;
  source?: "raw" | "normalized";
  consumesRawKeys?: string[];
  // Render the value as a clickable link (opens in a new tab) when it looks like a URL.
  isLink?: boolean;
};

const CHILD_DETAIL_RAW_KEYS = [
  "First name [3]",
  "Last name [3]",
  "Age [3]",
  "First name [4]",
  "Last name [4]",
  "Age [4]",
  "First name [5]",
  "Last name [5]",
  "Age [5]",
  "First name [6]",
  "Last name [6]",
  "Age [6]",
];

const HIDDEN_RAW_KEYS = new Set(["Declaration"]);

// Applications retained from the external form keep their original question headings.
// This map remains only for those records until their one-year retention period ends.
const RETAINED_APPLICATION_SECTIONS: Array<{
  title: string;
  fields: RetainedApplicationField[];
}> = [
  {
    title: "Applicant",
    fields: [
      {
        key: "applicant_name",
        label: "Name",
        normalizedKey: "applicant_name",
        source: "normalized",
        consumesRawKeys: ["First name", "Last name"],
      },
      { key: "Age", normalizedKey: "applicant_age" },
      { key: "Email address", label: "Email address", normalizedKey: "applicant_email" },
      { key: "Phone number (xxx-xxx-xxxx)", label: "Phone number" },
    ],
  },
  {
    title: "Co-applicant",
    fields: [
      {
        key: "co_applicant_name",
        label: "Name",
        normalizedKey: "co_applicant_name",
        source: "normalized",
        consumesRawKeys: ["First name [2]", "Last name [2]"],
      },
      { key: "Age [2]", label: "Age", normalizedKey: "co_applicant_age" },
      { key: "Email address [2]", label: "Email address", normalizedKey: "co_applicant_email" },
      { key: "Phone number (xxx-xxx-xxxx) [2]", label: "Phone number", normalizedKey: "co_applicant_phone" },
      { key: "Relationship to applicant" },
    ],
  },
  {
    title: "Household composition",
    fields: [
      {
        key: "How many children (under 18) will be living in the unit on the move in date?",
        label: "Number of children",
        normalizedKey: "child_count",
      },
      {
        key: "child_details",
        label: "Children",
        normalizedKey: "child_details",
        source: "normalized",
        consumesRawKeys: CHILD_DETAIL_RAW_KEYS,
      },
      {
        key: "If you have a link to a photo of yourself and the members of your household, please include it here.",
        label: "Household photo link",
        isLink: true,
      },
      {
        key: "household_photo_link",
        label: "Household photo link",
        normalizedKey: "household_photo_link",
        source: "normalized",
        consumesRawKeys: ["household_photo_link"],
        isLink: true,
      },
      { key: "If you have any pets, please describe them here.", label: "Pets", normalizedKey: "pets_text" },
    ],
  },
  {
    title: "Housing and references",
    fields: [
      { key: "Street address" },
      { key: "Street address 2" },
      { key: "City" },
      { key: "Province / State" },
      { key: "Postal / Zip Code" },
      { key: "Country" },
      {
        key: "Have you lived at your current address for 2 years or more?",
        label: "Current address 2+ years",
      },
      {
        key: "Do you own real estate (land, house, condominium, etc.)?",
        label: "Owns real estate",
        normalizedKey: "has_real_estate",
      },
      { key: "Current landlord name" },
      { key: "Current landlord email address" },
      { key: "Current landlord phone number (xxx-xxx-xxxx)", label: "Current landlord phone" },
      { key: "Previous landlord name" },
      { key: "Previous landlord email address" },
      { key: "Previous landlord phone number (xxx-xxx-xxxx)", label: "Previous landlord phone" },
    ],
  },
  {
    title: "Applicant employment",
    fields: [
      { key: "Job title" },
      { key: "Company name" },
      { key: "Start date at this company", normalizedKey: "applicant_employment_start" },
      { key: "Name of current manager" },
      { key: "Phone number (xxx-xxx-xxxx) of current manager", label: "Manager phone" },
      { key: "Email address of current manager", label: "Manager email" },
    ],
  },
  {
    title: "Co-applicant employment",
    fields: [
      { key: "Job title [2]", label: "Job title" },
      { key: "Company name [2]", label: "Company name" },
      {
        key: "Start date at this company [2]",
        label: "Start date at this company",
        normalizedKey: "co_applicant_employment_start",
      },
      { key: "Name of current manager [2]", label: "Name of current manager" },
      { key: "Phone number (xxx-xxx-xxxx) of current manager [2]", label: "Manager phone" },
      { key: "Email address of current manager [2]", label: "Manager email" },
    ],
  },
  {
    title: "Income and declaration",
    fields: [
      { key: "Total yearly gross income for applicant", normalizedKey: "applicant_income" },
      { key: "Total yearly gross income for co-applicant", normalizedKey: "co_applicant_income" },
      {
        key: "Total yearly gross income for your household (add up all the numbers above)",
        label: "Total household income",
        normalizedKey: "household_income",
      },
    ],
  },
  {
    title: "Submission",
    fields: [
      { key: "Timestamp" },
      { key: "Email Address", label: "Form submission email", normalizedKey: "form_submission_email" },
    ],
  },
];

export function buildRetainedFormDetailSections(app: ApplicationDetail): DetailSection[] {
  const rawRow = app.rawRow ?? {};
  const normalized = app.normalized ?? {};
  const usedRawKeys = new Set<string>();
  const essayKeys = new Set(app.essays.map((essay) => essay.question));

  const sections = RETAINED_APPLICATION_SECTIONS.map((section) => {
    const fields = section.fields
      .filter((field) => {
        if (field.source === "normalized") {
          return Object.prototype.hasOwnProperty.call(normalized, field.normalizedKey ?? field.key);
        }
        return Object.prototype.hasOwnProperty.call(rawRow, field.key);
      })
      .map((field) => {
        const isNormalized = field.source === "normalized";
        if (!isNormalized) usedRawKeys.add(field.key);
        field.consumesRawKeys?.forEach((key) => usedRawKeys.add(key));
        return {
          key: field.key,
          label: field.label ?? fieldLabel(field.key),
          value: isNormalized ? normalized[field.normalizedKey ?? field.key] : rawRow[field.key],
          normalizedKey: field.normalizedKey,
          isLink: field.isLink,
        };
      });
    return { title: section.title, fields };
  }).filter((section) => section.fields.length > 0);

  const otherRawFields = Object.entries(rawRow)
    .filter(([key]) => !usedRawKeys.has(key) && !essayKeys.has(key) && !HIDDEN_RAW_KEYS.has(key))
    .map(([key, value]) => ({
      key,
      label: fieldLabel(key),
      value,
      normalizedKey: undefined,
      isLink: undefined,
    }));

  if (otherRawFields.length > 0) {
    const submission = sections.find((section) => section.title === "Submission");
    if (submission) {
      submission.fields.push(...otherRawFields);
    } else {
      sections.push({ title: "Submission", fields: otherRawFields });
    }
  }

  return sections;
}
