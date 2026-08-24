import { emptyApplicantDraft, type ApplicantDraft } from "./types";

const STORAGE_KEY = "penta-application-draft-v1";
const MAX_INACTIVE_MS = 30 * 24 * 60 * 60 * 1000;

type StoredDraft = {
  savedAt: string;
  draft: ApplicantDraft;
};

export type LoadedDraft = {
  draft: ApplicantDraft;
  savedAt: Date | null;
};

export function loadDraft(now = new Date()): LoadedDraft {
  const serialized = localStorage.getItem(STORAGE_KEY);
  if (!serialized) return { draft: emptyApplicantDraft(), savedAt: null };

  try {
    const stored = JSON.parse(serialized) as Partial<StoredDraft>;
    const savedAt = new Date(stored.savedAt ?? "");
    if (
      !stored.draft ||
      !Number.isFinite(savedAt.getTime()) ||
      now.getTime() - savedAt.getTime() > MAX_INACTIVE_MS
    ) {
      clearDraft();
      return { draft: emptyApplicantDraft(), savedAt: null };
    }
    const defaults = emptyApplicantDraft();
    return {
      draft: {
        ...defaults,
        ...stored.draft,
        applicantEmployment: {
          ...defaults.applicantEmployment,
          ...stored.draft.applicantEmployment,
        },
        coApplicantEmployment: {
          ...defaults.coApplicantEmployment,
          ...stored.draft.coApplicantEmployment,
        },
      },
      savedAt,
    };
  } catch {
    clearDraft();
    return { draft: emptyApplicantDraft(), savedAt: null };
  }
}

export function saveDraft(draft: ApplicantDraft, now = new Date()): Date {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ savedAt: now.toISOString(), draft }));
  return now;
}

export function clearDraft(): void {
  localStorage.removeItem(STORAGE_KEY);
}

export function hasDraftContent(draft: ApplicantDraft): boolean {
  return Boolean(
    draft.applicant.firstName.trim() ||
      draft.applicant.lastName.trim() ||
      draft.applicant.email.trim() ||
      draft.children.length ||
      draft.essays.householdIntroduction.trim(),
  );
}
