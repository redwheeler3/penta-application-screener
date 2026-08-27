import { type Dispatch, type SetStateAction, useEffect, useRef, useState } from "react";

import { TECH_SUPPORT_ERROR_MESSAGE } from "../support";
import { APPLICATION_ACCESS_EMAIL_MESSAGE } from "./accessMessages";
import {
  accessCredentialFromFragment,
  type ApplicationResponse,
  defaultOpeningIds,
  type EmailChangeStatus,
  type EmailSendStatus,
  type LinkConflict,
  linkBody,
  type PendingCopy,
  type PersistencePhase,
  responseDetail,
  responseProblem,
  updateSnapshotEmail,
  validBrowserOpeningIds,
  workingSnapshot,
} from "./applicantPersistence";
import {
  cancelEmailChange,
  checkGuestSubmission,
  deleteApplication as deleteApplicationRequest,
  deletePendingDraft,
  fetchApplicantOpenings,
  fetchApplication,
  fetchPendingCopy,
  inspectAccessLink,
  logoutApplicant,
  openAccessLink,
  regenerateAccessLink,
  reconcilePendingCopy as reconcilePendingCopyRequest,
  requestReturnAccessLink,
  revertApplication as revertApplicationRequest,
  requestApplicantReauthentication,
  requestEmailChange,
  saveApplication,
  savePendingDraft,
  submitApplication,
  submitGuestApplication,
  type DraftIntent,
} from "./api";
import {
  clearApplicationDraft,
  clearApplicantStorage,
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
  const [phase, setPhase] = useState<PersistencePhase>("idle");
  const [message, setMessage] = useState("");
  const [applicationId, setApplicationId] = useState<number | null>(null);
  const [workingRevision, setWorkingRevision] = useState<number | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [serverHasUnsubmittedChanges, setServerHasUnsubmittedChanges] = useState(false);
  const [openings, setOpenings] = useState<ApplicantOpening[]>([]);
  const [openingIds, setOpeningIds] = useState<number[]>([]);
  const [canEdit, setCanEdit] = useState(false);
  const [openingsLoaded, setOpeningsLoaded] = useState(false);
  const [pendingDraftToken, setPendingDraftToken] = useState<string | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [accessEmail, setAccessEmail] = useState<string | null>(null);
  const [accessPurpose, setAccessPurpose] = useState<"applicant_access" | "email_change">("applicant_access");
  const [accessApplicationEmail, setAccessApplicationEmail] = useState<string | null>(null);
  const [linkConflict, setLinkConflict] = useState<LinkConflict | null>(null);
  const [pendingCopy, setPendingCopy] = useState<PendingCopy | null>(null);
  const [lastIntent, setLastIntent] = useState<DraftIntent>("save");
  const [reviewAfterAccess, setReviewAfterAccess] = useState(false);
  const [savedAnswers, setSavedAnswers] = useState<string | null>(null);
  const [primaryEmail, setPrimaryEmail] = useState<string | null>(null);
  const [pendingEmailChange, setPendingEmailChange] = useState<string | null>(null);
  const [emailChangeStatus, setEmailChangeStatus] = useState<EmailChangeStatus>("idle");
  const [emailChangeMessage, setEmailChangeMessage] = useState("");
  const [emailChangeNeedsReauthentication, setEmailChangeNeedsReauthentication] = useState(false);
  const [collisionEmail, setCollisionEmail] = useState<string | null>(null);
  const [submissionEmailSent, setSubmissionEmailSent] = useState(true);
  const [deletionEmailSent, setDeletionEmailSent] = useState(true);
  const [deletionStatus, setDeletionStatus] = useState<"idle" | "working" | "reauth" | "error">("idle");
  const [deletionMessage, setDeletionMessage] = useState("");

  useEffect(() => {
    draftRef.current = draft;
  }, [draft]);

  useEffect(() => {
    if (
      savedAnswers !== null &&
      savedAnswers !== workingSnapshot(draft, openingIds) &&
      (phase === "email_sent" || phase === "saved")
    ) {
      setPhase("idle");
    }
  }, [draft, openingIds, phase, savedAnswers]);

  useEffect(() => {
    if (
      phase === "authentication_required" &&
      collisionEmail !== null &&
      draft.applicant.email.trim().toLowerCase() !== collisionEmail
    ) {
      setCollisionEmail(null);
      setMessage("");
      setPhase("idle");
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
    setAccessToken(token);
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
    setPhase("working");
    const response = await inspectAccessLink(token);
    if (!response.ok) return fail(response);
    const body = await linkBody(response);
    setAccessPurpose(body.purpose ?? "applicant_access");
    setAccessApplicationEmail(body.applicationEmail);
    if (body.state === "unavailable") {
      setPhase("applications_unavailable");
      return;
    }
    if (body.switchRequired && body.currentEmail && body.linkEmail) {
      setLinkConflict({
        currentEmail: body.currentEmail,
        linkEmail: body.linkEmail,
        applicationEmail: body.applicationEmail,
        purpose: body.purpose ?? "applicant_access",
        linkIsValid: body.state === "valid",
      });
      setPhase("link_conflict");
      return;
    }
    if (body.state === "valid" && body.linkEmail) {
      setAccessEmail(body.linkEmail);
      setAccessPurpose(body.purpose ?? "applicant_access");
      setAccessApplicationEmail(body.applicationEmail);
      setPhase("link_ready");
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
    setPhase(body.state === "invalid" || body.state === "abandoned" ? "link_invalid" : "link_expired");
  }

  async function openLink(
    token: string,
    switchCurrent: boolean,
    rememberDevice: boolean,
  ): Promise<void> {
    setPhase("working");
    const response = await openAccessLink(token, switchCurrent, rememberDevice);
    if (!response.ok) return fail(response);
    const body = await linkBody(response);
    if (body.state === "email_in_use" && body.applicationId != null) {
      onRememberDeviceChange(rememberDevice);
      setApplicationId(body.applicationId);
      await restoreApplication(body.applicationId);
      setEmailChangeMessage("That email address already has an application, so nothing was changed.");
      setEmailChangeStatus("error");
      setPhase("idle");
      return;
    }
    if (body.state !== "valid" || body.applicationId == null) {
      setPhase(body.state === "invalid" || body.state === "abandoned" ? "link_invalid" : "link_expired");
      return;
    }
    onRememberDeviceChange(rememberDevice);
    setApplicationId(body.applicationId);
    setReviewAfterAccess(body.purpose !== "email_change" && body.pendingIntent === "submit");
    setPendingCopy(body.pendingCopy);
    setLinkConflict(null);
    await restoreApplication(body.applicationId);
    if (body.purpose === "email_change") {
      setPendingEmailChange(null);
      setEmailChangeMessage("");
      setEmailChangeStatus("confirmed");
    }
  }

  async function restoreApplication(knownId?: number): Promise<void> {
    const response = await fetchApplication();
    if (response.status === 401) {
      if (knownId == null) {
        setApplicationId(null);
        setWorkingRevision(null);
        setSubmitted(false);
        setServerHasUnsubmittedChanges(false);
        setPhase("idle");
        await restorePublicOpenings();
      } else {
        setMessage("Your application session has ended.");
        setPhase("session_expired");
      }
      return;
    }
    if (!response.ok) return fail(response);
    const body = (await response.json()) as ApplicationResponse;
    setApplicationId(body.applicationId);
    setWorkingRevision(body.workingRevision);
    setSubmitted(body.submitted);
    setServerHasUnsubmittedChanges(body.hasUnsubmittedChanges);
    setPrimaryEmail(body.primaryEmail);
    setPendingEmailChange(body.pendingEmailChange);
    setOpenings(body.openings);
    setCanEdit(body.canEdit);
    setOpeningsLoaded(true);
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
      setSavedAnswers(workingSnapshot(serverDraft, serverOpeningIds));
    }
    setOpeningIds(restoredOpeningIds);
    setPhase("idle");
    await restorePendingCopy();
  }

  async function restorePendingCopy(): Promise<void> {
    const response = await fetchPendingCopy();
    if (!response.ok) return;
    const body = (await response.json()) as { pendingCopy: PendingCopy | null };
    setPendingCopy(body.pendingCopy);
  }

  async function restorePublicOpenings(preserveSelection = false): Promise<void> {
    const response = await fetchApplicantOpenings();
    if (!response.ok) {
      setMessage(await responseDetail(response));
      setPhase("load_error");
      return;
    }
    const body = (await response.json()) as {
      canStartApplication: boolean;
      openings: ApplicantOpening[];
    };
    setOpenings(body.openings);
    setOpeningIds((current) => (
      preserveSelection
        ? validBrowserOpeningIds(current, body.openings)
        : defaultOpeningIds(body.openings)
    ));
    setCanEdit(body.canStartApplication);
    setSubmitted(false);
    setServerHasUnsubmittedChanges(false);
    setOpeningsLoaded(true);
  }

  async function beginEmailChange(newEmail: string): Promise<void> {
    setEmailChangeStatus("sending");
    setEmailChangeMessage("");
    const response = await requestEmailChange(newEmail);
    if (!response.ok) {
      const problem = await responseProblem(response);
      setEmailChangeNeedsReauthentication(problem.code === "recent_authentication_required");
      setEmailChangeMessage(problem.detail);
      setEmailChangeStatus("error");
      return;
    }
    const body = (await response.json()) as {
      emailSent: boolean;
      emailStatus: EmailSendStatus;
      pendingEmail: string | null;
    };
    setPendingEmailChange(body.pendingEmail);
    if (body.pendingEmail === null) {
      setEmailChangeMessage(TECH_SUPPORT_ERROR_MESSAGE);
      setEmailChangeStatus("error");
      return;
    }
    setEmailChangeMessage(
      body.emailSent
        ? "Check your email to confirm the new address."
        : "Check your inbox for the confirmation link we sent recently.",
    );
    setEmailChangeNeedsReauthentication(false);
    setEmailChangeStatus("sent");
  }

  function clearEmailChangeFeedback(): void {
    setEmailChangeMessage("");
    setEmailChangeNeedsReauthentication(false);
    setEmailChangeStatus("idle");
  }

  async function emailReauthenticationLink(): Promise<void> {
    const response = await requestApplicantReauthentication();
    if (!response.ok) {
      setEmailChangeMessage(await responseDetail(response));
      return;
    }
    const body = (await response.json()) as {
      emailSent: boolean;
      emailStatus: EmailSendStatus;
    };
    setEmailChangeMessage(
      body.emailSent
        ? `Check ${primaryEmail ?? "your email"} for a new sign-in link.`
        : body.emailStatus === "failed"
          ? TECH_SUPPORT_ERROR_MESSAGE
          : "Check your inbox for the sign-in link we sent recently.",
    );
  }

  async function stopEmailChange(): Promise<boolean> {
    const response = await cancelEmailChange();
    if (!response.ok) {
      setEmailChangeMessage(await responseDetail(response));
      setEmailChangeStatus("error");
      return false;
    }
    setPendingEmailChange(null);
    setEmailChangeMessage("");
    setEmailChangeNeedsReauthentication(false);
    setEmailChangeStatus("idle");
    return true;
  }

  async function refreshEmailIdentity(): Promise<void> {
    const response = await fetchApplication();
    if (response.status === 401) {
      setEmailChangeMessage(
        "This session has ended. Continue in the tab where you confirmed the new address.",
      );
      setEmailChangeStatus("error");
      return;
    }
    if (!response.ok) return;
    const body = (await response.json()) as ApplicationResponse;
    const emailChanged = primaryEmail !== null && body.primaryEmail !== primaryEmail;
    setPrimaryEmail(body.primaryEmail);
    setSubmitted(body.submitted);
    setServerHasUnsubmittedChanges(body.hasUnsubmittedChanges);
    setPendingEmailChange(body.pendingEmailChange);
    setDraft((current) => ({
      ...current,
      applicant: { ...current.applicant, email: body.primaryEmail },
    }));
    if (emailChanged) {
      setEmailChangeMessage("");
      setEmailChangeNeedsReauthentication(false);
      setEmailChangeStatus("confirmed");
    }
    if (workingRevision !== null && body.workingRevision !== workingRevision) {
      setMessage("This application changed in another tab or browser.");
      setPhase("stale_copy");
      return;
    }
    setWorkingRevision(body.workingRevision);
    setSavedAnswers((snapshot) => updateSnapshotEmail(snapshot, body.primaryEmail));
  }

  async function start(intent: DraftIntent): Promise<void> {
    setLastIntent(intent);
    setMessage("");
    setPhase("working");
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
    setPendingDraftToken(body.draftToken);
    setSavedAnswers(workingSnapshot(draftRef.current, openingIds));
    if (body.emailStatus === "failed") {
      setMessage(TECH_SUPPORT_ERROR_MESSAGE);
      setPhase("email_failed");
    } else {
      setMessage(
        body.emailSent
          ? "Your application is saved. Use the link in your email to open it again."
          : "Your application is saved. Check your inbox for the link we sent recently.",
      );
      setPhase("email_sent");
    }
  }

  async function saveForReview(): Promise<boolean> {
    if (applicationId == null) return true;
    setMessage("");
    setPhase("working");
    const saved = await persistAuthenticatedApplication("save");
    if (saved) setPhase("idle");
    return saved;
  }

  async function prepareGuestReview(): Promise<boolean> {
    if (applicationId != null) return true;
    setMessage("");
    setPhase("working");
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
      setCollisionEmail(email);
      if (body.emailStatus === "failed") {
        setMessage(TECH_SUPPORT_ERROR_MESSAGE);
        setPhase("error");
      } else {
        setMessage(
          body.emailSent
            ? "An application already exists for this email. Check your inbox for a link to sign in and open it."
            : "An application already exists for this email. Check your inbox for the link we sent recently.",
        );
        setPhase("authentication_required");
      }
      return false;
    }
    setPhase("idle");
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
    const body = (await response.json()) as {
      emailSent: boolean;
      emailStatus: EmailSendStatus;
    };
    setSubmissionEmailSent(body.emailSent);
    setSavedAnswers(workingSnapshot(draftRef.current, openingIds));
    setPhase("submitted");
  }

  async function persistAuthenticatedApplication(intent: DraftIntent): Promise<boolean> {
    if (workingRevision == null) {
      setMessage(TECH_SUPPORT_ERROR_MESSAGE);
      setPhase("error");
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
    const body = (await response.json()) as ApplicationResponse & {
      emailSent?: boolean;
      emailStatus?: EmailSendStatus;
    };
    setWorkingRevision(body.workingRevision);
    setSubmitted(body.submitted);
    setServerHasUnsubmittedChanges(body.hasUnsubmittedChanges);
    setOpenings(body.openings);
    setCanEdit(body.canEdit);
    setSavedAnswers(workingSnapshot(draftRef.current, openingIds));
    if (intent === "submit" && applicationId != null) clearApplicationDraft(applicationId);
    if (intent === "submit") setSubmissionEmailSent(body.emailSent !== false);
    setPhase(intent === "submit" ? "submitted" : "saved");
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
      setSavedAnswers(workingSnapshot(draftRef.current, openingIds));
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
      setMessage(TECH_SUPPORT_ERROR_MESSAGE);
      setPhase("error");
      return false;
    }
    setDraft((current) => ({
      ...current,
      applicant: { ...current.applicant, email: email.trim().toLowerCase() },
    }));
    setMessage(APPLICATION_ACCESS_EMAIL_MESSAGE);
    setPhase("access_link_sent");
    return true;
  }

  async function reconcilePendingCopy(choice: "saved" | "guest"): Promise<void> {
    setPhase("working");
    const response = await reconcilePendingCopyRequest(choice);
    if (!response.ok) return fail(response);
    setPendingCopy(null);
    await restoreApplication(applicationId ?? undefined);
  }

  async function emailSessionAccessLink(): Promise<void> {
    setPhase("working");
    if (await emailReturnLink()) {
      setMessage(APPLICATION_ACCESS_EMAIL_MESSAGE);
      setPhase("access_link_sent");
      return;
    }
    setMessage(TECH_SUPPORT_ERROR_MESSAGE);
    setPhase("error");
  }

  async function resendCurrentIntent(): Promise<void> {
    await start(lastIntent);
  }

  function clearActionFeedback(): void {
    setMessage("");
    setPhase((current) => (
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
    setLinkConflict(null);
    setAccessToken(null);
    await restoreApplication();
  }

  async function emailNewAccessLink(): Promise<void> {
    if (!accessToken) return;
    setPhase("working");
    const response = await regenerateAccessLink(accessToken);
    if (!response.ok) return fail(response);
    const body = (await response.json()) as {
      targetAvailable: boolean;
      emailSent: boolean;
      emailStatus: EmailSendStatus;
    };
    if (!body.targetAvailable) {
      setLinkConflict(null);
      setPhase("link_invalid");
      return;
    }
    if (body.emailStatus === "failed") {
      setMessage(TECH_SUPPORT_ERROR_MESSAGE);
      setPhase("error");
      return;
    }
    setMessage(
      body.emailSent
        ? accessPurpose === "email_change"
          ? "We emailed a new confirmation link. Open it to finish changing your email address."
          : "We emailed a new link to open your application."
        : accessPurpose === "email_change"
          ? "Check your inbox for the confirmation link we sent recently."
          : "Check your inbox for the application link we sent recently.",
    );
    setLinkConflict(null);
    setPhase("access_link_sent");
  }

  async function discardDraft(): Promise<void> {
    if (pendingDraftToken) await deletePendingDraft(pendingDraftToken);
    if (applicationId != null) clearApplicationDraft(applicationId);
    setPendingDraftToken(null);
    setOpeningIds(defaultOpeningIds(openings));
    setSavedAnswers(null);
    setPhase("idle");
  }

  async function revertToSubmitted(): Promise<boolean> {
    if (workingRevision == null) {
      setMessage(TECH_SUPPORT_ERROR_MESSAGE);
      setPhase("error");
      return false;
    }
    const response = await revertApplicationRequest(workingRevision);
    if (!response.ok) {
      await fail(response);
      return false;
    }
    const body = (await response.json()) as ApplicationResponse;
    if (body.answers === null) {
      setMessage(TECH_SUPPORT_ERROR_MESSAGE);
      setPhase("error");
      return false;
    }
    const restored = draftFromWorking(body.answers);
    const restoredOpeningIds = defaultOpeningIds(body.openings);
    restored.applicant.email = body.primaryEmail;
    setDraft(restored);
    setOpenings(body.openings);
    setOpeningIds(restoredOpeningIds);
    setCanEdit(body.canEdit);
    setWorkingRevision(body.workingRevision);
    setSubmitted(body.submitted);
    setServerHasUnsubmittedChanges(false);
    setSavedAnswers(workingSnapshot(restored, restoredOpeningIds));
    if (applicationId != null) clearApplicationDraft(applicationId);
    setPhase("idle");
    return true;
  }

  async function removeApplication(): Promise<boolean> {
    setDeletionStatus("working");
    setDeletionMessage("");
    const response = await deleteApplicationRequest();
    if (!response.ok) {
      const problem = await responseProblem(response);
      if (problem.code === "unauthorized") {
        setMessage("Your application session has ended.");
        setPhase("session_expired");
        setDeletionStatus("idle");
        return false;
      }
      setDeletionStatus(problem.code === "recent_authentication_required" ? "reauth" : "error");
      setDeletionMessage(problem.detail);
      return false;
    }
    const body = (await response.json()) as { emailSent: boolean };
    setDeletionEmailSent(body.emailSent);
    clearApplicantStorage();
    setApplicationId(null);
    setWorkingRevision(null);
    setSubmitted(false);
    setServerHasUnsubmittedChanges(false);
    setPrimaryEmail(null);
    setPendingEmailChange(null);
    setDeletionStatus("idle");
    setPhase("deleted");
    return true;
  }

  async function emailDeletionReauthentication(): Promise<void> {
    const response = await requestApplicantReauthentication();
    if (!response.ok) {
      setDeletionStatus("error");
      setDeletionMessage(await responseDetail(response));
      return;
    }
    const body = (await response.json()) as { emailStatus: EmailSendStatus };
    if (body.emailStatus === "failed") {
      setDeletionStatus("error");
      setDeletionMessage(TECH_SUPPORT_ERROR_MESSAGE);
      return;
    }
    setDeletionMessage(
      body.emailStatus === "sent"
        ? "Check your email for a fresh sign-in link."
        : "A fresh sign-in link was requested recently. Check your inbox.",
    );
  }

  function clearDeletionFeedback(): void {
    setDeletionStatus("idle");
    setDeletionMessage("");
  }

  async function signOut(): Promise<boolean> {
    const response = await logoutApplicant();
    if (!response.ok) {
      await fail(response);
      return false;
    }
    clearApplicantStorage();
    setApplicationId(null);
    setWorkingRevision(null);
    setSubmitted(false);
    setServerHasUnsubmittedChanges(false);
    setPrimaryEmail(null);
    setPendingEmailChange(null);
    setEmailChangeStatus("idle");
    setPhase("idle");
    await restorePublicOpenings();
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
    setMessage(problem.detail);
    setPhase(problem.code === "stale_application" ? "stale_copy" : "error");
  }

  async function refreshLifecycleState(): Promise<boolean> {
    const response = await fetchApplication();
    if (response.status === 401) {
      setMessage("Your application session has ended.");
      setPhase("session_expired");
      return false;
    }
    if (!response.ok) return false;
    const body = (await response.json()) as ApplicationResponse;
    setOpenings(body.openings);
    setOpeningIds((current) => validBrowserOpeningIds(current, body.openings));
    setCanEdit(body.canEdit);
    setSubmitted(body.submitted);
    setServerHasUnsubmittedChanges(body.hasUnsubmittedChanges);
    if (workingRevision !== null && body.workingRevision !== workingRevision) {
      setMessage("This application changed in another tab or browser.");
      setPhase("stale_copy");
      return false;
    }
    setWorkingRevision(body.workingRevision);
    return true;
  }

  return {
    phase,
    message,
    linkConflict,
    pendingCopy,
    accessEmail,
    accessPurpose,
    accessApplicationEmail,
    submissionEmailSent,
    reviewAfterAccess,
    clearReviewAfterAccess: () => setReviewAfterAccess(false),
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
    beginEmailChange,
    clearEmailChangeFeedback,
    emailReauthenticationLink,
    stopEmailChange,
    refreshEmailIdentity,
    discardDraft,
    revertToSubmitted,
    removeApplication,
    emailDeletionReauthentication,
    clearDeletionFeedback,
    signOut,
    reloadLatestApplication: () => restoreApplication(applicationId ?? undefined),
    retryInitialLoad: () => (
      accessToken ? inspectLink(accessToken) : restoreApplication(applicationId ?? undefined)
    ),
    openings,
    openingIds,
    canEdit,
    openingsLoaded,
    setOpeningSelected: (openingId: number, selected: boolean) => {
      setOpeningIds((current) => (
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
    emailChangeNeedsReauthentication,
    hasUnsavedChanges: savedAnswers !== workingSnapshot(draft, openingIds),
    hasUnsubmittedChanges: submitted && (
      serverHasUnsubmittedChanges || savedAnswers !== workingSnapshot(draft, openingIds)
    ),
    hasSubmittedApplication: submitted,
    deletionEmailSent,
    deletionStatus,
    deletionMessage,
    workingRevision,
    busy: phase === "working",
  };
}
