import { APPLICANT_ACTION_ERROR_MESSAGE, responseProblem } from "./applicantPersistence";
import {
  resetApplicantSession,
  type UpdateApplicantPersistence,
} from "./applicantPersistenceState";
import type * as applicantApi from "./api";
import { BROWSER_STORAGE_CLEAR_MESSAGE, captureApplicantStorage, clearApplicantStorage } from "./draftStorage";
import type { RequestIsCurrent } from "../hooks/useRequestScope";

type WithdrawalFlowDependencies = {
  api: ReturnType<typeof applicantApi.createApi>;
  updatePersistence: UpdateApplicantPersistence;
  endSessionWork: () => void;
  captureSession: () => RequestIsCurrent;
  fail: (response: Response) => Promise<void>;
  restorePublicOpenings: () => Promise<void>;
};

export function createApplicantWithdrawalFlow({
  api,
  updatePersistence,
  endSessionWork,
  captureSession,
  fail,
  restorePublicOpenings,
}: WithdrawalFlowDependencies) {
  const { logoutApplicant, withdrawApplication } = api;
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
    const cleared = await clearApplicantStorage(browserSnapshot);
    if (!inSession()) return false;
    endSessionWork();
    updatePersistence((state) => ({ ...resetApplicantSession(state, "withdrawn"),
      browserStorageMessage: cleared ? "" : BROWSER_STORAGE_CLEAR_MESSAGE }));
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
    const cleared = await clearApplicantStorage(browserSnapshot);
    if (!inSession()) return false;
    endSessionWork();
    updatePersistence((state) => ({ ...resetApplicantSession(state),
      browserStorageMessage: cleared ? "" : BROWSER_STORAGE_CLEAR_MESSAGE }));
    void restorePublicOpenings();
    return true;
  }

  return {
    withdrawApplication: withdraw,
    clearWithdrawalFeedback,
    signOut,
  };
}
