import { responseProblem } from "./applicantPersistence";
import {
  resetApplicantSession,
  type UpdateApplicantPersistence,
} from "./applicantPersistenceState";
import { logoutApplicant, withdrawApplication } from "./api";
import { clearApplicantStorage } from "./draftStorage";

type WithdrawalFlowDependencies = {
  updatePersistence: UpdateApplicantPersistence;
  invalidateReads: () => void;
  fail: (response: Response) => Promise<void>;
  restorePublicOpenings: () => Promise<void>;
};

export function createApplicantWithdrawalFlow({
  updatePersistence,
  invalidateReads,
  fail,
  restorePublicOpenings,
}: WithdrawalFlowDependencies) {
  async function withdraw(): Promise<boolean> {
    invalidateReads();
    updatePersistence({ withdrawalStatus: "working", withdrawalMessage: "" });
    const response = await withdrawApplication();
    if (!response.ok) {
      const problem = await responseProblem(response);
      if (problem.code === "unauthorized") {
        updatePersistence({
          message: "Your application session has ended.",
          phase: "session_expired",
          withdrawalStatus: "idle",
        });
        return false;
      }
      updatePersistence({ withdrawalStatus: "error", withdrawalMessage: problem.detail });
      return false;
    }
    clearApplicantStorage();
    updatePersistence((state) => resetApplicantSession(state, "withdrawn"));
    return true;
  }

  function clearWithdrawalFeedback(): void {
    updatePersistence({ withdrawalStatus: "idle", withdrawalMessage: "" });
  }

  async function signOut(): Promise<boolean> {
    invalidateReads();
    const response = await logoutApplicant();
    if (!response.ok) {
      await fail(response);
      return false;
    }
    clearApplicantStorage();
    updatePersistence((state) => resetApplicantSession(state));
    await restorePublicOpenings();
    return true;
  }

  return {
    withdrawApplication: withdraw,
    clearWithdrawalFeedback,
    signOut,
  };
}
