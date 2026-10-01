import { type Dispatch, type SetStateAction, useEffect, useReducer, useRef } from "react";

import { TECH_SUPPORT_ERROR_MESSAGE } from "../support";
import { retryForServiceRecovery } from "../serviceRecovery";
import { useRequestScope } from "../hooks/useRequestScope";
import {
  accessCredentialFromFragment,
  type ApplicationResponse,
  defaultOpeningIds,
  type EmailSendStatus,
  linkBody,
  type PendingCopy,
  responseProblem,
  validBrowserOpeningIds,
  workingSnapshot,
} from "./applicantPersistence";
import { createApplicantEmailFlow } from "./applicantEmailFlow";
import { createApplicantSaveFlow } from "./applicantSaveFlow";
import { createApplicantWithdrawalFlow } from "./applicantWithdrawalFlow";
import {
  type ApplicantPersistenceState,
  applicantPersistenceReducer,
  INITIAL_APPLICANT_PERSISTENCE_STATE,
} from "./applicantPersistenceState";
import {
  deletePendingDraft,
  fetchApplicantOpenings,
  fetchApplication,
  fetchPendingCopy,
  inspectAccessLink,
  openAccessLink,
  regenerateAccessLink,
  reconcilePendingCopy as reconcilePendingCopyRequest,
} from "./api";
import {
  clearApplicationDraft,
  hasAnswersBeyondEmail,
  loadApplicationDraft,
  remembersDevice,
} from "./draftStorage";
import { draftFromWorking } from "./applicationDraft";
import type { ApplicantDraft, ApplicantOpening } from "./types";

