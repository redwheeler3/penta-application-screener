import type { Dispatch, SetStateAction } from "react";

import { TECH_SUPPORT_ERROR_MESSAGE } from "../support";
import {
  type ApplicationResponse,
  type EmailSendStatus,
  responseDetail,
  responseProblem,
  updateSnapshotEmail,
} from "./applicantPersistence";
import type { UpdateApplicantPersistence } from "./applicantPersistenceState";
import {
  cancelEmailChange,
  fetchApplication,
  requestEmailChange,
} from "./api";
import type { ApplicantDraft } from "./types";

type EmailFlowDependencies = {
  updatePersistence: UpdateApplicantPersistence;
  setDraft: Dispatch<SetStateAction<ApplicantDraft>>;
};

export function createApplicantEmailFlow({
  updatePersistence,
  setDraft,
}: EmailFlowDependencies) {
  async function beginEmailChange(newEmail: string): Promise<void> {
    updatePersistence({
      emailChangeStatus: "sending",
      emailChangeMessage: "",
      googleDisconnectedByEmailChange: false,
    });
    const response = await requestEmailChange(newEmail);
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
    const response = await cancelEmailChange();
    if (!response.ok) {
      updatePersistence({ emailChangeMessage: await responseDetail(response), emailChangeStatus: "error" });
      return false;
    }
    updatePersistence({ pendingEmailChange: null, emailChangeMessage: "", emailChangeStatus: "idle" });
    return true;
  }

  async function refreshEmailIdentity(): Promise<void> {
    const response = await fetchApplication();
    if (response.status === 401) {
      updatePersistence({
        emailChangeMessage: "This session has ended. Continue in the tab where you confirmed the new address.",
        emailChangeStatus: "error",
      });
      return;
    }
    if (!response.ok) return;
    const body = (await response.json()) as ApplicationResponse;
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

  return {
    beginEmailChange,
    clearEmailChangeFeedback,
    stopEmailChange,
    refreshEmailIdentity,
  };
}
