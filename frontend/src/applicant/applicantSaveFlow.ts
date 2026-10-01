import type { Dispatch, RefObject } from "react";

import { TECH_SUPPORT_ERROR_MESSAGE } from "../support";
import { APPLICATION_ACCESS_EMAIL_MESSAGE } from "./accessMessages";
import {
  type ApplicationResponse,
  type EmailSendStatus,
  workingSnapshot,
} from "./applicantPersistence";
import type {
  ApplicantPersistenceAction,
  ApplicantPersistenceState,
  SetApplicantPersistence,
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
  type ApplicantDraft,
  canonicalAnswers,
  residenceHistoryCutoff,
  workingAnswers,
} from "./types";

type SaveFlowDependencies = {
  state: ApplicantPersistenceState;
  getCurrentState: () => ApplicantPersistenceState;
  draftRef: RefObject<ApplicantDraft>;
  dispatch: Dispatch<ApplicantPersistenceAction>;
  invalidateReads: () => void;
  setPersistence: SetApplicantPersistence;
  fail: (response: Response) => Promise<void>;
};

/** Saving, review preparation, and submission share one snapshot acknowledgement rule. */
export function createApplicantSaveFlow({
  state, getCurrentState, draftRef, dispatch, invalidateReads, setPersistence, fail,
}: SaveFlowDependencies) {
  const { applicationId, workingRevision, openingIds, pendingDraftToken, openings, lastIntent } = state;

  async function start(intent: DraftIntent): Promise<void> {
    invalidateReads();
    dispatch({ type: "save_started", intent });
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
    dispatch({
      type: "save_completed",
      snapshot,
      draftToken: body.draftToken,
      phase: body.emailStatus === "failed" ? "email_failed" : "email_sent",
      message: body.emailStatus === "failed"
        ? TECH_SUPPORT_ERROR_MESSAGE
        : body.emailSent
          ? "Your application is saved. Use the link in your email to open it again."
          : "Your application is saved. Check your inbox for the link we sent recently.",
    });
  }

  async function saveForReview(): Promise<boolean> {
    if (applicationId == null) return true;
    dispatch({ type: "save_started", intent: "save" });
    const saved = await persistAuthenticatedApplication("save");
    if (saved) setPersistence("phase", "idle");
    return saved;
  }

  async function prepareGuestReview(): Promise<boolean> {
    if (applicationId != null) return true;
    dispatch({ type: "save_started", intent: "submit" });
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
      setPersistence("collisionEmail", email);
      if (body.emailStatus === "failed") {
        setPersistence("message", TECH_SUPPORT_ERROR_MESSAGE);
        setPersistence("phase", "error");
      } else {
        setPersistence("message", APPLICATION_ACCESS_EMAIL_MESSAGE);
        setPersistence("phase", "authentication_required");
      }
      return false;
    }
    setPersistence("phase", "idle");
    return true;
  }

  async function persistGuestApplication(): Promise<void> {
    const snapshot = workingSnapshot(draftRef.current, openingIds);
    const response = await submitGuestApplication(
      canonicalAnswers(draftRef.current, residenceHistoryCutoff(openings)),
      true,
      openingIds,
      pendingDraftToken,
    );
    if (!response.ok) return fail(response);
    dispatch({ type: "save_completed", snapshot, phase: "submitted" });
  }

  async function persistAuthenticatedApplication(intent: DraftIntent): Promise<boolean> {
    invalidateReads();
    if (workingRevision == null) {
      dispatch({ type: "action_failed", message: TECH_SUPPORT_ERROR_MESSAGE });
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
    dispatch({ type: "save_completed", snapshot, application: body,
      phase: intent === "submit" ? "submitted" : "saved" });
    if (intent === "submit" && applicationId != null
      && snapshot === workingSnapshot(draftRef.current, getCurrentState().openingIds)) {
      clearApplicationDraft(applicationId);
    }
    return true;
  }

  async function emailReturnLink(): Promise<boolean> {
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
      setPersistence("savedAnswers", snapshot);
    }
    return true;
  }

  async function requestEntryLink(email: string): Promise<boolean> {
    const working = workingAnswers(draftRef.current);
    const answers = { ...working, applicant: { ...working.applicant, email: email.trim().toLowerCase() } };
    const response = await requestReturnAccessLink(answers, openingIds, null);
    if (!response.ok) {
      await fail(response);
      return false;
    }
    const body = (await response.json()) as { emailStatus: EmailSendStatus };
    if (body.emailStatus === "failed") {
      setPersistence("message", TECH_SUPPORT_ERROR_MESSAGE);
      setPersistence("phase", "error");
      return false;
    }
    setPersistence("message", APPLICATION_ACCESS_EMAIL_MESSAGE);
    setPersistence("phase", "access_link_sent");
    return true;
  }

  async function emailSessionAccessLink(): Promise<void> {
    setPersistence("phase", "working");
    if (await emailReturnLink()) {
      setPersistence("message", APPLICATION_ACCESS_EMAIL_MESSAGE);
      setPersistence("phase", "access_link_sent");
      return;
    }
    setPersistence("message", TECH_SUPPORT_ERROR_MESSAGE);
    setPersistence("phase", "error");
  }

  async function resendCurrentIntent(): Promise<void> {
    await start(lastIntent);
  }

  return {
    start, saveForReview, prepareGuestReview, emailReturnLink, requestEntryLink,
    emailSessionAccessLink, resendCurrentIntent,
  };
}
