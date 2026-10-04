import { emptyApplicantDraft } from "./applicationDraft";
import type { ApplicantDraft } from "./types";

const DRAFTS_KEY = "penta-application-drafts-v5";
const REMEMBER_DEVICE_KEY = "penta-application-remember-device-v1";

type StoredDraft = {
  savedAt: string;
  draft: ApplicantDraft;
  openingIds: number[];
  baseRevision: number;
};
type StoredDrafts = Record<string, StoredDraft>;

export type LoadedDraft = Omit<StoredDraft, "savedAt"> & { savedAt: Date };

export function remembersDevice(): boolean {
  return rememberedStorageScope() !== null;
}

export function rememberedStorageScope(): string | null {
  try {
    return localStorage.getItem(REMEMBER_DEVICE_KEY);
  } catch {
    return null;
  }
}

async function withStorageLock<T>(operation: () => T): Promise<T> {
  if (!navigator.locks) return operation();
  return navigator.locks.request(DRAFTS_KEY, operation);
}

export async function setRememberDevice(remember: boolean): Promise<string | null> {
  return withStorageLock(() => {
    if (!remember) {
      localStorage.removeItem(REMEMBER_DEVICE_KEY);
      localStorage.removeItem(DRAFTS_KEY);
      return null;
    }
    if (!navigator.locks) return null; // server saves remain available without browser persistence
    // Store the consent lifetime in the existing preference value, not a separate record.
    const scope = crypto.randomUUID();
    localStorage.setItem(REMEMBER_DEVICE_KEY, scope);
    return scope;
  });
}

export function observeRememberedStorage(onChange: () => void): () => void {
  const changed = (event: StorageEvent) => {
    if (event.storageArea === localStorage && (event.key === null || event.key === REMEMBER_DEVICE_KEY)) {
      onChange();
    }
  };
  window.addEventListener("storage", changed);
  return () => window.removeEventListener("storage", changed);
}

export function loadApplicationDraft(applicationId: number): LoadedDraft | null {
  const drafts = readDrafts();
  const stored = drafts[String(applicationId)];
  if (!stored) return null;
  const savedAt = new Date(stored.savedAt);
  if (!Number.isFinite(savedAt.getTime())) {
    void clearApplicationDraft(applicationId);
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

export async function saveApplicationDraft(
  applicationId: number,
  draft: ApplicantDraft,
  openingIds: number[],
  baseRevision: number,
  consentScope: string,
  now = new Date(),
): Promise<Date | null> {
  if (!navigator.locks) return null;
  return withStorageLock(() => {
    if (rememberedStorageScope() !== consentScope) return null;
    const drafts = readDrafts();
    drafts[String(applicationId)] = {
      savedAt: now.toISOString(),
      draft,
      openingIds,
      baseRevision,
    };
    writeDrafts(drafts);
    return now;
  });
}

export async function clearApplicationDraft(applicationId: number): Promise<void> {
  const scope = rememberedStorageScope();
  await withStorageLock(() => {
    if (scope === null || rememberedStorageScope() !== scope) return;
    const drafts = readDrafts();
    delete drafts[String(applicationId)];
    writeDrafts(drafts);
  });
}

export async function clearApplicantStorage(): Promise<void> {
  await withStorageLock(() => {
    localStorage.removeItem(DRAFTS_KEY);
    localStorage.removeItem(REMEMBER_DEVICE_KEY);
  });
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
      draft.currentAddressMoveInDate.trim() ||
      draft.previousResidences.some((residence) => (
        residence.moveInDate.trim()
        || Object.values(residence.address).some((value) => value.trim())
      )) ||
      draft.ownsCurrentHome ||
      draft.ownsOtherRealEstate ||
      references.some((reference) => Object.values(reference).some((value) => value.trim())) ||
      Object.values(draft.essays).some((value) => value.trim()) ||
      draft.pets.trim() ||
      draft.householdPhotoLink.trim() ||
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
