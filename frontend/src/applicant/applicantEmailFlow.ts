import type { Dispatch, SetStateAction } from "react";
import type { RequestIsCurrent } from "../hooks/useRequestScope";

import { TECH_SUPPORT_ERROR_MESSAGE } from "../support";
import {
  APPLICANT_ACTION_ERROR_MESSAGE,
  type ApplicationResponse,
  type EmailSendStatus,
  responseDetail,
  responseProblem,
  updateSnapshotEmail,
} from "./applicantPersistence";
import type { UpdateApplicantPersistence } from "./applicantPersistenceState";
import type * as publicApi from "./api";
import type { ApplicantDraft } from "./types";

type EmailFlowDependencies = {
  api: ReturnType<typeof publicApi.createApi>;
  beginApplicationRead: () => RequestIsCurrent;
  captureSession: () => RequestIsCurrent;
  updatePersistence: UpdateApplicantPersistence;
  setDraft: Dispatch<SetStateAction<ApplicantDraft>>;
};

export function createApplicantEmailFlow({
  api,
  beginApplicationRead,
  captureSession,
  updatePersistence: dispatch,
  setDraft: dispatchDraft,
}: EmailFlowDependencies) {
  const { cancelEmailChange, fetchApplication, requestEmailChange } = api;
  const inSession = captureSession();
  const updatePersistence: UpdateApplicantPersistence = (patch) => {
    if (inSession()) dispatch(patch);
  };
  const setDraft: Dispatch<SetStateAction<ApplicantDraft>> = (patch) => {
    if (inSession()) dispatchDraft(patch);
  };
  async function beginEmailChange(newEmail: string): Promise<void> {
    if (!inSession()) return;
    updatePersistence({
      emailChangeStatus: "sending",
      emailChangeMessage: "",
      googleDisconnectedByEmailChange: false,
    });
    const response = await requestEmailChange(newEmail);
    if (!inSession()) return;
    if (!response.ok) {
      const problem = await responseProblem(response);
      updatePersistence({ emailChangeMessage: problem.detail, emailChangeStatus: "error" });
      return;
    }
    const body = (await response.json()) as {
      emailSent: boolean;
      emailStatus: EmailSendStatus;
      pendingEmail: string | null;
    };
    updatePersistence({ pendingEmailChange: body.pendingEmail });
    if (body.pendingEmail === null) {
      updatePersistence({ emailChangeMessage: TECH_SUPPORT_ERROR_MESSAGE, emailChangeStatus: "error" });
      return;
    }
    updatePersistence({
      emailChangeMessage: body.emailSent
        ? "Check your email to confirm the new address."
        : "Check your inbox for the confirmation link we sent recently.",
      emailChangeStatus: "sent",
    });
  }

  function clearEmailChangeFeedback(): void {
    updatePersistence({ emailChangeMessage: "", emailChangeStatus: "idle" });
  }

  async function stopEmailChange(): Promise<boolean> {
    if (!inSession()) return false;
    const response = await cancelEmailChange();
    if (!inSession()) return false;
    if (!response.ok) {
      updatePersistence({ emailChangeMessage: await responseDetail(response), emailChangeStatus: "error" });
      return false;
    }
    updatePersistence({ pendingEmailChange: null, emailChangeMessage: "", emailChangeStatus: "idle" });
    return true;
  }

  async function refreshEmailIdentity(): Promise<void> {
    if (!inSession()) return;
    const isCurrent = beginApplicationRead();
    const response = await fetchApplication().catch(() => null);
    if (!isCurrent()) return;
    if (response === null) {
      updatePersistence({ emailChangeMessage: APPLICANT_ACTION_ERROR_MESSAGE, emailChangeStatus: "error" });
      return;
    }
    if (response.status === 401) {
      updatePersistence({
        emailChangeMessage: "This session has ended. Continue in the tab where you confirmed the new address.",
        emailChangeStatus: "error",
      });
      return;
    }
    if (!response.ok) return;
    const body = (await response.json().catch(() => null)) as ApplicationResponse | null;
    if (!isCurrent()) return;
    if (body === null) {
      updatePersistence({ emailChangeMessage: APPLICANT_ACTION_ERROR_MESSAGE, emailChangeStatus: "error" });
      return;
    }
    updatePersistence((state) => {
      const emailChanged = state.primaryEmail !== null && body.primaryEmail !== state.primaryEmail;
      const stale = state.workingRevision !== null && body.workingRevision !== state.workingRevision;
      return {
        primaryEmail: body.primaryEmail,
        googleSignInLinked: body.googleSignInLinked,
        pendingEmailChange: body.pendingEmailChange,
        ...(emailChanged ? {
          emailChangeMessage: "",
          emailChangeStatus: "confirmed",
          googleDisconnectedByEmailChange: state.googleSignInLinked,
        } : {}),
        ...(stale ? {
          message: "This application changed in another tab or browser.", phase: "stale_copy",
        } : {
          workingRevision: body.workingRevision,
          savedAnswers: updateSnapshotEmail(state.savedAnswers, body.primaryEmail),
        }),
      };
    });
    setDraft((current) => ({
      ...current,
      applicant: { ...current.applicant, email: body.primaryEmail },
    }));
  }

  async function recoverEmailAction<Result>(operation: () => Promise<Result>, fallback: Result): Promise<Result> {
    try {
      return await operation();
    } catch {
      updatePersistence({ emailChangeMessage: APPLICANT_ACTION_ERROR_MESSAGE, emailChangeStatus: "error" });
      return fallback;
    }
  }

  return {
    beginEmailChange: (email: string) => recoverEmailAction(() => beginEmailChange(email), undefined),
    clearEmailChangeFeedback,
    stopEmailChange: () => recoverEmailAction(stopEmailChange, false),
    refreshEmailIdentity,
  };
}
