import type { Dispatch, SetStateAction } from "react";

import { TECH_SUPPORT_ERROR_MESSAGE } from "../support";
import {
  type ApplicationResponse,
  type EmailSendStatus,
  responseDetail,
  responseProblem,
  updateSnapshotEmail,
} from "./applicantPersistence";
import type { SetApplicantPersistence } from "./applicantPersistenceState";
import {
  cancelEmailChange,
  fetchApplication,
  requestEmailChange,
} from "./api";
import type { ApplicantDraft } from "./types";

type EmailFlowDependencies = {
  setPersistence: SetApplicantPersistence;
  setDraft: Dispatch<SetStateAction<ApplicantDraft>>;
  primaryEmail: string | null;
  workingRevision: number | null;
};

export function createApplicantEmailFlow({
  setPersistence,
  setDraft,
  primaryEmail,
  workingRevision,
}: EmailFlowDependencies) {
  async function beginEmailChange(newEmail: string): Promise<void> {
    setPersistence("emailChangeStatus", "sending");
    setPersistence("emailChangeMessage", "");
    const response = await requestEmailChange(newEmail);
    if (!response.ok) {
      const problem = await responseProblem(response);
      setPersistence("emailChangeMessage", problem.detail);
      setPersistence("emailChangeStatus", "error");
      return;
    }
    const body = (await response.json()) as {
      emailSent: boolean;
      emailStatus: EmailSendStatus;
      pendingEmail: string | null;
    };
    setPersistence("pendingEmailChange", body.pendingEmail);
    if (body.pendingEmail === null) {
      setPersistence("emailChangeMessage", TECH_SUPPORT_ERROR_MESSAGE);
      setPersistence("emailChangeStatus", "error");
      return;
    }
    setPersistence(
      "emailChangeMessage",
      body.emailSent
        ? "Check your email to confirm the new address."
        : "Check your inbox for the confirmation link we sent recently.",
    );
    setPersistence("emailChangeStatus", "sent");
  }

  function clearEmailChangeFeedback(): void {
    setPersistence("emailChangeMessage", "");
    setPersistence("emailChangeStatus", "idle");
  }

  async function stopEmailChange(): Promise<boolean> {
    const response = await cancelEmailChange();
    if (!response.ok) {
      setPersistence("emailChangeMessage", await responseDetail(response));
      setPersistence("emailChangeStatus", "error");
      return false;
    }
    setPersistence("pendingEmailChange", null);
    setPersistence("emailChangeMessage", "");
    setPersistence("emailChangeStatus", "idle");
    return true;
  }

  async function refreshEmailIdentity(): Promise<void> {
    const response = await fetchApplication();
    if (response.status === 401) {
      setPersistence(
        "emailChangeMessage",
        "This session has ended. Continue in the tab where you confirmed the new address.",
      );
      setPersistence("emailChangeStatus", "error");
      return;
    }
    if (!response.ok) return;
    const body = (await response.json()) as ApplicationResponse;
    const emailChanged = primaryEmail !== null && body.primaryEmail !== primaryEmail;
    setPersistence("primaryEmail", body.primaryEmail);
    setPersistence("submitted", body.submitted);
    setPersistence("serverHasUnsubmittedChanges", body.hasUnsubmittedChanges);
    setPersistence("pendingEmailChange", body.pendingEmailChange);
    setDraft((current) => ({
      ...current,
      applicant: { ...current.applicant, email: body.primaryEmail },
    }));
    if (emailChanged) {
      setPersistence("emailChangeMessage", "");
      setPersistence("emailChangeStatus", "confirmed");
    }
    if (workingRevision !== null && body.workingRevision !== workingRevision) {
      setPersistence("message", "This application changed in another tab or browser.");
      setPersistence("phase", "stale_copy");
      return;
    }
    setPersistence("workingRevision", body.workingRevision);
    setPersistence("savedAnswers", (snapshot) => updateSnapshotEmail(snapshot, body.primaryEmail));
  }

  return {
    beginEmailChange,
    clearEmailChangeFeedback,
    stopEmailChange,
    refreshEmailIdentity,
  };
}
