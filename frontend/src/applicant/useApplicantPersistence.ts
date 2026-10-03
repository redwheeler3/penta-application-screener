import { type Dispatch, type SetStateAction, useEffect, useReducer, useRef } from "react";

import { TECH_SUPPORT_ERROR_MESSAGE } from "../support";
import { retryForServiceRecovery } from "../serviceRecovery";
import { useRequestScope, type RequestIsCurrent } from "../hooks/useRequestScope";
import {
  accessCredentialFromFragment,
  APPLICANT_ACTION_ERROR_MESSAGE,
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
  applicantPersistenceReducer,
  INITIAL_APPLICANT_PERSISTENCE_STATE,
  resetApplicantSession,
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
  const sessionWork = useRequestScope();
  const linkStarted = useRef(false);
  const [persistence, updatePersistence] = useReducer(
    applicantPersistenceReducer,
    INITIAL_APPLICANT_PERSISTENCE_STATE,
  resetApplicantSession,
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

  const stateRef = useRef(persistence);
  stateRef.current = persistence;
  draftRef.current = draft;

  useEffect(() => {
    if (
      savedAnswers !== null &&
      savedAnswers !== workingSnapshot(draft, openingIds) &&
      (phase === "email_sent" || phase === "saved")
    ) {
      updatePersistence({ phase: "idle" });
    }
  }, [draft, openingIds, phase, savedAnswers]);

  useEffect(() => {
    if (
      phase === "authentication_required" &&
      collisionEmail !== null &&
      draft.applicant.email.trim().toLowerCase() !== collisionEmail
    ) {
      updatePersistence({ collisionEmail: null, message: "", phase: "idle" });
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
    updatePersistence({ accessToken: token });
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
    const inSession = sessionWork.capture();
    try {
      updatePersistence({ phase: "working" });
      const response = await inspectAccessLink(token);
      if (!inSession()) return;
      if (!response.ok) return fail(response);
      const body = await linkBody(response);
      if (!inSession()) return;
      updatePersistence({
        accessPurpose: body.purpose ?? "applicant_access",
        accessApplicationEmail: body.applicationEmail,
      });
      if (body.state === "unavailable") {
        updatePersistence({ phase: "applications_unavailable" });
        return;
      }
      if (body.switchRequired && body.currentEmail && body.linkEmail) {
        updatePersistence({
          linkConflict: {
            currentEmail: body.currentEmail,
            linkEmail: body.linkEmail,
            applicationEmail: body.applicationEmail,
            purpose: body.purpose ?? "applicant_access",
            linkIsValid: body.state === "valid",
          },
          phase: "link_conflict",
        });
        return;
      }
      if (body.state === "valid" && body.linkEmail) {
        updatePersistence({ accessEmail: body.linkEmail, phase: "link_ready" });
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
      updatePersistence({ phase: body.state === "invalid" || body.state === "abandoned" ? "link_invalid" : "link_expired" });
    } catch {
      if (inSession()) updatePersistence({ message: APPLICANT_ACTION_ERROR_MESSAGE, phase: "error" });
    }
  }

  async function openLink(
    token: string,
    switchCurrent: boolean,
    rememberDevice: boolean,
  ): Promise<void> {
    endSessionWork();
    const inSession = sessionWork.capture();
    try {
      updatePersistence({ phase: "working" });
      const response = await openAccessLink(token, switchCurrent, rememberDevice);
      if (!inSession()) return;
      if (!response.ok) return fail(response);
      const body = await linkBody(response);
      if (!inSession()) return;
      if (body.state === "email_in_use" && body.applicationId != null) {
        onRememberDeviceChange(rememberDevice);
        updatePersistence({ applicationId: body.applicationId });
        await restoreApplication(body.applicationId);
        if (!inSession()) return;
        updatePersistence({
          emailChangeMessage: "That email address already has an application, so nothing was changed.",
          emailChangeStatus: "error",
          phase: "idle",
        });
        return;
      }
      if (body.state !== "valid" || body.applicationId == null) {
        updatePersistence({ phase: body.state === "invalid" || body.state === "abandoned" ? "link_invalid" : "link_expired" });
        return;
      }
      onRememberDeviceChange(rememberDevice);
      updatePersistence({
        applicationId: body.applicationId,
        reviewAfterAccess: body.purpose !== "email_change" && body.pendingIntent === "submit",
        pendingCopy: body.pendingCopy,
        linkConflict: null,
      });
      await restoreApplication(body.applicationId);
      if (!inSession()) return;
      if (body.purpose === "email_change") {
        updatePersistence({
          pendingEmailChange: null,
          emailChangeMessage: "",
          emailChangeStatus: "confirmed",
          googleDisconnectedByEmailChange: body.googleDisconnected,
        });
      }
    } catch {
      if (inSession()) updatePersistence({ message: APPLICANT_ACTION_ERROR_MESSAGE, phase: "error" });
    }
  }

  async function restoreApplication(knownId?: number): Promise<void> {
    const isCurrent = applicationReads.begin();
    const response = await recoverInitialLoad(fetchApplication, isCurrent);
    if (response === null || !isCurrent()) return;
    if (response.status === 401) {
      if (knownId == null) {
        updatePersistence((state) => resetApplicantSession(state));
        await restorePublicOpenings();
      } else {
        updatePersistence({ message: "Your application session has ended.", phase: "session_expired" });
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
    updatePersistence({
      applicationId: body.applicationId,
      workingRevision: body.workingRevision,
      primaryEmail: body.primaryEmail,
      googleSignInLinked: body.googleSignInLinked,
      pendingEmailChange: body.pendingEmailChange,
      openings: body.openings,
      canEdit: body.canEdit,
      openingsLoaded: true,
      openingIds: restoredOpeningIds,
      savedAnswers: snapshot,
      phase: "idle",
    });
    await restorePendingCopy();
  }

  async function restorePendingCopy(): Promise<void> {
    const isCurrent = pendingCopyReads.begin();
    const response = await fetchPendingCopy().catch(() => null);
    if (!isCurrent()) return;
    if (response === null) {
      updatePersistence({ message: APPLICANT_ACTION_ERROR_MESSAGE, phase: "error" });
      return;
    }
    if (!response.ok) return;
    const body = (await response.json().catch(() => null)) as { pendingCopy: PendingCopy | null } | null;
    if (!isCurrent()) return;
    if (body === null) {
      updatePersistence({ message: APPLICANT_ACTION_ERROR_MESSAGE, phase: "error" });
      return;
    }
    updatePersistence({ pendingCopy: body.pendingCopy });
  }

  async function restorePublicOpenings(preserveSelection = false): Promise<void> {
    const isCurrent = applicationReads.begin();
    const response = await recoverInitialLoad(fetchApplicantOpenings, isCurrent);
    if (response === null || !isCurrent()) return;
    if (!response.ok) return fail(response);
    const body = (await response.json()) as {
      canStartApplication: boolean;
      openings: ApplicantOpening[];
    };
    if (!isCurrent()) return;
    updatePersistence((state) => ({
      openings: body.openings,
      openingIds: preserveSelection
        ? validBrowserOpeningIds(state.openingIds, body.openings)
        : defaultOpeningIds(body.openings),
      canEdit: body.canStartApplication,
      openingsLoaded: true,
    }));
  }

  async function recoverInitialLoad(
    request: () => Promise<Response>,
    isCurrent: RequestIsCurrent,
  ): Promise<Response | null> {
    if (stateRef.current.openingsLoaded) {
      try {
        return await request();
      } catch {
        if (isCurrent()) updatePersistence({ message: TECH_SUPPORT_ERROR_MESSAGE, phase: "error" });
        return null;
      }
    }
    updatePersistence({ loadRecoveryStage: null });
    try {
      const response = await retryForServiceRecovery(async () => {
        const attempt = await request();
        if (attempt.status === 429 || attempt.status >= 500) {
          throw new Error(`Application service unavailable (${attempt.status}).`);
        }
        return attempt;
      }, (stage) => {
        if (isCurrent()) updatePersistence({ loadRecoveryStage: stage });
      });
      if (isCurrent()) updatePersistence({ loadRecoveryStage: null });
      return response;
    } catch {
      if (isCurrent()) updatePersistence({
        loadRecoveryStage: "failed",
        message: TECH_SUPPORT_ERROR_MESSAGE,
        phase: "load_error",
      });
      return null;
    }
  }

  async function reconcilePendingCopy(choice: "saved" | "guest"): Promise<void> {
    if (!pendingCopy) return;
    const inSession = sessionWork.capture();
    try {
      updatePersistence({ phase: "working" });
      const response = await reconcilePendingCopyRequest(choice, pendingCopy.baseRevision, pendingCopy.guestSavedAt);
      if (!inSession()) return;
      if (!response.ok) {
        const problem = await responseProblem(response);
        if (!inSession()) return;
        if (problem.code === "stale_application" || problem.code === "pending_copy_changed") {
          await restorePendingCopy();
          if (inSession()) updatePersistence({ message: problem.detail, phase: "error" });
          return;
        }
        if (problem.code === "pending_copy_not_found") {
          updatePersistence({ pendingCopy: null, phase: "idle" });
          await restoreApplication(applicationId ?? undefined);
          return;
        }
        updatePersistence({ message: problem.detail, phase: "error" });
        return;
      }
      updatePersistence({ pendingCopy: null });
      await restoreApplication(applicationId ?? undefined);
    } catch {
      if (inSession()) updatePersistence({ message: APPLICANT_ACTION_ERROR_MESSAGE, phase: "error" });
    }
  }

  function clearActionFeedback(): void {
    updatePersistence((state) => ({
      message: "",
      phase: ["saved", "email_sent", "email_failed", "error"].includes(state.phase) ? "idle" : state.phase,
    }));
  }

  function returnToApplication(): void {
    updatePersistence({ message: "", phase: "idle" });
  }

  async function openLinkedApplication(rememberDevice: boolean): Promise<void> {
    if (accessToken) await openLink(accessToken, true, rememberDevice);
  }

  async function openReadyApplication(rememberDevice: boolean): Promise<void> {
    if (accessToken) await openLink(accessToken, false, rememberDevice);
  }

  async function keepCurrentApplication(): Promise<void> {
    endSessionWork();
    updatePersistence({ linkConflict: null, accessToken: null });
    await restoreApplication();
  }

  async function emailNewAccessLink(): Promise<void> {
    if (!accessToken) return;
    const inSession = sessionWork.capture();
    try {
      updatePersistence({ phase: "working" });
      const response = await regenerateAccessLink(accessToken);
      if (!inSession()) return;
      if (!response.ok) return fail(response);
      const body = (await response.json()) as {
        targetAvailable: boolean;
        emailSent: boolean;
        emailStatus: EmailSendStatus;
      };
      if (!inSession()) return;
      if (!body.targetAvailable) {
        updatePersistence({ linkConflict: null, phase: "link_invalid" });
        return;
      }
      if (body.emailStatus === "failed") {
        updatePersistence({ message: TECH_SUPPORT_ERROR_MESSAGE, phase: "error" });
        return;
      }
      updatePersistence({
        message: body.emailSent
          ? accessPurpose === "email_change"
            ? "We emailed a new confirmation link. Open it to finish changing your email address."
            : "We emailed a new link to open your application."
          : accessPurpose === "email_change"
            ? "Check your inbox for the confirmation link we sent recently."
            : "Check your inbox for the application link we sent recently.",
        linkConflict: null,
        phase: "access_link_sent",
      });
    } catch {
      if (inSession()) updatePersistence({ message: APPLICANT_ACTION_ERROR_MESSAGE, phase: "error" });
    }
  }

  async function discardDraft(): Promise<void> {
    endSessionWork();
    if (applicationId != null) clearApplicationDraft(applicationId);
    updatePersistence({
      pendingDraftToken: null,
      openingIds: defaultOpeningIds(openings),
      savedAnswers: null,
      phase: "idle",
    });
    if (pendingDraftToken) await deletePendingDraft(pendingDraftToken);
  }

  async function fail(response: Response): Promise<void> {
    const inSession = sessionWork.capture();
    const problem = await responseProblem(response);
    if (!inSession()) return;
    const { applicationId } = stateRef.current;
    if (["applications_closed", "opening_archived", "opening_selection_required"].includes(
      problem.code ?? "",
    )) {
      if (applicationId != null) {
        if (!(await refreshLifecycleState())) {
          if (inSession()) updatePersistence((state) => (
            state.phase === "stale_copy" || state.phase === "session_expired"
              ? {} : { message: problem.detail, phase: "error" }
          ));
          return;
        }
      } else await restorePublicOpenings(true);
    }
    if (!inSession()) return;
    updatePersistence({ message: problem.detail,
      phase: problem.code === "stale_application" ? "stale_copy" : "error" });
  }

  async function refreshLifecycleState(): Promise<boolean> {
    const isCurrent = applicationReads.begin();
    const response = await fetchApplication().catch(() => null);
    if (!isCurrent()) return false;
    if (response === null) return false;
    if (response.status === 401) {
      updatePersistence({ message: "Your application session has ended.", phase: "session_expired" });
      return false;
    }
    if (!response.ok) return false;
    const body = (await response.json().catch(() => null)) as ApplicationResponse | null;
    if (!isCurrent()) return false;
    if (body === null) return false;
    const currentRevision = stateRef.current.workingRevision;
    updatePersistence((state) => {
      const stale = state.workingRevision !== null && state.workingRevision !== body.workingRevision;
      return {
        openings: body.openings,
        openingIds: validBrowserOpeningIds(state.openingIds, body.openings),
        canEdit: body.canEdit,
        ...(stale ? {
          message: "This application changed in another tab or browser.", phase: "stale_copy",
        } : { workingRevision: body.workingRevision }),
      };
    });
    return currentRevision === null || body.workingRevision === currentRevision;
  }

  function invalidateApplicationReads(): void {
    applicationReads.invalidate();
    pendingCopyReads.invalidate();
  }

  function endSessionWork(): void {
    sessionWork.reset();
    invalidateApplicationReads();
  }

  const saveFlow = createApplicantSaveFlow({
    stateRef,
    draftRef,
    invalidateReads: invalidateApplicationReads,
    captureSession: sessionWork.capture,
    updatePersistence,
    fail,
  });
  const emailFlow = createApplicantEmailFlow({
    beginApplicationRead: applicationReads.begin,
    captureSession: sessionWork.capture,
    updatePersistence,
    setDraft,
  });
  const withdrawalFlow = createApplicantWithdrawalFlow({
    endSessionWork,
    captureSession: sessionWork.capture,
    updatePersistence,
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
    clearReviewAfterAccess: () => updatePersistence({ reviewAfterAccess: false }),
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
      updatePersistence((state) => ({
        openingIds: selected
          ? [...new Set([...state.openingIds, openingId])]
          : state.openingIds.filter((id) => id !== openingId),
      }));
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
