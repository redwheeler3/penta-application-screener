export type YesNo = "" | "yes" | "no";

export type PersonDraft = {
  firstName: string;
  lastName: string;
  birthDate: string;
  phone: string;
  email: string;
};

export type ReferenceDraft = {
  name: string;
  email: string;
  phone: string;
};

export type EmploymentDraft = {
  status: "" | "employed" | "self_employed" | "unemployed";
  jobTitle: string;
  companyName: string;
  startDate: string;
  manager: ReferenceDraft;
};

export type ChildDraft = {
  id: string;
  firstName: string;
  lastName: string;
  birthDate: string;
};

export type ApplicantDraft = {
  applicant: PersonDraft;
  coApplicant: PersonDraft & { relationship: string };
  hasCoApplicant: boolean;
  children: ChildDraft[];
  currentAddress: {
    street: string;
    street2: string;
    city: string;
    provinceOrState: string;
    postalOrZipCode: string;
    country: string;
  };
  livedAtCurrentAddressTwoYears: YesNo;
  ownsCurrentHome: YesNo;
  ownsOtherRealEstate: YesNo;
  currentLandlord: ReferenceDraft;
  previousLandlord: ReferenceDraft;
  essays: {
    householdIntroduction: string;
    skillsToContribute: string;
    previousCoopExperience: string;
    whyCoop: string;
    additionalInformation: string;
  };
  pets: string;
  applicantEmployment: EmploymentDraft;
  coApplicantEmployment: EmploymentDraft;
  applicantIncome: string;
  coApplicantIncome: string;
};

export type CanonicalApplicationAnswers = {
  applicant: CanonicalPerson;
  coApplicant: (CanonicalPerson & { relationship: string }) | null;
  children: { firstName: string; lastName: string; birthDate: string }[];
  currentAddress: {
    street: string;
    street2: string | null;
    city: string;
    provinceOrState: string;
    postalOrZipCode: string;
    country: string;
  };
  livedAtCurrentAddressTwoYears: boolean;
  ownsCurrentHome: boolean;
  ownsOtherRealEstate: boolean;
  currentLandlord: ReferenceDraft | null;
  previousLandlord: ReferenceDraft | null;
  essays: ApplicantDraft["essays"];
  pets: string | null;
  applicantEmployment: CanonicalEmployment;
  coApplicantEmployment: CanonicalEmployment | null;
  applicantIncome: number;
  coApplicantIncome: number | null;
};

export type WorkingApplicationAnswers = Omit<
  CanonicalApplicationAnswers,
  | "livedAtCurrentAddressTwoYears"
  | "ownsCurrentHome"
  | "ownsOtherRealEstate"
  | "applicantEmployment"
  | "coApplicantEmployment"
  | "applicantIncome"
  | "coApplicantIncome"
> & {
  livedAtCurrentAddressTwoYears: boolean | null;
  ownsCurrentHome: boolean | null;
  ownsOtherRealEstate: boolean | null;
  applicantEmployment: WorkingEmployment;
  coApplicantEmployment: WorkingEmployment | null;
  applicantIncome: number | null;
  coApplicantIncome: number | null;
};

type CanonicalPerson = PersonDraft;

type CanonicalEmployment = {
  status: Exclude<EmploymentDraft["status"], "">;
  jobTitle: string | null;
  companyName: string | null;
  startDate: string | null;
  manager: ReferenceDraft | null;
};

type WorkingEmployment = Omit<CanonicalEmployment, "status"> & {
  status: CanonicalEmployment["status"] | null;
};

const emptyPerson = (): PersonDraft => ({
  firstName: "",
  lastName: "",
  birthDate: "",
  phone: "",
  email: "",
});

const emptyReference = (): ReferenceDraft => ({ name: "", email: "", phone: "" });

const emptyEmployment = (): EmploymentDraft => ({
  status: "",
  jobTitle: "",
  companyName: "",
  startDate: "",
  manager: emptyReference(),
});

export function emptyApplicantDraft(): ApplicantDraft {
  return {
    applicant: emptyPerson(),
    coApplicant: { ...emptyPerson(), relationship: "" },
    hasCoApplicant: true,
    children: [],
    currentAddress: {
      street: "",
      street2: "",
      city: "",
      provinceOrState: "BC",
      postalOrZipCode: "",
      country: "Canada",
    },
    livedAtCurrentAddressTwoYears: "",
    ownsCurrentHome: "",
    ownsOtherRealEstate: "",
    currentLandlord: emptyReference(),
    previousLandlord: emptyReference(),
    essays: {
      householdIntroduction: "",
      skillsToContribute: "",
      previousCoopExperience: "",
      whyCoop: "",
      additionalInformation: "",
    },
    pets: "",
    applicantEmployment: emptyEmployment(),
    coApplicantEmployment: emptyEmployment(),
    applicantIncome: "",
    coApplicantIncome: "",
  };
}

export function newChild(): ChildDraft {
  return {
    id: crypto.randomUUID(),
    firstName: "",
    lastName: "",
    birthDate: "",
  };
}

export function householdIncome(draft: ApplicantDraft): number {
  const coApplicantIncome = draft.hasCoApplicant ? numberValue(draft.coApplicantIncome) : 0;
  return numberValue(draft.applicantIncome) + coApplicantIncome;
}

