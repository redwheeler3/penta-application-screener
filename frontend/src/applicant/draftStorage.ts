import { emptyApplicantDraft, type ApplicantDraft } from "./types";

const DRAFTS_KEY = "penta-application-drafts-v4";
const REMEMBER_DEVICE_KEY = "penta-application-remember-device-v1";
const MAX_INACTIVE_MS = 30 * 24 * 60 * 60 * 1000;

type StoredDraft = {
  savedAt: string;
  draft: ApplicantDraft;
  openingIds: number[];
  baseRevision: number;
};
type StoredDrafts = Record<string, StoredDraft>;

export type LoadedDraft = Omit<StoredDraft, "savedAt"> & { savedAt: Date };

export function remembersDevice(): boolean {
  return localStorage.getItem(REMEMBER_DEVICE_KEY) === "true";
}

export function setRememberDevice(remember: boolean): void {
  if (remember) localStorage.setItem(REMEMBER_DEVICE_KEY, "true");
  else {
    localStorage.removeItem(REMEMBER_DEVICE_KEY);
    localStorage.removeItem(DRAFTS_KEY);
  }
}

export function loadApplicationDraft(applicationId: number, now = new Date()): LoadedDraft | null {
  const drafts = readDrafts();
  const stored = drafts[String(applicationId)];
  if (!stored) return null;
  const savedAt = new Date(stored.savedAt);
  if (!Number.isFinite(savedAt.getTime()) || now.getTime() - savedAt.getTime() > MAX_INACTIVE_MS) {
    clearApplicationDraft(applicationId);
    return null;
  }
  const defaults = emptyApplicantDraft();
  return {
    draft: {
      ...defaults,
      ...stored.draft,
      applicantEmployment: { ...defaults.applicantEmployment, ...stored.draft.applicantEmployment },
      coApplicantEmployment: {
        ...defaults.coApplicantEmployment,
        ...stored.draft.coApplicantEmployment,
      },
    },
    openingIds: stored.openingIds,
    baseRevision: stored.baseRevision,
    savedAt,
  };
}

export function saveApplicationDraft(
  applicationId: number,
  draft: ApplicantDraft,
  openingIds: number[],
  baseRevision: number,
  now = new Date(),
): Date {
  const drafts = readDrafts();
  drafts[String(applicationId)] = {
    savedAt: now.toISOString(),
    draft,
    openingIds,
    baseRevision,
  };
  writeDrafts(drafts);
  return now;
}

export function clearApplicationDraft(applicationId: number): void {
  const drafts = readDrafts();
  delete drafts[String(applicationId)];
  writeDrafts(drafts);
}

export function clearApplicantStorage(): void {
  localStorage.removeItem(DRAFTS_KEY);
  localStorage.removeItem(REMEMBER_DEVICE_KEY);
}

export function hasDraftContent(draft: ApplicantDraft): boolean {
  return Boolean(draft.applicant.email.trim() || hasAnswersBeyondEmail(draft));
}

export function hasAnswersBeyondEmail(draft: ApplicantDraft): boolean {
  const references = [draft.currentLandlord, draft.previousLandlord];
  const employment = [draft.applicantEmployment, draft.coApplicantEmployment];
  const coApplicant = Object.values(draft.coApplicant);
  return Boolean(
    draft.applicant.firstName.trim() ||
      draft.applicant.lastName.trim() ||
      draft.applicant.birthDate.trim() ||
      draft.applicant.phone.trim() ||
      coApplicant.some((value) => value.trim()) ||
      draft.children.length ||
      draft.currentAddress.street.trim() ||
      draft.currentAddress.street2.trim() ||
      draft.currentAddress.city.trim() ||
      draft.currentAddress.postalOrZipCode.trim() ||
      draft.currentAddress.provinceOrState !== "BC" ||
      draft.currentAddress.country !== "Canada" ||
      draft.livedAtCurrentAddressTwoYears ||
      draft.ownsCurrentHome ||
      draft.ownsOtherRealEstate ||
      references.some((reference) => Object.values(reference).some((value) => value.trim())) ||
      Object.values(draft.essays).some((value) => value.trim()) ||
      draft.pets.trim() ||
      employment.some((job) => (
        job.status ||
        job.jobTitle.trim() ||
        job.companyName.trim() ||
        job.startDate.trim() ||
        Object.values(job.manager).some((value) => value.trim())
      )) ||
      draft.applicantIncome.trim() ||
      draft.coApplicantIncome.trim()
  );
}

function readDrafts(): StoredDrafts {
  try {
    return JSON.parse(localStorage.getItem(DRAFTS_KEY) || "{}") as StoredDrafts;
  } catch {
    return {};
  }
}

function writeDrafts(drafts: StoredDrafts): void {
  localStorage.setItem(DRAFTS_KEY, JSON.stringify(drafts));
}
