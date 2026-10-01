import type { OpeningDetails } from "../types";

export type YesNo = "" | "yes" | "no";

export type ApplicantOpening = OpeningDetails & {
  phase: "upcoming" | "open" | "closed" | "archived";
  selected: boolean;
  participating: boolean;
  hasParticipated: boolean;
  canSelect: boolean;
  canWithdraw: boolean;
};

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

export type AddressDraft = {
  street: string;
  street2: string;
  city: string;
  provinceOrState: string;
  postalOrZipCode: string;
  country: string;
};

export type ResidenceDraft = {
  id: string;
  address: AddressDraft;
  moveInDate: string;
};

export type ApplicantDraft = {
  applicant: PersonDraft;
  coApplicant: PersonDraft & { relationship: string };
  hasCoApplicant: boolean;
  children: ChildDraft[];
  currentAddress: AddressDraft;
  currentAddressMoveInDate: string;
  previousResidences: ResidenceDraft[];
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
  householdPhotoLink: string;
  applicantEmployment: EmploymentDraft;
  coApplicantEmployment: EmploymentDraft;
  applicantIncome: string;
  coApplicantIncome: string;
};

export type CanonicalApplicationAnswers = {
  applicant: PersonDraft;
  coApplicant: (PersonDraft & { relationship: string }) | null;
  children: { firstName: string; lastName: string; birthDate: string }[];
  currentAddress: {
    street: string;
    street2: string | null;
    city: string;
    provinceOrState: string;
    postalOrZipCode: string;
    country: string;
  };
  currentAddressMoveInDate: string;
  previousResidences: {
    address: CanonicalApplicationAnswers["currentAddress"];
    moveInDate: string;
  }[];
  ownsCurrentHome: boolean;
  ownsOtherRealEstate: boolean;
  currentLandlord: ReferenceDraft | null;
  previousLandlord: ReferenceDraft | null;
  essays: ApplicantDraft["essays"];
  pets: string | null;
  householdPhotoLink: string | null;
  applicantEmployment: CanonicalEmployment;
  coApplicantEmployment: CanonicalEmployment | null;
  applicantIncome: number;
  coApplicantIncome: number | null;
};

export type WorkingApplicationAnswers = Omit<
  CanonicalApplicationAnswers,
  | "ownsCurrentHome"
  | "ownsOtherRealEstate"
  | "applicantEmployment"
  | "coApplicantEmployment"
  | "applicantIncome"
  | "coApplicantIncome"
> & {
  ownsCurrentHome: boolean | null;
  ownsOtherRealEstate: boolean | null;
  applicantEmployment: WorkingEmployment;
  coApplicantEmployment: WorkingEmployment | null;
  applicantIncome: number | null;
  coApplicantIncome: number | null;
};

export type CanonicalEmployment = {
  status: Exclude<EmploymentDraft["status"], "">;
  jobTitle: string | null;
  companyName: string | null;
  startDate: string | null;
  manager: ReferenceDraft | null;
};

export type WorkingEmployment = Omit<CanonicalEmployment, "status"> & {
  status: CanonicalEmployment["status"] | null;
};
