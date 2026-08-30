import { type Dispatch, type SetStateAction, useEffect, useReducer, useRef } from "react";

import { TECH_SUPPORT_ERROR_MESSAGE } from "../support";
import { retryForServiceRecovery } from "../serviceRecovery";
import { APPLICATION_ACCESS_EMAIL_MESSAGE } from "./accessMessages";
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
import { createApplicantWithdrawalFlow } from "./applicantWithdrawalFlow";
import { createApplicantEmailFlow } from "./applicantEmailFlow";
import {
  type ApplicantPersistenceState,
  applicantPersistenceReducer,
  INITIAL_APPLICANT_PERSISTENCE_STATE,
} from "./applicantPersistenceState";
import {
  checkGuestSubmission,
  deletePendingDraft,
  fetchApplicantOpenings,
  fetchApplication,
  fetchPendingCopy,
  inspectAccessLink,
  openAccessLink,
  regenerateAccessLink,
  reconcilePendingCopy as reconcilePendingCopyRequest,
  requestReturnAccessLink,
  revertApplication as revertApplicationRequest,
  saveApplication,
  savePendingDraft,
  submitApplication,
  submitGuestApplication,
  type DraftIntent,
} from "./api";
import {
  clearApplicationDraft,
  hasAnswersBeyondEmail,
  loadApplicationDraft,
  remembersDevice,
} from "./draftStorage";
import {
  type ApplicantDraft,
  type ApplicantOpening,
  canonicalAnswers,
  draftFromWorking,
  workingAnswers,
} from "./types";

