import { fieldLabel, formatDateOnly, formatPacificDateTime } from "../../format";
import type { ApplicationDetail } from "../../types";

export type DetailField = {
  key: string;
  label: string;
  value: unknown;
  normalizedKey?: string;
  isLink?: boolean;
};

export type DetailSection = {
  title: string;
  fields: DetailField[];
};

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

type AnswerRecord = Record<string, unknown>;

function isRecord(value: unknown): value is AnswerRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nested(record: AnswerRecord, key: string): AnswerRecord | null {
  const value = record[key];
  return isRecord(value) ? value : null;
}

function detailField(
  key: string,
  label: string,
  value: unknown,
  options: { normalizedKey?: string; isLink?: boolean } = {},
): DetailField {
  return { key, label, value, ...options };
}

function readableChoice(value: unknown): unknown {
  return typeof value === "string"
    ? value.replaceAll("_", " ").replace(/^\w/, (letter) => letter.toUpperCase())
    : value;
}

function presentFields(fields: DetailField[]): DetailField[] {
  return fields.filter(
    (field) => field.value !== null && field.value !== undefined && field.value !== "",
  );
}

function displayDate(value: unknown): unknown {
  return typeof value === "string" ? formatDateOnly(value) : value;
}

function personFields(options: {
  prefix: "applicant" | "co_applicant";
  person: AnswerRecord;
  age: unknown;
  ageKey: "applicant_age" | "co_applicant_age";
  nameKey: "applicant_name" | "co_applicant_name";
  emailKey: "applicant_email" | "co_applicant_email";
  phoneKey?: "co_applicant_phone";
  includeRelationship?: boolean;
}): DetailField[] {
  const { prefix, person } = options;
  return presentFields([
    detailField(
      `${prefix}.name`,
      "Name",
      [person.first_name, person.last_name].filter(Boolean).join(" "),
      { normalizedKey: options.nameKey },
    ),
    detailField(options.ageKey, "Age", options.age, {
      normalizedKey: options.ageKey,
    }),
    detailField(`${prefix}.email`, "Email address", person.email, {
      normalizedKey: options.emailKey,
    }),
    detailField(`${prefix}.phone`, "Phone number", person.phone, {
      ...(options.phoneKey ? { normalizedKey: options.phoneKey } : {}),
    }),
    ...(options.includeRelationship
      ? [
          detailField(
            `${prefix}.relationship`,
            "Relationship to applicant",
            person.relationship,
          ),
        ]
      : []),
  ]);
}

function referenceFields(prefix: string, reference: AnswerRecord | null): DetailField[] {
  if (!reference) return [];
  return [
    detailField(`${prefix}.name`, "Name", reference.name),
    detailField(`${prefix}.email`, "Email address", reference.email),
    detailField(`${prefix}.phone`, "Phone number", reference.phone),
  ];
}

function employmentSection(
  title: string,
  prefix: string,
  employment: AnswerRecord | null,
): DetailSection | null {
  if (!employment) return null;
  const manager = nested(employment, "manager");
  const selfEmployed = employment.status === "self_employed";
  return {
    title,
    fields: presentFields([
      detailField(`${prefix}.status`, "Employment status", readableChoice(employment.status)),
      detailField(
        `${prefix}.job_title`,
        selfEmployed ? "Type of business" : "Job title",
        employment.job_title,
      ),
      detailField(
        `${prefix}.company_name`,
        selfEmployed ? "Business name" : "Employer",
        employment.company_name,
      ),
      detailField(
        `${prefix}.start_date`,
        "Start date",
        displayDate(employment.start_date),
      ),
      ...referenceFields(`${prefix}.manager`, manager).map((field) => ({
        ...field,
        label: `Manager ${field.label.toLowerCase()}`,
      })),
    ]),
  };
}