export function canonicalAnswers(draft: ApplicantDraft): CanonicalApplicationAnswers {
  const currentRenter = draft.ownsCurrentHome === "no";
  return {
    applicant: draft.applicant,
    coApplicant: draft.hasCoApplicant ? draft.coApplicant : null,
    children: draft.children.map(({ firstName, lastName, birthDate }) => ({
      firstName,
      lastName,
      birthDate,
    })),
    currentAddress: {
      ...draft.currentAddress,
      street2: draft.currentAddress.street2 || null,
    },
    livedAtCurrentAddressTwoYears: draft.livedAtCurrentAddressTwoYears === "yes",
    ownsCurrentHome: draft.ownsCurrentHome === "yes",
    ownsOtherRealEstate: draft.ownsOtherRealEstate === "yes",
    currentLandlord: currentRenter ? draft.currentLandlord : null,
    previousLandlord:
      currentRenter && draft.livedAtCurrentAddressTwoYears === "no"
        ? draft.previousLandlord
        : null,
    essays: draft.essays,
    pets: draft.pets.trim() || null,
    applicantEmployment: canonicalEmployment(draft.applicantEmployment),
    coApplicantEmployment: draft.hasCoApplicant
      ? canonicalEmployment(draft.coApplicantEmployment)
      : null,
    applicantIncome: numberValue(draft.applicantIncome),
    coApplicantIncome: draft.hasCoApplicant ? numberValue(draft.coApplicantIncome) : null,
  };
}

export function workingAnswers(draft: ApplicantDraft): WorkingApplicationAnswers {
  const currentRenter = draft.ownsCurrentHome === "no";
  return {
    ...canonicalAnswers(draft),
    livedAtCurrentAddressTwoYears: yesNoValue(draft.livedAtCurrentAddressTwoYears),
    ownsCurrentHome: yesNoValue(draft.ownsCurrentHome),
    ownsOtherRealEstate: yesNoValue(draft.ownsOtherRealEstate),
    applicantEmployment: workingEmployment(draft.applicantEmployment),
    coApplicantEmployment: draft.hasCoApplicant
      ? workingEmployment(draft.coApplicantEmployment)
      : null,
    applicantIncome: optionalNumberValue(draft.applicantIncome),
    coApplicantIncome: draft.hasCoApplicant
      ? optionalNumberValue(draft.coApplicantIncome)
      : null,
    currentLandlord: currentRenter ? draft.currentLandlord : null,
    previousLandlord:
      currentRenter && draft.livedAtCurrentAddressTwoYears === "no"
        ? draft.previousLandlord
        : null,
  };
}

export function draftFromWorking(answers: WorkingApplicationAnswers): ApplicantDraft {
  const draft = emptyApplicantDraft();
  return {
    ...draft,
    applicant: answers.applicant,
    coApplicant: answers.coApplicant ?? draft.coApplicant,
    hasCoApplicant: answers.coApplicant !== null,
    children: answers.children.map((child) => ({ ...child, id: crypto.randomUUID() })),
    currentAddress: { ...answers.currentAddress, street2: answers.currentAddress.street2 ?? "" },
    livedAtCurrentAddressTwoYears: yesNoDraft(answers.livedAtCurrentAddressTwoYears),
    ownsCurrentHome: yesNoDraft(answers.ownsCurrentHome),
    ownsOtherRealEstate: yesNoDraft(answers.ownsOtherRealEstate),
    currentLandlord: answers.currentLandlord ?? draft.currentLandlord,
    previousLandlord: answers.previousLandlord ?? draft.previousLandlord,
    essays: answers.essays,
    pets: answers.pets ?? "",
    applicantEmployment: draftEmployment(answers.applicantEmployment),
    coApplicantEmployment: answers.coApplicantEmployment
      ? draftEmployment(answers.coApplicantEmployment)
      : draft.coApplicantEmployment,
    applicantIncome: answers.applicantIncome === null ? "" : String(answers.applicantIncome),
    coApplicantIncome:
      answers.coApplicantIncome === null ? "" : String(answers.coApplicantIncome),
  };
}

function canonicalEmployment(employment: EmploymentDraft): CanonicalEmployment {
  if (employment.status === "unemployed") {
    return {
      status: employment.status,
      jobTitle: null,
      companyName: null,
      startDate: null,
      manager: null,
    };
  }
  return {
    status: employment.status as CanonicalEmployment["status"],
    jobTitle: employment.jobTitle,
    companyName: employment.companyName,
    startDate: employment.startDate,
    manager: employment.status === "employed" ? employment.manager : null,
  };
}

function workingEmployment(employment: EmploymentDraft): WorkingEmployment {
  return {
    status: employment.status || null,
    jobTitle: employment.jobTitle,
    companyName: employment.companyName,
    startDate: employment.startDate,
    manager: employment.status === "employed" ? employment.manager : null,
  };
}

function draftEmployment(employment: WorkingEmployment): EmploymentDraft {
  return {
    status: employment.status ?? "",
    jobTitle: employment.jobTitle ?? "",
    companyName: employment.companyName ?? "",
    startDate: employment.startDate ?? "",
    manager: employment.manager ?? emptyReference(),
  };
}

function yesNoValue(value: YesNo): boolean | null {
  if (!value) return null;
  return value === "yes";
}

function yesNoDraft(value: boolean | null): YesNo {
  if (value === null) return "";
  return value ? "yes" : "no";
}

function optionalNumberValue(value: string): number | null {
  return value.trim() ? numberValue(value) : null;
}

function numberValue(value: string): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}
