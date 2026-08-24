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
  };
  pets: string;
  applicantEmployment: EmploymentDraft;
  coApplicantEmployment: EmploymentDraft;
  applicantIncome: string;
  coApplicantIncome: string;
  declarationAccepted: boolean;
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
    },
    pets: "",
    applicantEmployment: emptyEmployment(),
    coApplicantEmployment: emptyEmployment(),
    applicantIncome: "",
    coApplicantIncome: "",
    declarationAccepted: false,
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

function numberValue(value: string): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}
