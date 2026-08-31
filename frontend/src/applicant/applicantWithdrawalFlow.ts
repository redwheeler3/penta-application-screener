import { responseProblem } from "./applicantPersistence";
import type { SetApplicantPersistence } from "./applicantPersistenceState";
import { logoutApplicant, withdrawApplication } from "./api";
import { clearApplicantStorage } from "./draftStorage";

type WithdrawalFlowDependencies = {
  setPersistence: SetApplicantPersistence;
  fail: (response: Response) => Promise<void>;
  restorePublicOpenings: () => Promise<void>;
};

export function createApplicantWithdrawalFlow({
  setPersistence,
  fail,
  restorePublicOpenings,
}: WithdrawalFlowDependencies) {
  async function withdraw(): Promise<boolean> {
    setPersistence("withdrawalStatus", "working");
    setPersistence("withdrawalMessage", "");
    const response = await withdrawApplication();
    if (!response.ok) {
      const problem = await responseProblem(response);
      if (problem.code === "unauthorized") {
        setPersistence("message", "Your application session has ended.");
        setPersistence("phase", "session_expired");
        setPersistence("withdrawalStatus", "idle");
        return false;
      }
      setPersistence("withdrawalStatus", "error");
      setPersistence("withdrawalMessage", problem.detail);
      return false;
    }
    clearApplicantStorage();
    setPersistence("applicationId", null);
    setPersistence("workingRevision", null);
    setPersistence("primaryEmail", null);
    setPersistence("googleSignInLinked", false);
    setPersistence("googleDisconnectedByEmailChange", false);
    setPersistence("pendingEmailChange", null);
    setPersistence("withdrawalStatus", "idle");
    setPersistence("phase", "withdrawn");
    return true;
  }

  function clearWithdrawalFeedback(): void {
    setPersistence("withdrawalStatus", "idle");
    setPersistence("withdrawalMessage", "");
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
    setPersistence("primaryEmail", null);
    setPersistence("googleSignInLinked", false);
    setPersistence("googleDisconnectedByEmailChange", false);
    setPersistence("pendingEmailChange", null);
    setPersistence("emailChangeStatus", "idle");
    setPersistence("phase", "idle");
    await restorePublicOpenings();
    return true;
  }

  return {
    withdrawApplication: withdraw,
    clearWithdrawalFeedback,
    signOut,
  };
}
