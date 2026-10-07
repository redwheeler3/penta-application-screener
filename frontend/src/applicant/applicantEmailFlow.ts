import type { RequestIsCurrent } from "../hooks/useRequestScope";

import { TECH_SUPPORT_ERROR_MESSAGE } from "../support";
import {
  APPLICANT_ACTION_ERROR_MESSAGE,
  type EmailSendStatus,
  responseDetail,
  responseProblem,
} from "./applicantPersistence";
import type { UpdateApplicantPersistence } from "./applicantPersistenceState";
import type * as applicantApi from "./api";

type EmailFlowDependencies = {
  api: ReturnType<typeof applicantApi.createApi>;
  runMutation: <Result>(operation: () => Promise<Result>, fallback: Result) => Promise<Result>;
  captureSession: () => RequestIsCurrent;
  updatePersistence: UpdateApplicantPersistence;
};

export function createApplicantEmailFlow({
  api,
  runMutation,
  captureSession,
  updatePersistence: dispatch,
}: EmailFlowDependencies) {
  const { cancelEmailChange, requestEmailChange } = api;
  const inSession = captureSession();
  const updatePersistence: UpdateApplicantPersistence = (patch) => {
    if (inSession()) dispatch(patch);
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
    updatePersistence({ emailChangeStatus: "sending" });
    const response = await cancelEmailChange();
    if (!inSession()) return false;
    if (!response.ok) {
      updatePersistence({ emailChangeMessage: await responseDetail(response), emailChangeStatus: "error" });
      return false;
    }
    updatePersistence({ pendingEmailChange: null, emailChangeMessage: "", emailChangeStatus: "idle" });
    return true;
  }

  function recoverEmailAction<Result>(operation: () => Promise<Result>, fallback: Result): Promise<Result> {
    return runMutation(async () => {
      try {
        return await operation();
      } catch {
        updatePersistence({ emailChangeMessage: APPLICANT_ACTION_ERROR_MESSAGE, emailChangeStatus: "error" });
        return fallback;
      }
    }, fallback);
  }

  return {
    beginEmailChange: (email: string) => recoverEmailAction(() => beginEmailChange(email), undefined),
    clearEmailChangeFeedback,
    stopEmailChange: () => recoverEmailAction(stopEmailChange, false),
  };
}
