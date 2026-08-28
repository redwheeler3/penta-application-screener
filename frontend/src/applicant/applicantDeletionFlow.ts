import { responseProblem } from "./applicantPersistence";
import type { SetApplicantPersistence } from "./applicantPersistenceState";
import {
  deleteApplication as deleteApplicationRequest,
  logoutApplicant,
} from "./api";
import { clearApplicantStorage } from "./draftStorage";

type DeletionFlowDependencies = {
  setPersistence: SetApplicantPersistence;
  fail: (response: Response) => Promise<void>;
  restorePublicOpenings: () => Promise<void>;
};

export function createApplicantDeletionFlow({
  setPersistence,
  fail,
  restorePublicOpenings,
}: DeletionFlowDependencies) {
  async function removeApplication(): Promise<boolean> {
    setPersistence("deletionStatus", "working");
    setPersistence("deletionMessage", "");
    const response = await deleteApplicationRequest();
    if (!response.ok) {
      const problem = await responseProblem(response);
      if (problem.code === "unauthorized") {
        setPersistence("message", "Your application session has ended.");
        setPersistence("phase", "session_expired");
        setPersistence("deletionStatus", "idle");
        return false;
      }
      setPersistence("deletionStatus", "error");
      setPersistence("deletionMessage", problem.detail);
      return false;
    }
    const body = (await response.json()) as { emailSent: boolean };
    setPersistence("deletionEmailSent", body.emailSent);
    clearApplicantStorage();
    setPersistence("applicationId", null);
    setPersistence("workingRevision", null);
    setPersistence("submitted", false);
    setPersistence("serverHasUnsubmittedChanges", false);
    setPersistence("primaryEmail", null);
    setPersistence("pendingEmailChange", null);
    setPersistence("deletionStatus", "idle");
    setPersistence("phase", "deleted");
    return true;
  }

  function clearDeletionFeedback(): void {
    setPersistence("deletionStatus", "idle");
    setPersistence("deletionMessage", "");
  }

  async function signOut(): Promise<boolean> {
    const response = await logoutApplicant();
    if (!response.ok) {
      await fail(response);
      return false;
    }
    clearApplicantStorage();
    setPersistence("applicationId", null);
    setPersistence("workingRevision", null);
    setPersistence("submitted", false);
    setPersistence("serverHasUnsubmittedChanges", false);
    setPersistence("primaryEmail", null);
    setPersistence("pendingEmailChange", null);
    setPersistence("emailChangeStatus", "idle");
    setPersistence("phase", "idle");
    await restorePublicOpenings();
    return true;
  }

  return {
    removeApplication,
    clearDeletionFeedback,
    signOut,
  };
}
