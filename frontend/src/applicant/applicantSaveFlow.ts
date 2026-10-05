import type { RefObject } from "react";
import type { RequestIsCurrent } from "../hooks/useRequestScope";

import { TECH_SUPPORT_ERROR_MESSAGE } from "../support";
import { APPLICATION_ACCESS_EMAIL_MESSAGE } from "./accessMessages";
import {
  APPLICANT_ACTION_ERROR_MESSAGE,
  type ApplicationResponse,
  type EmailSendStatus,
  workingSnapshot,
} from "./applicantPersistence";
import type {
  ApplicantPersistenceState,
  UpdateApplicantPersistence,
} from "./applicantPersistenceState";
import type * as publicApi from "./api";
import { requestReturnAccessLink as requestBootstrapAccessLink } from "./api";
import { type DraftIntent } from "./api";
import { BROWSER_STORAGE_CLEAR_MESSAGE, clearApplicationDraft } from "./draftStorage";
import {
  canonicalAnswers,
  residenceHistoryCutoff,
  workingAnswers,
} from "./applicationDraft";
import type { ApplicantDraft } from "./types";

type SaveFlowDependencies = {
  api: ReturnType<typeof publicApi.createApi>;
  stateRef: RefObject<ApplicantPersistenceState>;
  draftRef: RefObject<ApplicantDraft>;
  invalidateReads: () => void;
  captureSession: () => RequestIsCurrent;
  updatePersistence: UpdateApplicantPersistence;
  fail: (response: Response) => Promise<void>;
};

