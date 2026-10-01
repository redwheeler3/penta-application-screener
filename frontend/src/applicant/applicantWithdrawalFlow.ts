import type { Dispatch } from "react";

import { responseProblem } from "./applicantPersistence";
import type {
  ApplicantPersistenceAction,
  SetApplicantPersistence,
} from "./applicantPersistenceState";
import { logoutApplicant, withdrawApplication } from "./api";
import { clearApplicantStorage } from "./draftStorage";

type WithdrawalFlowDependencies = {
  setPersistence: SetApplicantPersistence;
  dispatch: Dispatch<ApplicantPersistenceAction>;
  invalidateReads: () => void;
  fail: (response: Response) => Promise<void>;
  restorePublicOpenings: () => Promise<void>;
};

export function createApplicantWithdrawalFlow({
  setPersistence,
  dispatch,
  invalidateReads,
  fail,
  restorePublicOpenings,
}: WithdrawalFlowDependencies) {
  async function withdraw(): Promise<boolean> {
    invalidateReads();
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
    dispatch({ type: "session_ended", phase: "withdrawn" });
    return true;
  }

  function clearWithdrawalFeedback(): void {
    setPersistence("withdrawalStatus", "idle");
    setPersistence("withdrawalMessage", "");
  }

  async function signOut(): Promise<boolean> {
    invalidateReads();
    const response = await logoutApplicant();
    if (!response.ok) {
      await fail(response);
      return false;
    }
    clearApplicantStorage();
    dispatch({ type: "session_ended", phase: "idle" });
    await restorePublicOpenings();
    return true;
  }

  return {
    withdrawApplication: withdraw,
    clearWithdrawalFeedback,
    signOut,
  };
}
