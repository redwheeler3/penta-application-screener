import { formatDateOnly, formatPacificDateTime } from "../../format";
import type { ApplicationDetail } from "../../types";
import { buildRetainedFormDetailSections } from "./retainedFormDetailSections";

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
  columns?: 2 | 4;
  printColumns?: 2;
};

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

function birthDateAndAge(birthDate: unknown, age: unknown): unknown {
  if (typeof birthDate !== "string") return age == null ? birthDate : `Age ${age}`;
  const formattedBirthDate = displayDate(birthDate);
  return age == null ? formattedBirthDate : `${formattedBirthDate} (${age})`;
}

function compactAddress(value: AnswerRecord): string {
  return [
    value.street,
    value.street_2,
    [value.city, value.province_or_state, value.postal_or_zip_code]
      .filter(Boolean)
      .join(", "),
    value.country,
  ].filter(Boolean).join(", ");
}

function previousResidenceFields(value: unknown): DetailField[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item, index) => {
    if (!isRecord(item)) return [];
    const address = nested(item, "address") ?? {};
    return presentFields([
      detailField(
        `previous_residences.${index}.address`,
        "Previous address",
        compactAddress(address),
      ),
      detailField(
        `previous_residences.${index}.move_in_date`,
        "Moved into previous address",
        displayDate(item.move_in_date),
      ),
    ]);
  });
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
    detailField(`${prefix}.birth_date`, "Date of birth (age)", birthDateAndAge(person.birth_date, options.age), {
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
    columns: 4,
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
      columns: 4,
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
          columns: 4,
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
      printColumns: 2,
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
      columns: 2,
      fields: presentFields([
        detailField(
          "current_address",
          "Current address",
          compactAddress(address),
        ),
        detailField(
          "current_address_move_in_date",
          "Moved into current address",
          displayDate(answers.current_address_move_in_date),
        ),
        ...previousResidenceFields(answers.previous_residences),
        detailField("owns_current_home", "Owns current home", answers.owns_current_home, {
          normalizedKey: answers.owns_current_home ? "has_real_estate" : undefined,
        }),
        detailField(
          "owns_other_real_estate",
          "Owns another home or land",
          answers.owns_other_real_estate,
          {
            normalizedKey: answers.owns_other_real_estate
              ? "has_real_estate"
              : undefined,
          },
        ),
      ]),
    },
    currentLandlord
      ? {
          title: "Current landlord",
          fields: referenceFields("current_landlord", currentLandlord),
        }
      : null,
    previousLandlord
      ? {
          title: "Previous landlord",
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
      columns: coApplicant ? undefined : 2,
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

export function buildDetailSections(app: ApplicationDetail): DetailSection[] {
  const rawRow = app.rawRow ?? {};
  if (isRecord(rawRow.applicant)) {
    return buildCanonicalDetailSections(app, rawRow);
  }
  return buildRetainedFormDetailSections(app);
}