function buildCanonicalDetailSections(
  app: ApplicationDetail,
  answers: AnswerRecord,
): DetailSection[] {
  const applicant = nested(answers, "applicant") ?? {};
  const coApplicant = nested(answers, "co_applicant");
  const address = nested(answers, "current_address") ?? {};
  const currentLandlord = nested(answers, "current_landlord");
  const previousLandlord = nested(answers, "previous_landlord");
  const normalized = app.normalized ?? {};
  const sections: Array<DetailSection | null> = [
    {
      title: "Applicant",
      fields: personFields({
        prefix: "applicant",
        person: applicant,
        age: normalized.applicant_age,
        ageKey: "applicant_age",
        nameKey: "applicant_name",
        emailKey: "applicant_email",
      }),
    },
    coApplicant
      ? {
          title: "Co-applicant",
          fields: personFields({
            prefix: "co_applicant",
            person: coApplicant,
            age: normalized.co_applicant_age,
            ageKey: "co_applicant_age",
            nameKey: "co_applicant_name",
            emailKey: "co_applicant_email",
            phoneKey: "co_applicant_phone",
            includeRelationship: true,
          }),
        }
      : null,
    {
      title: "Household",
      fields: [
        detailField("child_details", "Children", normalized.child_details, {
          normalizedKey: "child_details",
        }),
        detailField("household_photo_link", "Household photo link", answers.household_photo_link, {
          normalizedKey: "household_photo_link",
          isLink: true,
        }),
        detailField("pets", "Pets", answers.pets, { normalizedKey: "pets_text" }),
      ],
    },
    {
      title: "Current housing",
      fields: [
        detailField("current_address.street", "Street address", address.street),
        detailField("current_address.street_2", "Apartment or unit", address.street_2),
        detailField("current_address.city", "City", address.city),
        detailField(
          "current_address.province_or_state",
          "Province or state",
          address.province_or_state,
        ),
        detailField(
          "current_address.postal_or_zip_code",
          "Postal or ZIP code",
          address.postal_or_zip_code,
        ),
        detailField("current_address.country", "Country", address.country),
        detailField(
          "lived_at_current_address_two_years",
          "At this address for at least two years",
          answers.lived_at_current_address_two_years,
        ),
        detailField("owns_current_home", "Owns current home", answers.owns_current_home, {
          normalizedKey: "has_real_estate",
        }),
        detailField(
          "owns_other_real_estate",
          "Owns another home or land",
          answers.owns_other_real_estate,
          { normalizedKey: "has_real_estate" },
        ),
      ],
    },
    currentLandlord
      ? {
          title: "Current housing reference",
          fields: referenceFields("current_landlord", currentLandlord),
        }
      : null,
    previousLandlord
      ? {
          title: "Previous housing reference",
          fields: referenceFields("previous_landlord", previousLandlord),
        }
      : null,
    employmentSection(
      "Applicant employment",
      "applicant_employment",
      nested(answers, "applicant_employment"),
    ),
    employmentSection(
      "Co-applicant employment",
      "co_applicant_employment",
      nested(answers, "co_applicant_employment"),
    ),
    {
      title: "Income",
      fields: presentFields([
        detailField("applicant_income", "Applicant annual income", answers.applicant_income, {
          normalizedKey: "applicant_income",
        }),
        detailField(
          "co_applicant_income",
          "Co-applicant annual income",
          answers.co_applicant_income,
          { normalizedKey: "co_applicant_income" },
        ),
        detailField(
          "household_income",
          "Total household income",
          normalized.household_income,
          { normalizedKey: "household_income" },
        ),
      ]),
    },
    {
      title: "Submission",
      fields: presentFields([
        detailField(
          "first_submitted_at",
          "Submitted",
          app.firstSubmittedAt ? formatPacificDateTime(app.firstSubmittedAt) : null,
        ),
        detailField(
          "last_submitted_at",
          "Last updated",
          app.submissionVersionCount > 1 && app.lastSubmittedAt
            ? formatPacificDateTime(app.lastSubmittedAt)
            : null,
        ),
        detailField(
          "submission_version_count",
          "Submitted versions",
          app.submissionVersionCount,
        ),
      ]),
    },
  ];
  return sections.filter((section): section is DetailSection => section !== null);
}

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

export function buildDetailSections(app: ApplicationDetail): DetailSection[] {
  const rawRow = app.rawRow ?? {};
  if (isRecord(rawRow.applicant)) {
    return buildCanonicalDetailSections(app, rawRow);
  }
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
