import type { RefObject } from "react";

import { TECH_SUPPORT_ERROR_MESSAGE } from "../support";
import { APPLICATION_ACCESS_EMAIL_MESSAGE } from "./accessMessages";
import {
  type ApplicationResponse,
  type EmailSendStatus,
  workingSnapshot,
} from "./applicantPersistence";
import type {
  ApplicantPersistenceState,
  UpdateApplicantPersistence,
} from "./applicantPersistenceState";
import {
  checkGuestSubmission,
  type DraftIntent,
  requestReturnAccessLink,
  saveApplication,
  savePendingDraft,
  submitApplication,
  submitGuestApplication,
} from "./api";
import { clearApplicationDraft } from "./draftStorage";
import {
  canonicalAnswers,
  residenceHistoryCutoff,
  workingAnswers,
} from "./applicationDraft";
import type { ApplicantDraft } from "./types";

type SaveFlowDependencies = {
  stateRef: RefObject<ApplicantPersistenceState>;
  draftRef: RefObject<ApplicantDraft>;
  invalidateReads: () => void;
  updatePersistence: UpdateApplicantPersistence;
  fail: (response: Response) => Promise<void>;
};

/** Saving, review preparation, and submission share one snapshot acknowledgement rule. */
export function createApplicantSaveFlow({
  stateRef, draftRef, updatePersistence, invalidateReads, fail,
}: SaveFlowDependencies) {
  async function start(intent: DraftIntent): Promise<void> {
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
    if (!response.ok) return fail(response);
    const body = (await response.json()) as {
      draftToken: string;
      emailSent: boolean;
      emailStatus: EmailSendStatus;
    };
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
    if (stateRef.current.applicationId == null) return true;
    updatePersistence({ lastIntent: "save", message: "", phase: "working" });
    const saved = await persistAuthenticatedApplication("save");
    if (saved) updatePersistence({ phase: "idle" });
    return saved;
  }

  async function prepareGuestReview(): Promise<boolean> {
    const { applicationId, openingIds } = stateRef.current;
    if (applicationId != null) return true;
    updatePersistence({ lastIntent: "submit", message: "", phase: "working" });
    const email = draftRef.current.applicant.email.trim().toLowerCase();
    const response = await checkGuestSubmission(
      workingAnswers(draftRef.current),
      openingIds,
    );
    if (!response.ok) {
      await fail(response);
      return false;
    }
    const body = (await response.json()) as {
      canSubmit: boolean;
      emailSent: boolean;
      emailStatus: EmailSendStatus | null;
    };
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
    const { openingIds, pendingDraftToken, openings } = stateRef.current;
    const snapshot = workingSnapshot(draftRef.current, openingIds);
    const response = await submitGuestApplication(
      canonicalAnswers(draftRef.current, residenceHistoryCutoff(openings)),
      true,
      openingIds,
      pendingDraftToken,
    );
    if (!response.ok) return fail(response);
    updatePersistence({ savedAnswers: snapshot, message: "", phase: "submitted" });
  }

  async function persistAuthenticatedApplication(intent: DraftIntent): Promise<boolean> {
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
    if (!response.ok) {
      await fail(response);
      return false;
    }
    const body = (await response.json()) as ApplicationResponse;
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
      clearApplicationDraft(applicationId);
    }
    return true;
  }

  async function emailReturnLink(): Promise<boolean> {
    const { openingIds, workingRevision } = stateRef.current;
    invalidateReads();
    const snapshot = workingSnapshot(draftRef.current, openingIds);
    const response = await requestReturnAccessLink(
      workingAnswers(draftRef.current),
      openingIds,
      workingRevision,
    );
    if (!response.ok) {
      await fail(response);
      return false;
    }
    const body = (await response.json()) as {
      currentAnswersSaved: boolean;
      emailStatus: EmailSendStatus;
    };
    if (body.emailStatus === "failed") return false;
    if (body.currentAnswersSaved) {
      updatePersistence({ savedAnswers: snapshot });
    }
    return true;
  }

  async function requestEntryLink(email: string): Promise<boolean> {
    const { openingIds } = stateRef.current;
    const working = workingAnswers(draftRef.current);
    const answers = { ...working, applicant: { ...working.applicant, email: email.trim().toLowerCase() } };
    const response = await requestReturnAccessLink(answers, openingIds, null);
    if (!response.ok) {
      await fail(response);
      return false;
    }
    const body = (await response.json()) as { emailStatus: EmailSendStatus };
    if (body.emailStatus === "failed") {
      updatePersistence({ message: TECH_SUPPORT_ERROR_MESSAGE, phase: "error" });
      return false;
    }
    updatePersistence({ message: APPLICATION_ACCESS_EMAIL_MESSAGE, phase: "access_link_sent" });
    return true;
  }

  async function emailSessionAccessLink(): Promise<void> {
    updatePersistence({ phase: "working" });
    if (await emailReturnLink()) {
      updatePersistence({ message: APPLICATION_ACCESS_EMAIL_MESSAGE, phase: "access_link_sent" });
      return;
    }
    updatePersistence({ message: TECH_SUPPORT_ERROR_MESSAGE, phase: "error" });
  }

  async function resendCurrentIntent(): Promise<void> {
    await start(stateRef.current.lastIntent);
  }

  return {
    start, saveForReview, prepareGuestReview, emailReturnLink, requestEntryLink,
    emailSessionAccessLink, resendCurrentIntent,
  };
}
