import type { ApplicantOpening, WorkingApplicationAnswers } from "./types";

export type PendingCopyDiffRow = {
  label: string;
  saved: string;
  guest: string;
};

export function pendingCopyDifferences(
  saved: WorkingApplicationAnswers,
  savedOpeningIds: number[],
  guest: WorkingApplicationAnswers,
  guestOpeningIds: number[],
  openings: ApplicantOpening[],
): PendingCopyDiffRow[] {
  const savedValues = displayedValues(saved, savedOpeningIds, openings);
  const guestValues = displayedValues(guest, guestOpeningIds, openings);
  return savedValues.map(
    (row, index) => ({
      label: row.label,
      saved: shown(row.value),
      guest: shown(guestValues[index].value),
    }),
  ).filter((row) => row.saved !== row.guest);
}

function displayedValues(
  answers: WorkingApplicationAnswers,
  openingIds: number[],
  openings: ApplicantOpening[],
): { label: string; value: string }[] {
  const applicant = answers.applicant;
  const coApplicant = answers.coApplicant;
  return [
    field("Openings", openingIds.map((id) => openingName(openings, id)).join("\n")),
    field("Primary applicant name", name(applicant.firstName, applicant.lastName)),
    field("Primary applicant date of birth", applicant.birthDate),
    field("Primary applicant email", applicant.email),
    field("Primary applicant phone", applicant.phone),
    field("Co-applicant name", coApplicant ? name(coApplicant.firstName, coApplicant.lastName) : ""),
    field("Co-applicant relationship", coApplicant?.relationship ?? ""),
    field("Co-applicant date of birth", coApplicant?.birthDate ?? ""),
    field("Co-applicant email", coApplicant?.email ?? ""),
    field("Co-applicant phone", coApplicant?.phone ?? ""),
    field("Children", answers.children.map((child) => (
      `${name(child.firstName, child.lastName)}${child.birthDate ? ` (${child.birthDate})` : ""}`
    )).join("\n")),
    field("Current address", address(answers)),
    field("Lived at current address for two years", yesNo(answers.livedAtCurrentAddressTwoYears)),
    field("Owns current home", yesNo(answers.ownsCurrentHome)),
    field("Owns another home or land", yesNo(answers.ownsOtherRealEstate)),
    field("Current landlord", reference(answers.currentLandlord)),
    field("Previous landlord", reference(answers.previousLandlord)),
    field("Household introduction", answers.essays.householdIntroduction),
    field("Skills to contribute", answers.essays.skillsToContribute),
    field("Previous co-op experience", answers.essays.previousCoopExperience),
    field("Why co-op housing", answers.essays.whyCoop),
    field("Anything else", answers.essays.additionalInformation),
    field("Pets", answers.pets ?? ""),
    field("Household photo link", answers.householdPhotoLink ?? ""),
    field("Primary applicant employment", employment(answers.applicantEmployment)),
    field("Co-applicant employment", employment(answers.coApplicantEmployment)),
    field("Primary applicant annual income", money(answers.applicantIncome)),
    field("Co-applicant annual income", money(answers.coApplicantIncome)),
  ];
}

function field(label: string, value: string): { label: string; value: string } {
  return { label, value: value.trim() };
}

function name(first: string, last: string): string {
  return [first, last].filter(Boolean).join(" ");
}

function address(answers: WorkingApplicationAnswers): string {
  const value = answers.currentAddress;
  return [
    value.street,
    value.street2,
    [value.city, value.provinceOrState, value.postalOrZipCode].filter(Boolean).join(", "),
    value.country,
  ].filter(Boolean).join("\n");
}

function yesNo(value: boolean | null): string {
  if (value === null) return "";
  return value ? "Yes" : "No";
}

function reference(value: WorkingApplicationAnswers["currentLandlord"]): string {
  if (!value) return "";
  return [value.name, value.email, value.phone].filter(Boolean).join(" · ");
}

function employment(value: WorkingApplicationAnswers["applicantEmployment"] | null): string {
  if (!value) return "";
  const status = value.status?.replace("_", "-") ?? "";
  const manager = reference(value.manager);
  return [status, value.jobTitle, value.companyName, value.startDate, manager].filter(Boolean).join(" · ");
}

function money(value: number | null): string {
  if (value === null) return "";
  return value.toLocaleString("en-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0,
  });
}

function openingName(openings: ApplicantOpening[], openingId: number): string {
  const opening = openings.find((item) => item.id === openingId);
  return opening ? `${opening.unitSizeBedrooms}-bedroom home (${opening.moveInDate})` : `Opening ${openingId}`;
}

function shown(value: string): string {
  return value || "Not provided";
}
