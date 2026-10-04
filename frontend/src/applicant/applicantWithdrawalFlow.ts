import { APPLICANT_ACTION_ERROR_MESSAGE, responseProblem } from "./applicantPersistence";
import {
  resetApplicantSession,
  type UpdateApplicantPersistence,
} from "./applicantPersistenceState";
import { logoutApplicant, withdrawApplication } from "./api";
import { captureApplicantStorage, clearApplicantStorage } from "./draftStorage";
import type { RequestIsCurrent } from "../hooks/useRequestScope";

type WithdrawalFlowDependencies = {
  updatePersistence: UpdateApplicantPersistence;
  endSessionWork: () => void;
  captureSession: () => RequestIsCurrent;
  fail: (response: Response) => Promise<void>;
  restorePublicOpenings: () => Promise<void>;
};

export function createApplicantWithdrawalFlow({
  updatePersistence,
  endSessionWork,
  captureSession,
  fail,
  restorePublicOpenings,
}: WithdrawalFlowDependencies) {
  async function withdraw(): Promise<boolean> {
    const browserSnapshot = captureApplicantStorage();
    endSessionWork();
    const inSession = captureSession();
    updatePersistence({ withdrawalStatus: "working", withdrawalMessage: "" });
    const response = await withdrawApplication().catch(() => null);
    if (!inSession()) return false;
    if (response === null) {
      updatePersistence({ phase: "idle", withdrawalStatus: "error", withdrawalMessage: APPLICANT_ACTION_ERROR_MESSAGE });
      return false;
    }
    if (!response.ok) {
      const problem = await responseProblem(response);
      if (!inSession()) return false;
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
    await clearApplicantStorage(browserSnapshot);
    if (!inSession()) return false;
    endSessionWork();
    updatePersistence((state) => resetApplicantSession(state, "withdrawn"));
    return true;
  }

  function clearWithdrawalFeedback(): void {
    updatePersistence({ withdrawalStatus: "idle", withdrawalMessage: "" });
  }

  async function signOut(): Promise<boolean> {
    const browserSnapshot = captureApplicantStorage();
    endSessionWork();
    const inSession = captureSession();
    const response = await logoutApplicant().catch(() => null);
    if (!inSession()) return false;
    if (response === null) {
      updatePersistence({ message: APPLICANT_ACTION_ERROR_MESSAGE, phase: "error" });
      return false;
    }
    if (!response.ok) {
      await fail(response);
      return false;
    }
    await clearApplicantStorage(browserSnapshot);
    if (!inSession()) return false;
    endSessionWork();
    updatePersistence((state) => resetApplicantSession(state));
    void restorePublicOpenings();
    return true;
  }

  return {
    withdrawApplication: withdraw,
    clearWithdrawalFeedback,
    signOut,
  };
}