export function useApplicantPersistence(
  draft: ApplicantDraft,
  setDraft: Dispatch<SetStateAction<ApplicantDraft>>,
  onRememberDeviceChange: (remember: boolean) => void,
) {
  const draftRef = useRef(draft);
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
    submitted,
    serverHasUnsubmittedChanges,
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
    lastIntent,
    reviewAfterAccess,
    savedAnswers,
    primaryEmail,
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

  useEffect(() => {
    draftRef.current = draft;
  }, [draft]);

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
  }, []);

  useEffect(() => {
    const refreshWhenVisible = () => {
      if (document.visibilityState !== "visible") return;
      if (applicationId != null) void refreshLifecycleState();
      else if (openingsLoaded) void restorePublicOpenings(true);
    };
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => document.removeEventListener("visibilitychange", refreshWhenVisible);
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
    }
  }

  async function restoreApplication(knownId?: number): Promise<void> {
    const response = await recoverInitialLoad(fetchApplication);
    if (response === null) return;
    if (response.status === 401) {
      if (knownId == null) {
        setPersistence("applicationId", null);
        setPersistence("workingRevision", null);
        setPersistence("submitted", false);
        setPersistence("serverHasUnsubmittedChanges", false);
        setPersistence("phase", "idle");
        await restorePublicOpenings();
      } else {
        setPersistence("message", "Your application session has ended.");
        setPersistence("phase", "session_expired");
      }
      return;
    }
    if (!response.ok) return fail(response);
    const body = (await response.json()) as ApplicationResponse;
    setPersistence("applicationId", body.applicationId);
    setPersistence("workingRevision", body.workingRevision);
    setPersistence("submitted", body.submitted);
    setPersistence("serverHasUnsubmittedChanges", body.hasUnsubmittedChanges);
    setPersistence("primaryEmail", body.primaryEmail);
    setPersistence("pendingEmailChange", body.pendingEmailChange);
    setPersistence("openings", body.openings);
    setPersistence("canEdit", body.canEdit);
    setPersistence("openingsLoaded", true);
    const serverOpeningIds = defaultOpeningIds(body.openings);
    let restoredOpeningIds = serverOpeningIds;
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
      restored.applicant.email = body.primaryEmail;
      setDraft(restored);
      setPersistence("savedAnswers", workingSnapshot(serverDraft, serverOpeningIds));
    }
    setPersistence("openingIds", restoredOpeningIds);
    setPersistence("phase", "idle");
    await restorePendingCopy();
  }

  async function restorePendingCopy(): Promise<void> {
    const response = await fetchPendingCopy();
    if (!response.ok) return;
    const body = (await response.json()) as { pendingCopy: PendingCopy | null };
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
    setPersistence("submitted", false);
    setPersistence("serverHasUnsubmittedChanges", false);
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

  async function start(intent: DraftIntent): Promise<void> {
    setPersistence("lastIntent", intent);
    setPersistence("message", "");
    setPersistence("phase", "working");
    if (applicationId != null) {
      await persistAuthenticatedApplication(intent);
      return;
    }
    if (intent === "submit") {
      await persistGuestApplication();
      return;
    }

    const response = await savePendingDraft(
      workingAnswers(draftRef.current),
      intent,
      pendingDraftToken,
      openingIds,
    );
    if (!response.ok) return fail(response);
    const body = (await response.json()) as {
      draftToken: string;
      emailSent: boolean;
      emailStatus: EmailSendStatus;
    };
    setPersistence("pendingDraftToken", body.draftToken);
    setPersistence("savedAnswers", workingSnapshot(draftRef.current, openingIds));
    if (body.emailStatus === "failed") {
      setPersistence("message", TECH_SUPPORT_ERROR_MESSAGE);
      setPersistence("phase", "email_failed");
    } else {
      setPersistence("message",
        body.emailSent
          ? "Your application is saved. Use the link in your email to open it again."
          : "Your application is saved. Check your inbox for the link we sent recently.",
      );
      setPersistence("phase", "email_sent");
    }
  }

  async function saveForReview(): Promise<boolean> {
    if (applicationId == null) return true;
    setPersistence("message", "");
    setPersistence("phase", "working");
    const saved = await persistAuthenticatedApplication("save");
    if (saved) setPersistence("phase", "idle");
    return saved;
  }

  async function prepareGuestReview(): Promise<boolean> {
    if (applicationId != null) return true;
    setPersistence("message", "");
    setPersistence("phase", "working");
    const email = draftRef.current.applicant.email.trim().toLowerCase();
    const response = await checkGuestSubmission(
      workingAnswers(draftRef.current),
      openingIds,
    );
    if (!response.ok) {
      await fail(response);
      return false;
    }
    const body = (await response.json()) as {
      canSubmit: boolean;
      emailSent: boolean;
      emailStatus: EmailSendStatus | null;
    };
    if (!body.canSubmit) {
      setPersistence("collisionEmail", email);
      if (body.emailStatus === "failed") {
        setPersistence("message", TECH_SUPPORT_ERROR_MESSAGE);
        setPersistence("phase", "error");
      } else {
        setPersistence("message",
          body.emailSent
            ? "An application already exists for this email. Check your inbox for a link to sign in and open it."
            : "An application already exists for this email. Check your inbox for the link we sent recently.",
        );
        setPersistence("phase", "authentication_required");
      }
      return false;
    }
    setPersistence("phase", "idle");
    return true;
  }

  async function persistGuestApplication(): Promise<void> {
    const response = await submitGuestApplication(
      canonicalAnswers(draftRef.current),
      true,
      openingIds,
      pendingDraftToken,
    );
    if (!response.ok) return fail(response);
    setPersistence("savedAnswers", workingSnapshot(draftRef.current, openingIds));
    setPersistence("phase", "submitted");
  }

  async function persistAuthenticatedApplication(intent: DraftIntent): Promise<boolean> {
    if (workingRevision == null) {
      setPersistence("message", TECH_SUPPORT_ERROR_MESSAGE);
      setPersistence("phase", "error");
      return false;
    }
    const response = intent === "submit"
      ? await submitApplication(
          canonicalAnswers(draftRef.current),
          true,
          openingIds,
          workingRevision,
        )
      : await saveApplication(workingAnswers(draftRef.current), openingIds, workingRevision);
    if (!response.ok) {
      await fail(response);
      return false;
    }
    const body = (await response.json()) as ApplicationResponse;
    setPersistence("workingRevision", body.workingRevision);
    setPersistence("submitted", body.submitted);
    setPersistence("serverHasUnsubmittedChanges", body.hasUnsubmittedChanges);
    setPersistence("openings", body.openings);
    setPersistence("canEdit", body.canEdit);
    setPersistence("savedAnswers", workingSnapshot(draftRef.current, openingIds));
    if (intent === "submit" && applicationId != null) clearApplicationDraft(applicationId);
    setPersistence("phase", intent === "submit" ? "submitted" : "saved");
    return true;
  }

  async function emailReturnLink(): Promise<boolean> {
    const response = await requestReturnAccessLink(
      workingAnswers(draftRef.current),
      openingIds,
      workingRevision,
    );
    if (!response.ok) {
      await fail(response);
      return false;
    }
    const body = (await response.json()) as {
      currentAnswersSaved: boolean;
      emailStatus: EmailSendStatus;
    };
    if (body.emailStatus === "failed") return false;
    if (body.currentAnswersSaved) {
      setPersistence("savedAnswers", workingSnapshot(draftRef.current, openingIds));
    }
    return true;
  }

  async function requestEntryLink(email: string): Promise<boolean> {
    const answers = workingAnswers(draftRef.current);
    answers.applicant.email = email.trim().toLowerCase();
    const response = await requestReturnAccessLink(answers, openingIds, null);
    if (!response.ok) {
      await fail(response);
      return false;
    }
    const body = (await response.json()) as { emailStatus: EmailSendStatus };
    if (body.emailStatus === "failed") {
      setPersistence("message", TECH_SUPPORT_ERROR_MESSAGE);
      setPersistence("phase", "error");
      return false;
    }
    setPersistence("message", APPLICATION_ACCESS_EMAIL_MESSAGE);
    setPersistence("phase", "access_link_sent");
    return true;
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

  async function emailSessionAccessLink(): Promise<void> {
    setPersistence("phase", "working");
    if (await emailReturnLink()) {
      setPersistence("message", APPLICATION_ACCESS_EMAIL_MESSAGE);
      setPersistence("phase", "access_link_sent");
      return;
    }
    setPersistence("message", TECH_SUPPORT_ERROR_MESSAGE);
    setPersistence("phase", "error");
  }

  async function resendCurrentIntent(): Promise<void> {
    await start(lastIntent);
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

  async function revertToSubmitted(): Promise<boolean> {
    if (workingRevision == null) {
      setPersistence("message", TECH_SUPPORT_ERROR_MESSAGE);
      setPersistence("phase", "error");
      return false;
    }
    const response = await revertApplicationRequest(workingRevision);
    if (!response.ok) {
      await fail(response);
      return false;
    }
    const body = (await response.json()) as ApplicationResponse;
    if (body.answers === null) {
      setPersistence("message", TECH_SUPPORT_ERROR_MESSAGE);
      setPersistence("phase", "error");
      return false;
    }
    const restored = draftFromWorking(body.answers);
    const restoredOpeningIds = defaultOpeningIds(body.openings);
    restored.applicant.email = body.primaryEmail;
    setDraft(restored);
    setPersistence("openings", body.openings);
    setPersistence("openingIds", restoredOpeningIds);
    setPersistence("canEdit", body.canEdit);
    setPersistence("workingRevision", body.workingRevision);
    setPersistence("submitted", body.submitted);
    setPersistence("serverHasUnsubmittedChanges", false);
    setPersistence("savedAnswers", workingSnapshot(restored, restoredOpeningIds));
    if (applicationId != null) clearApplicationDraft(applicationId);
    setPersistence("phase", "idle");
    return true;
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
    setPersistence("message", problem.detail);
    setPersistence("phase", problem.code === "stale_application" ? "stale_copy" : "error");
  }

  async function refreshLifecycleState(): Promise<boolean> {
    const response = await fetchApplication();
    if (response.status === 401) {
      setPersistence("message", "Your application session has ended.");
      setPersistence("phase", "session_expired");
      return false;
    }
    if (!response.ok) return false;
    const body = (await response.json()) as ApplicationResponse;
    setPersistence("openings", body.openings);
    setPersistence("openingIds", (current) => validBrowserOpeningIds(current, body.openings));
    setPersistence("canEdit", body.canEdit);
    setPersistence("submitted", body.submitted);
    setPersistence("serverHasUnsubmittedChanges", body.hasUnsubmittedChanges);
    if (workingRevision !== null && body.workingRevision !== workingRevision) {
      setPersistence("message", "This application changed in another tab or browser.");
      setPersistence("phase", "stale_copy");
      return false;
    }
    setPersistence("workingRevision", body.workingRevision);
    return true;
  }

  const emailFlow = createApplicantEmailFlow({
    setPersistence,
    setDraft,
    primaryEmail,
    workingRevision,
  });
  const withdrawalFlow = createApplicantWithdrawalFlow({
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
    start,
    prepareGuestReview,
    saveForReview,
    emailReturnLink,
    requestEntryLink,
    reconcilePendingCopy,
    emailSessionAccessLink,
    resendCurrentIntent,
    openLinkedApplication,
    openReadyApplication,
    keepCurrentApplication,
    emailNewAccessLink,
    ...emailFlow,
    discardDraft,
    revertToSubmitted,
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
    pendingEmailChange,
    emailChangeStatus,
    emailChangeMessage,
    hasUnsavedChanges: savedAnswers !== workingSnapshot(draft, openingIds),
    hasUnsubmittedChanges: submitted && (
      serverHasUnsubmittedChanges || savedAnswers !== workingSnapshot(draft, openingIds)
    ),
    hasSubmittedApplication: submitted,
    withdrawalStatus,
    withdrawalMessage,
    workingRevision,
    busy: phase === "working",
  };
}