export function useApplicantPersistence(
  draft: ApplicantDraft,
  setDraft: Dispatch<SetStateAction<ApplicantDraft>>,
  onRememberDeviceChange: (remember: boolean) => void,
) {
  const draftRef = useRef(draft);
  const applicationReads = useRequestScope();
  const pendingCopyReads = useRequestScope();
  const linkStarted = useRef(false);
  const [persistence, dispatchPersistence] = useReducer(
    applicantPersistenceReducer,
    INITIAL_APPLICANT_PERSISTENCE_STATE,
  );
  const {
    phase,
    loadRecoveryStage,
    message,
    applicationId,
    workingRevision,
    openings,
    openingIds,
    canEdit,
    openingsLoaded,
    pendingDraftToken,
    accessToken,
    accessEmail,
    accessPurpose,
    accessApplicationEmail,
    linkConflict,
    pendingCopy,
    reviewAfterAccess,
    savedAnswers,
    primaryEmail,
    googleSignInLinked,
    googleDisconnectedByEmailChange,
    pendingEmailChange,
    emailChangeStatus,
    emailChangeMessage,
    collisionEmail,
    withdrawalStatus,
    withdrawalMessage,
  } = persistence;

  function setPersistence<Key extends keyof ApplicantPersistenceState>(
    key: Key,
    value:
      | ApplicantPersistenceState[Key]
      | ((current: ApplicantPersistenceState[Key]) => ApplicantPersistenceState[Key]),
  ): void {
    dispatchPersistence({ key, value } as Parameters<typeof dispatchPersistence>[0]);
  }

  const stateRef = useRef(persistence);
  stateRef.current = persistence;
  draftRef.current = draft;

  useEffect(() => {
    if (
      savedAnswers !== null &&
      savedAnswers !== workingSnapshot(draft, openingIds) &&
      (phase === "email_sent" || phase === "saved")
    ) {
      setPersistence("phase", "idle");
    }
  }, [draft, openingIds, phase, savedAnswers]);

  useEffect(() => {
    if (
      phase === "authentication_required" &&
      collisionEmail !== null &&
      draft.applicant.email.trim().toLowerCase() !== collisionEmail
    ) {
      setPersistence("collisionEmail", null);
      setPersistence("message", "");
      setPersistence("phase", "idle");
    }
  }, [collisionEmail, draft.applicant.email, phase]);

  useEffect(() => {
    if (linkStarted.current) return;
    linkStarted.current = true;
    const token = accessCredentialFromFragment();
    if (!token) {
      void restoreApplication();
      return;
    }
    setPersistence("accessToken", token);
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    void inspectLink(token);
    // Link inspection is intentionally one-shot. Depending on these render-local
    // workflow functions would repeat a single-use credential exchange.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const refreshWhenVisible = () => {
      if (document.visibilityState !== "visible") return;
      if (applicationId != null) void refreshLifecycleState();
      else if (openingsLoaded) void restorePublicOpenings(true);
    };
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => document.removeEventListener("visibilitychange", refreshWhenVisible);
    // The primitive lifecycle keys above own this subscription. The workflow
    // functions are render-local and would resubscribe on every state transition.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applicationId, openingsLoaded, workingRevision]);

  async function inspectLink(token: string): Promise<void> {
    setPersistence("phase", "working");
    const response = await inspectAccessLink(token);
    if (!response.ok) return fail(response);
    const body = await linkBody(response);
    setPersistence("accessPurpose", body.purpose ?? "applicant_access");
    setPersistence("accessApplicationEmail", body.applicationEmail);
    if (body.state === "unavailable") {
      setPersistence("phase", "applications_unavailable");
      return;
    }
    if (body.switchRequired && body.currentEmail && body.linkEmail) {
      setPersistence("linkConflict", {
        currentEmail: body.currentEmail,
        linkEmail: body.linkEmail,
        applicationEmail: body.applicationEmail,
        purpose: body.purpose ?? "applicant_access",
        linkIsValid: body.state === "valid",
      });
      setPersistence("phase", "link_conflict");
      return;
    }
    if (body.state === "valid" && body.linkEmail) {
      setPersistence("accessEmail", body.linkEmail);
      setPersistence("accessPurpose", body.purpose ?? "applicant_access");
      setPersistence("accessApplicationEmail", body.applicationEmail);
      setPersistence("phase", "link_ready");
      return;
    }
    if (
      body.purpose !== "email_change" &&
      (body.state === "expired" || body.state === "used" || body.state === "replaced") &&
      body.currentEmail === body.linkEmail
    ) {
      await restoreApplication();
      return;
    }
    setPersistence("phase", body.state === "invalid" || body.state === "abandoned" ? "link_invalid" : "link_expired");
  }

  async function openLink(
    token: string,
    switchCurrent: boolean,
    rememberDevice: boolean,
  ): Promise<void> {
    setPersistence("phase", "working");
    const response = await openAccessLink(token, switchCurrent, rememberDevice);
    if (!response.ok) return fail(response);
    const body = await linkBody(response);
    if (body.state === "email_in_use" && body.applicationId != null) {
      onRememberDeviceChange(rememberDevice);
      setPersistence("applicationId", body.applicationId);
      await restoreApplication(body.applicationId);
      setPersistence("emailChangeMessage", "That email address already has an application, so nothing was changed.");
      setPersistence("emailChangeStatus", "error");
      setPersistence("phase", "idle");
      return;
    }
    if (body.state !== "valid" || body.applicationId == null) {
      setPersistence("phase", body.state === "invalid" || body.state === "abandoned" ? "link_invalid" : "link_expired");
      return;
    }
    onRememberDeviceChange(rememberDevice);
    setPersistence("applicationId", body.applicationId);
    setPersistence("reviewAfterAccess", body.purpose !== "email_change" && body.pendingIntent === "submit");
    setPersistence("pendingCopy", body.pendingCopy);
    setPersistence("linkConflict", null);
    await restoreApplication(body.applicationId);
    if (body.purpose === "email_change") {
      setPersistence("pendingEmailChange", null);
      setPersistence("emailChangeMessage", "");
      setPersistence("emailChangeStatus", "confirmed");
      setPersistence("googleDisconnectedByEmailChange", body.googleDisconnected);
    }
  }

  async function restoreApplication(knownId?: number): Promise<void> {
    const isCurrent = applicationReads.begin();
    const response = await recoverInitialLoad(fetchApplication);
    if (response === null || !isCurrent()) return;
    if (response.status === 401) {
      if (knownId == null) {
        dispatchPersistence({ type: "session_ended", phase: "idle" });
        await restorePublicOpenings();
      } else {
        setPersistence("message", "Your application session has ended.");
        setPersistence("phase", "session_expired");
      }
      return;
    }
    if (!response.ok) return fail(response);
    const body = (await response.json()) as ApplicationResponse;
    if (!isCurrent()) return;
    const serverOpeningIds = defaultOpeningIds(body.openings);
    let restoredOpeningIds = serverOpeningIds;
    let snapshot: string | null = null;
    if (body.answers) {
      const stored = remembersDevice() ? loadApplicationDraft(body.applicationId) : null;
      const serverDraft = draftFromWorking(body.answers);
      const storedMatchesServer = stored?.baseRevision === body.workingRevision;
      const restored = storedMatchesServer && hasAnswersBeyondEmail(stored.draft)
        ? stored.draft
        : serverDraft;
      if (storedMatchesServer) {
        restoredOpeningIds = validBrowserOpeningIds(stored.openingIds, body.openings);
      }
      setDraft({ ...restored, applicant: { ...restored.applicant, email: body.primaryEmail } });
      snapshot = workingSnapshot(serverDraft, serverOpeningIds);
    }
    dispatchPersistence({ type: "application_restored", application: body,
      openingIds: restoredOpeningIds, snapshot });
    await restorePendingCopy();
  }

  async function restorePendingCopy(): Promise<void> {
    const isCurrent = pendingCopyReads.begin();
    const response = await fetchPendingCopy();
    if (!response.ok || !isCurrent()) return;
    const body = (await response.json()) as { pendingCopy: PendingCopy | null };
    if (!isCurrent()) return;
    setPersistence("pendingCopy", body.pendingCopy);
  }

  async function restorePublicOpenings(preserveSelection = false): Promise<void> {
    const response = await recoverInitialLoad(fetchApplicantOpenings);
    if (response === null) return;
    if (!response.ok) return fail(response);
    const body = (await response.json()) as {
      canStartApplication: boolean;
      openings: ApplicantOpening[];
    };
    setPersistence("openings", body.openings);
    setPersistence("openingIds", (current) => (
      preserveSelection
        ? validBrowserOpeningIds(current, body.openings)
        : defaultOpeningIds(body.openings)
    ));
    setPersistence("canEdit", body.canStartApplication);
    setPersistence("openingsLoaded", true);
  }

  async function recoverInitialLoad(
    request: () => Promise<Response>,
  ): Promise<Response | null> {
    if (openingsLoaded) return request();
    setPersistence("loadRecoveryStage", null);
    try {
      const response = await retryForServiceRecovery(async () => {
        const attempt = await request();
        if (attempt.status === 429 || attempt.status >= 500) {
          throw new Error(`Application service unavailable (${attempt.status}).`);
        }
        return attempt;
      }, (stage) => setPersistence("loadRecoveryStage", stage));
      setPersistence("loadRecoveryStage", null);
      return response;
    } catch {
      setPersistence("loadRecoveryStage", "failed");
      setPersistence("message", TECH_SUPPORT_ERROR_MESSAGE);
      setPersistence("phase", "load_error");
      return null;
    }
  }

  async function reconcilePendingCopy(choice: "saved" | "guest"): Promise<void> {
    setPersistence("phase", "working");
    const response = await reconcilePendingCopyRequest(choice);
    if (!response.ok) {
      const problem = await responseProblem(response);
      if (problem.code === "pending_copy_not_found") {
        setPersistence("pendingCopy", null);
        setPersistence("phase", "idle");
        await restoreApplication(applicationId ?? undefined);
        return;
      }
      setPersistence("message", problem.detail);
      setPersistence("phase", "error");
      return;
    }
    setPersistence("pendingCopy", null);
    await restoreApplication(applicationId ?? undefined);
  }

  function clearActionFeedback(): void {
    setPersistence("message", "");
    setPersistence("phase", (current) => (
      current === "saved"
      || current === "email_sent"
      || current === "email_failed"
      || current === "error"
        ? "idle"
        : current
    ));
  }

  function returnToApplication(): void {
    setPersistence("message", "");
    setPersistence("phase", "idle");
  }

  async function openLinkedApplication(rememberDevice: boolean): Promise<void> {
    if (accessToken) await openLink(accessToken, true, rememberDevice);
  }

  async function openReadyApplication(rememberDevice: boolean): Promise<void> {
    if (accessToken) await openLink(accessToken, false, rememberDevice);
  }

  async function keepCurrentApplication(): Promise<void> {
    setPersistence("linkConflict", null);
    setPersistence("accessToken", null);
    await restoreApplication();
  }

  async function emailNewAccessLink(): Promise<void> {
    if (!accessToken) return;
    setPersistence("phase", "working");
    const response = await regenerateAccessLink(accessToken);
    if (!response.ok) return fail(response);
    const body = (await response.json()) as {
      targetAvailable: boolean;
      emailSent: boolean;
      emailStatus: EmailSendStatus;
    };
    if (!body.targetAvailable) {
      setPersistence("linkConflict", null);
      setPersistence("phase", "link_invalid");
      return;
    }
    if (body.emailStatus === "failed") {
      setPersistence("message", TECH_SUPPORT_ERROR_MESSAGE);
      setPersistence("phase", "error");
      return;
    }
    setPersistence("message",
      body.emailSent
        ? accessPurpose === "email_change"
          ? "We emailed a new confirmation link. Open it to finish changing your email address."
          : "We emailed a new link to open your application."
        : accessPurpose === "email_change"
          ? "Check your inbox for the confirmation link we sent recently."
          : "Check your inbox for the application link we sent recently.",
    );
    setPersistence("linkConflict", null);
    setPersistence("phase", "access_link_sent");
  }

  async function discardDraft(): Promise<void> {
    if (pendingDraftToken) await deletePendingDraft(pendingDraftToken);
    if (applicationId != null) clearApplicationDraft(applicationId);
    setPersistence("pendingDraftToken", null);
    setPersistence("openingIds", defaultOpeningIds(openings));
    setPersistence("savedAnswers", null);
    setPersistence("phase", "idle");
  }

  async function fail(response: Response): Promise<void> {
    const problem = await responseProblem(response);
    if (["applications_closed", "opening_archived", "opening_selection_required"].includes(
      problem.code ?? "",
    )) {
      if (applicationId != null) {
        if (!(await refreshLifecycleState())) return;
      } else await restorePublicOpenings(true);
    }
    dispatchPersistence({ type: "action_failed", message: problem.detail,
      phase: problem.code === "stale_application" ? "stale_copy" : "error" });
  }

  async function refreshLifecycleState(): Promise<boolean> {
    const isCurrent = applicationReads.begin();
    const response = await fetchApplication();
    if (!isCurrent()) return false;
    if (response.status === 401) {
      setPersistence("message", "Your application session has ended.");
      setPersistence("phase", "session_expired");
      return false;
    }
    if (!response.ok) return false;
    const body = (await response.json()) as ApplicationResponse;
    if (!isCurrent()) return false;
    const currentRevision = stateRef.current.workingRevision;
    dispatchPersistence({ type: "lifecycle_refreshed", application: body });
    return currentRevision === null || body.workingRevision === currentRevision;
  }

  function invalidateApplicationReads(): void {
    applicationReads.invalidate();
    pendingCopyReads.invalidate();
  }

  const saveFlow = createApplicantSaveFlow({
    state: persistence,
    getCurrentState: () => stateRef.current,
    draftRef,
    dispatch: dispatchPersistence,
    invalidateReads: invalidateApplicationReads,
    setPersistence,
    fail,
  });
  const emailFlow = createApplicantEmailFlow({
    setPersistence,
    setDraft,
    primaryEmail,
    workingRevision,
    googleSignInLinked,
  });
  const withdrawalFlow = createApplicantWithdrawalFlow({
    dispatch: dispatchPersistence,
    invalidateReads: invalidateApplicationReads,
    setPersistence,
    fail,
    restorePublicOpenings,
  });

  return {
    phase,
    loadRecoveryStage,
    message,
    linkConflict,
    pendingCopy,
    accessEmail,
    accessPurpose,
    accessApplicationEmail,
    reviewAfterAccess,
    clearReviewAfterAccess: () => setPersistence("reviewAfterAccess", false),
    clearActionFeedback,
    returnToApplication,
    reconcilePendingCopy,
    openLinkedApplication,
    openReadyApplication,
    keepCurrentApplication,
    emailNewAccessLink,
    ...saveFlow,
    ...emailFlow,
    discardDraft,
    ...withdrawalFlow,
    reloadLatestApplication: () => restoreApplication(applicationId ?? undefined),
    openings,
    openingIds,
    canEdit,
    openingsLoaded,
    setOpeningSelected: (openingId: number, selected: boolean) => {
      setPersistence("openingIds", (current) => (
        selected
          ? [...new Set([...current, openingId])]
          : current.filter((id) => id !== openingId)
      ));
    },
    authenticated: applicationId != null,
    applicationId,
    primaryEmail,
    googleSignInLinked,
    googleDisconnectedByEmailChange,
    pendingEmailChange,
    emailChangeStatus,
    emailChangeMessage,
    hasUnsavedChanges: savedAnswers !== workingSnapshot(draft, openingIds),
    withdrawalStatus,
    withdrawalMessage,
    workingRevision,
    busy: phase === "working",
  };
}