/** Saving, review preparation, and submission share one snapshot acknowledgement rule. */
export function createApplicantSaveFlow({
  api,
  stateRef, draftRef, updatePersistence: dispatch, invalidateReads, captureSession, fail,
}: SaveFlowDependencies) {
  const { checkGuestSubmission, requestReturnAccessLink, saveApplication, savePendingDraft, submitApplication, submitGuestApplication } = api;
  const inSession = captureSession();
  const updatePersistence: UpdateApplicantPersistence = (patch) => {
    if (inSession()) dispatch(patch);
  };
  async function start(intent: DraftIntent): Promise<void> {
    if (!inSession()) return;
    const { applicationId, openingIds, pendingDraftToken } = stateRef.current;
    invalidateReads();
    updatePersistence({ lastIntent: intent, message: "", phase: "working" });
    if (applicationId != null) {
      await persistAuthenticatedApplication(intent);
      return;
    }
    if (intent === "submit") {
      await persistGuestApplication();
      return;
    }

    const snapshot = workingSnapshot(draftRef.current, openingIds);
    const response = await savePendingDraft(
      workingAnswers(draftRef.current),
      intent,
      pendingDraftToken,
      openingIds,
    );
    if (!inSession()) return;
    if (!response.ok) return fail(response);
    const body = (await response.json()) as {
      draftToken: string;
      emailSent: boolean;
      emailStatus: EmailSendStatus;
    };
    if (!inSession()) return;
    updatePersistence({
      savedAnswers: snapshot,
      pendingDraftToken: body.draftToken,
      phase: body.emailStatus === "failed" ? "email_failed" : "email_sent",
      message: body.emailStatus === "failed"
        ? TECH_SUPPORT_ERROR_MESSAGE
        : body.emailSent
          ? "Your application is saved. Use the link in your email to open it again."
          : "Your application is saved. Check your inbox for the link we sent recently.",
    });
  }

  async function saveForReview(): Promise<boolean> {
    if (!inSession()) return false;
    if (stateRef.current.applicationId == null) return true;
    updatePersistence({ lastIntent: "save", message: "", phase: "working" });
    const saved = await persistAuthenticatedApplication("save");
    if (!inSession()) return false;
    if (saved) updatePersistence({ phase: "idle" });
    return saved;
  }

  async function prepareGuestReview(): Promise<boolean> {
    if (!inSession()) return false;
    const { applicationId, openingIds } = stateRef.current;
    if (applicationId != null) return true;
    updatePersistence({ lastIntent: "submit", message: "", phase: "working" });
    const email = draftRef.current.applicant.email.trim().toLowerCase();
    const response = await checkGuestSubmission(
      workingAnswers(draftRef.current),
      openingIds,
    );
    if (!inSession()) return false;
    if (!response.ok) {
      await fail(response);
      return false;
    }
    const body = (await response.json()) as {
      canSubmit: boolean;
      emailSent: boolean;
      emailStatus: EmailSendStatus | null;
    };
    if (!inSession()) return false;
    if (!body.canSubmit) {
      updatePersistence({ collisionEmail: email });
      if (body.emailStatus === "failed") {
        updatePersistence({ message: TECH_SUPPORT_ERROR_MESSAGE, phase: "error" });
      } else {
        updatePersistence({ message: APPLICATION_ACCESS_EMAIL_MESSAGE, phase: "authentication_required" });
      }
      return false;
    }
    updatePersistence({ phase: "idle" });
    return true;
  }

  async function persistGuestApplication(): Promise<void> {
    if (!inSession()) return;
    const { openingIds, pendingDraftToken, openings } = stateRef.current;
    const snapshot = workingSnapshot(draftRef.current, openingIds);
    const response = await submitGuestApplication(
      canonicalAnswers(draftRef.current, residenceHistoryCutoff(openings)),
      true,
      openingIds,
      pendingDraftToken,
    );
    if (!inSession()) return;
    if (!response.ok) return fail(response);
    updatePersistence({ savedAnswers: snapshot, message: "", phase: "submitted" });
  }

  async function persistAuthenticatedApplication(intent: DraftIntent): Promise<boolean> {
    if (!inSession()) return false;
    const { applicationId, workingRevision, openingIds, openings } = stateRef.current;
    invalidateReads();
    if (workingRevision == null) {
      updatePersistence({ message: TECH_SUPPORT_ERROR_MESSAGE, phase: "error" });
      return false;
    }
    const snapshot = workingSnapshot(draftRef.current, openingIds);
    const response = intent === "submit"
      ? await submitApplication(
          canonicalAnswers(draftRef.current, residenceHistoryCutoff(openings)),
          true,
          openingIds,
          workingRevision,
        )
      : await saveApplication(workingAnswers(draftRef.current), openingIds, workingRevision);
    if (!inSession()) return false;
    if (!response.ok) {
      await fail(response);
      return false;
    }
    const body = (await response.json()) as ApplicationResponse;
    if (!inSession()) return false;
    // Reads started during this save can still describe the pre-save revision.
    invalidateReads();
    updatePersistence({
      workingRevision: body.workingRevision,
      openings: body.openings,
      canEdit: body.canEdit,
      savedAnswers: snapshot,
      message: "",
      phase: intent === "submit" ? "submitted" : "saved",
    });
    if (intent === "submit" && applicationId != null
      && snapshot === workingSnapshot(draftRef.current, stateRef.current.openingIds)) {
      if (!(await clearApplicationDraft(applicationId))) {
        updatePersistence({ browserStorageMessage: BROWSER_STORAGE_CLEAR_MESSAGE });
      }
    }
    return inSession();
  }

  async function emailReturnLink(): Promise<boolean> {
    if (!inSession()) return false;
    const { openingIds, workingRevision } = stateRef.current;
    invalidateReads();
    const snapshot = workingSnapshot(draftRef.current, openingIds);
    const response = await requestReturnAccessLink(
      workingAnswers(draftRef.current),
      openingIds,
      workingRevision,
    );
    if (!inSession()) return false;
    if (!response.ok) {
      await fail(response);
      return false;
    }
    const body = (await response.json()) as {
      currentAnswersSaved: boolean;
      workingRevision: number | null;
      emailStatus: EmailSendStatus;
    };
    if (!inSession()) return false;
    if (body.currentAnswersSaved) {
      invalidateReads();
      updatePersistence({ savedAnswers: snapshot, workingRevision: body.workingRevision });
    }
    return body.emailStatus !== "failed";
  }

  async function requestEntryLink(email: string): Promise<boolean> {
    if (!inSession()) return false;
    const { openingIds } = stateRef.current;
    const working = workingAnswers(draftRef.current);
    const answers = { ...working, applicant: { ...working.applicant, email: email.trim().toLowerCase() } };
    const response = await requestBootstrapAccessLink(answers, openingIds, null);
    if (!inSession()) return false;
    if (!response.ok) {
      await fail(response);
      return false;
    }
    const body = (await response.json()) as { emailStatus: EmailSendStatus };
    if (!inSession()) return false;
    if (body.emailStatus === "failed") {
      updatePersistence({ message: TECH_SUPPORT_ERROR_MESSAGE, phase: "error" });
      return false;
    }
    updatePersistence({ message: APPLICATION_ACCESS_EMAIL_MESSAGE, phase: "access_link_sent" });
    return true;
  }

  async function emailSessionAccessLink(): Promise<void> {
    updatePersistence({ phase: "working" });
    await requestEntryLink(stateRef.current.primaryEmail || draftRef.current.applicant.email);
  }

  async function resendCurrentIntent(): Promise<void> {
    await start(stateRef.current.lastIntent);
  }

  async function recoverSave<Result>(operation: () => Promise<Result>, fallback: Result): Promise<Result> {
    try {
      return await operation();
    } catch {
      // A lost response does not prove the server rejected the write. Keep the
      // draft and its last acknowledged revision, allowing a safe retry or reload.
      updatePersistence({ message: APPLICANT_ACTION_ERROR_MESSAGE, phase: "error" });
      return fallback;
    }
  }

  return {
    start: (intent: DraftIntent) => recoverSave(() => start(intent), undefined),
    saveForReview: () => recoverSave(saveForReview, false),
    prepareGuestReview: () => recoverSave(prepareGuestReview, false),
    emailReturnLink: () => recoverSave(emailReturnLink, false),
    requestEntryLink: (email: string) => recoverSave(() => requestEntryLink(email), false),
    emailSessionAccessLink: () => recoverSave(emailSessionAccessLink, undefined),
    resendCurrentIntent: () => recoverSave(resendCurrentIntent, undefined),
  };
}
