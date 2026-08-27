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
  requestApplicantReauthentication,
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
      setPersistence(
        "emailChangeNeedsReauthentication",
        problem.code === "recent_authentication_required",
      );
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
    setPersistence("emailChangeNeedsReauthentication", false);
    setPersistence("emailChangeStatus", "sent");
  }

  function clearEmailChangeFeedback(): void {
    setPersistence("emailChangeMessage", "");
    setPersistence("emailChangeNeedsReauthentication", false);
    setPersistence("emailChangeStatus", "idle");
  }

  async function emailReauthenticationLink(): Promise<void> {
    const response = await requestApplicantReauthentication();
    if (!response.ok) {
      setPersistence("emailChangeMessage", await responseDetail(response));
      return;
    }
    const body = (await response.json()) as {
      emailSent: boolean;
      emailStatus: EmailSendStatus;
    };
    setPersistence(
      "emailChangeMessage",
      body.emailSent
        ? `Check ${primaryEmail ?? "your email"} for a new sign-in link.`
        : body.emailStatus === "failed"
          ? TECH_SUPPORT_ERROR_MESSAGE
          : "Check your inbox for the sign-in link we sent recently.",
    );
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
    setPersistence("emailChangeNeedsReauthentication", false);
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
      setPersistence("emailChangeNeedsReauthentication", false);
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
    emailReauthenticationLink,
    stopEmailChange,
    refreshEmailIdentity,
  };
}
