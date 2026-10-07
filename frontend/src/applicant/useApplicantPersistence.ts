import { type Dispatch, type SetStateAction, useEffect, useMemo, useReducer, useRef } from "react";

import { identityClient } from "../api/client";
import * as applicantApi from "./api";
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
  updateSnapshotEmail,
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
  inspectAccessLink,
  regenerateAccessLink,
} from "./api";
import {
  clearApplicationDraft,
  captureApplicantStorage,
  BROWSER_STORAGE_CLEAR_MESSAGE,
  hasAnswersBeyondEmail,
  loadApplicationDraft,
  remembersDevice,
} from "./draftStorage";
import { draftFromWorking } from "./applicationDraft";
import type { ApplicantDraft, ApplicantOpening } from "./types";

export function useApplicantPersistence(
  draft: ApplicantDraft,
  setDraft: Dispatch<SetStateAction<ApplicantDraft>>,
  onRememberDeviceChange: (remember: boolean) => void | Promise<void>,
) {
  const draftRef = useRef(draft);
  const applicationReads = useRequestScope();
  const pendingCopyReads = useRequestScope();
  const sessionWork = useRequestScope();
  const pendingMutation = useRef<RequestIsCurrent | null>(null);
  const linkStarted = useRef(false);
  const inspectedApplicationId = useRef<number | null>(null);
  const [persistence, updatePersistence] = useReducer(
    applicantPersistenceReducer,
    INITIAL_APPLICANT_PERSISTENCE_STATE,
  resetApplicantSession,
  );
  const {
    phase,
    loadRecoveryStage,
    message,
    browserStorageMessage,
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

  const api = useMemo(() => applicantApi.createApi(identityClient({ kind: "applicant", id: applicationId })), [applicationId]);
  const { reconcilePendingCopy: reconcilePendingCopyRequest } = api;

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
    const changed = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      if (detail?.kind === "applicant" && detail.reason === "mismatch") {
        markSessionChanged();
      }
    };
    const stored = (event: StorageEvent) => {
      if (event.key === "penta-session-change:applicant") refreshWhenVisible();
    };
    document.addEventListener("visibilitychange", refreshWhenVisible);
    window.addEventListener("focus", refreshWhenVisible);
    window.addEventListener("storage", stored);
    window.addEventListener("penta-session-changed", changed);
    return () => {
      document.removeEventListener("visibilitychange", refreshWhenVisible);
      window.removeEventListener("focus", refreshWhenVisible);
      window.removeEventListener("storage", stored);
      window.removeEventListener("penta-session-changed", changed);
    };
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
      inspectedApplicationId.current = body.applicationId;
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
      const exchange = applicantApi.createApi(identityClient({ kind: "applicant", id: inspectedApplicationId.current }));
      const response = await exchange.openAccessLink(token, switchCurrent, rememberDevice);
      if (!inSession()) return;
      if (!response.ok) return fail(response);
      const body = await linkBody(response);
      if (!inSession()) return;
      if (body.state === "unavailable") {
        updatePersistence({ phase: "applications_unavailable" });
        return;
      }
      if (body.state === "email_in_use" && body.applicationId != null) {
        await onRememberDeviceChange(rememberDevice);
        if (!inSession()) return;
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
      await onRememberDeviceChange(rememberDevice);
      if (!inSession()) return;
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

  async function restoreApplication(knownId?: number, copy: "remembered" | "saved" = "remembered",
    storage = captureApplicantStorage()): Promise<void> {
    const isCurrent = applicationReads.begin();
    const storedCopy = copy === "saved" ? storage : null;
    const expectedId = knownId ?? stateRef.current.applicationId;
    const read = expectedId == null ? applicantApi.fetchApplication
      : applicantApi.createApi(identityClient({ kind: "applicant", id: expectedId })).fetchApplication;
    const response = await recoverInitialLoad(read, isCurrent);
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
    if (expectedId != null && body.applicationId !== expectedId) {
      updatePersistence({ message: "Your session changed. Your answers have not been replaced.", phase: "session_expired" });
      return;
    }
    if (storedCopy !== null) await acceptChosenApplication(body, storedCopy, isCurrent);
    else applyApplicationCopy(body, copy);
    if (copy === "remembered") await restorePendingCopy(body.applicationId);
  }

  function applyApplicationCopy(body: ApplicationResponse, copy: "remembered" | "saved") {
    const serverOpeningIds = defaultOpeningIds(body.openings);
    let restoredOpeningIds = serverOpeningIds;
    let snapshot: string | null = null;
    if (body.answers) {
      const stored = copy === "remembered" && remembersDevice() ? loadApplicationDraft(body.applicationId) : null;
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
      ...(copy === "saved" ? { pendingCopy: null } : {}),
    });
  }

  async function acceptChosenApplication(
    body: ApplicationResponse, storage: ReturnType<typeof captureApplicantStorage>, isCurrent: RequestIsCurrent,
  ) {
    if (!(await clearApplicationDraft(body.applicationId, storage)) && isCurrent()) {
      updatePersistence({ browserStorageMessage: BROWSER_STORAGE_CLEAR_MESSAGE });
    }
    if (isCurrent()) applyApplicationCopy(body, "saved");
  }

  async function restorePendingCopy(acceptedApplicationId = applicationId, onResolved?: () => Promise<void>): Promise<boolean> {
    if (acceptedApplicationId === null) return false;
    const isCurrent = pendingCopyReads.begin();
    const restoredApi = applicantApi.createApi(identityClient({ kind: "applicant", id: acceptedApplicationId }));
    const response = await restoredApi.fetchPendingCopy().catch(() => null);
    if (!isCurrent()) return false;
    if (response === null) {
      updatePersistence({ message: APPLICANT_ACTION_ERROR_MESSAGE, phase: "error" });
      return false;
    }
    if (!response.ok) {
      if (response.status === 401) markSessionChanged();
      else await fail(response);
      return false;
    }
    const body = (await response.json().catch(() => null)) as { pendingCopy: PendingCopy | null } | null;
    if (!isCurrent()) return false;
    if (body === null) {
      updatePersistence({ message: APPLICANT_ACTION_ERROR_MESSAGE, phase: "error" });
      return false;
    }
    if (body.pendingCopy === null && onResolved) {
      await onResolved();
      return false;
    }
    updatePersistence({ pendingCopy: body.pendingCopy });
    return body.pendingCopy !== null;
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
    const storage = captureApplicantStorage();
    const inSession = sessionWork.capture();
    try {
      updatePersistence({ phase: "working" });
      const response = await reconcilePendingCopyRequest(choice, pendingCopy.baseRevision, pendingCopy.guestSavedAt);
      if (!inSession()) return;
      if (!response.ok) {
        const problem = await responseProblem(response);
        if (problem.code === "session_changed") { markSessionChanged(); return; }
        if (!inSession()) return;
        if (problem.code === "stale_application" || problem.code === "pending_copy_changed") {
          const needsChoice = await restorePendingCopy(applicationId,
            () => restoreApplication(applicationId ?? undefined, "saved", storage));
          if (needsChoice && inSession()) updatePersistence({ message: problem.detail, phase: "error" });
          return;
        }
        if (problem.code === "pending_copy_not_found") {
          await restoreApplication(applicationId ?? undefined, "saved", storage);
          return;
        }
        updatePersistence({ message: problem.detail, phase: "error" });
        return;
      }
      const body = await response.json() as ApplicationResponse;
      if (!inSession()) return;
      if (body.applicationId !== applicationId) { markSessionChanged(); return; }
      await acceptChosenApplication(body, storage, inSession);
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

  async function discardDraft(): Promise<boolean> {
    endSessionWork();
    const inSession = sessionWork.capture();
    updatePersistence({ phase: "working", message: "" });
    if (pendingDraftToken) {
      const response = await deletePendingDraft(pendingDraftToken).catch(() => null);
      if (!inSession()) return false;
      if (!response?.ok) {
        updatePersistence({ message: "Could not clear the saved draft. Your answers are still here; try again.", phase: "error" });
        return false;
      }
    }
    if (applicationId != null) await clearApplicationDraft(applicationId);
    if (!inSession()) return false;
    updatePersistence({
      pendingDraftToken: null,
      openingIds: defaultOpeningIds(openings),
      savedAnswers: null,
      phase: "idle",
    });
    return true;
  }

  function markSessionChanged() {
    if (stateRef.current.phase === "session_expired") return;
    endSessionWork();
    updatePersistence({ message: "Your session changed. Your answers are still here; sign in to the original application to continue.", phase: "session_expired" });
  }

  async function fail(response: Response): Promise<void> {
    const inSession = sessionWork.capture();
    const problem = await responseProblem(response);
    if (!inSession()) return;
    if (problem.code === "session_changed") { markSessionChanged(); return; }
    const { applicationId } = stateRef.current;
    if (["applications_closed", "applications_locked", "opening_archived", "opening_selection_required"].includes(
      problem.code ?? "",
    )) {
      if (applicationId != null) {
        if (!(await refreshLifecycleState(true))) {
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

  async function refreshLifecycleState(duringMutation = false): Promise<boolean> {
    if (!duringMutation && pendingMutation.current?.()) return false;
    const isCurrent = applicationReads.begin();
    const expectedId = stateRef.current.applicationId;
    if (expectedId == null) return false;
    const response = await applicantApi.createApi(identityClient({ kind: "applicant", id: expectedId })).fetchApplication().catch(() => null);
    if (!isCurrent()) return false;
    if (response === null) return false;
    if (response.status === 401) {
      updatePersistence({ message: "Your application session has ended.", phase: "session_expired" });
      return false;
    }
    if (!response.ok) {
      if (response.status === 409) await fail(response);
      return false;
    }
    const body = (await response.json().catch(() => null)) as ApplicationResponse | null;
    if (!isCurrent()) return false;
    if (body === null) return false;
    if (body.applicationId !== expectedId) {
      updatePersistence({ message: "Your session changed. Your answers have not been replaced.", phase: "session_expired" });
      return false;
    }
    const currentRevision = stateRef.current.workingRevision;
    updatePersistence((state) => {
      const stale = state.workingRevision !== null && state.workingRevision !== body.workingRevision;
      const emailChanged = state.primaryEmail !== null && body.primaryEmail !== state.primaryEmail;
      return {
        primaryEmail: body.primaryEmail,
        googleSignInLinked: body.googleSignInLinked,
        pendingEmailChange: body.pendingEmailChange,
        ...(emailChanged ? { emailChangeMessage: "", emailChangeStatus: "confirmed" as const,
          googleDisconnectedByEmailChange: state.googleSignInLinked } : {}),
        openings: body.openings,
        openingIds: validBrowserOpeningIds(state.openingIds, body.openings),
        canEdit: body.canEdit,
        ...(stale ? {
          message: "This application changed in another tab or browser.", phase: "stale_copy",
        } : { workingRevision: body.workingRevision,
          savedAnswers: updateSnapshotEmail(state.savedAnswers, body.primaryEmail),
          ...(state.phase === "session_expired" ? { phase: "idle" as const, message: "" } : {}),
        }),
      };
    });
    setDraft((current) => current.applicant.email === body.primaryEmail ? current
      : { ...current, applicant: { ...current.applicant, email: body.primaryEmail } });
    return currentRevision === null || body.workingRevision === currentRevision;
  }

  async function runMutation<Result>(operation: () => Promise<Result>, fallback: Result): Promise<Result> {
    const owner = sessionWork.capture();
    if (!owner() || pendingMutation.current?.()) return fallback;
    pendingMutation.current = owner;
    invalidateApplicationReads();
    try {
      return await operation();
    } finally {
      if (pendingMutation.current === owner) {
        pendingMutation.current = null;
        invalidateApplicationReads();
      }
    }
  }

  function invalidateApplicationReads(): void {
    applicationReads.invalidate();
    pendingCopyReads.invalidate();
  }

  function endSessionWork(): void {
    pendingMutation.current = null;
    sessionWork.reset();
    invalidateApplicationReads();
    // The abandoned request cannot acknowledge its outcome after the session changes.
    // Release its busy state; the next lifecycle read reconciles the pending address.
    updatePersistence((state) => state.emailChangeStatus === "sending"
      ? { emailChangeStatus: "idle" } : {});
  }

  const saveFlow = createApplicantSaveFlow({
    api,
    stateRef,
    draftRef,
    invalidateReads: invalidateApplicationReads,
    captureSession: sessionWork.capture,
    updatePersistence,
    fail,
    runMutation,
  });
  const emailFlow = createApplicantEmailFlow({
    api,
    runMutation,
    captureSession: sessionWork.capture,
    updatePersistence,
  });
  const withdrawalFlow = createApplicantWithdrawalFlow({
    api,
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
    browserStorageMessage,
    linkConflict,
    pendingCopy,
    accessEmail,
    accessPurpose,
    accessApplicationEmail,
    reviewAfterAccess,
    clearReviewAfterAccess: () => updatePersistence({ reviewAfterAccess: false }),
    clearActionFeedback,
    returnToApplication,
    reconcilePendingCopy: (choice: "saved" | "guest") => runMutation(() => reconcilePendingCopy(choice), undefined),
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
    busy: phase === "working" || emailChangeStatus === "sending",
  };
}
