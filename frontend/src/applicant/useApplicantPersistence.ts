import { type Dispatch, type SetStateAction, useEffect, useRef, useState } from "react";

import { TECH_SUPPORT_ERROR_MESSAGE } from "../support";

import {
  cancelEmailChange,
  deletePendingDraft,
  fetchApplication,
  inspectAccessLink,
  logoutApplicant,
  openAccessLink,
  regenerateAccessLink,
  requestReturnAccessLink,
  requestApplicantReauthentication,
  requestEmailChange,
  saveApplication,
  savePendingDraft,
  submitApplication,
  type DraftIntent,
} from "./api";
import {
  clearApplicationDraft,
  clearApplicantStorage,
  loadApplicationDraft,
  remembersDevice,
} from "./draftStorage";
import {
  type ApplicantDraft,
  canonicalAnswers,
  draftFromWorking,
  type WorkingApplicationAnswers,
  workingAnswers,
} from "./types";

export type PersistencePhase =
  | "idle"
  | "working"
  | "email_sent"
  | "saved"
  | "submitted"
  | "link_ready"
  | "link_conflict"
  | "link_expired"
  | "link_invalid"
  | "error";

type ApplicationResponse = {
  applicationId: number;
  primaryEmail: string;
  pendingEmailChange: string | null;
  answers: WorkingApplicationAnswers | null;
};

type EmailChangeStatus = "idle" | "sending" | "sent" | "confirmed" | "error";

export type LinkConflict = {
  currentEmail: string;
  linkEmail: string;
  applicationEmail: string | null;
  purpose: "applicant_access" | "email_change";
  linkIsValid: boolean;
};

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
  const [pendingDraftToken, setPendingDraftToken] = useState<string | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [accessEmail, setAccessEmail] = useState<string | null>(null);
  const [accessPurpose, setAccessPurpose] = useState<"applicant_access" | "email_change">("applicant_access");
  const [accessApplicationEmail, setAccessApplicationEmail] = useState<string | null>(null);
  const [linkConflict, setLinkConflict] = useState<LinkConflict | null>(null);
  const [lastIntent, setLastIntent] = useState<DraftIntent>("save");
  const [reviewAfterAccess, setReviewAfterAccess] = useState(false);
  const [savedAnswers, setSavedAnswers] = useState<string | null>(null);
  const [primaryEmail, setPrimaryEmail] = useState<string | null>(null);
  const [pendingEmailChange, setPendingEmailChange] = useState<string | null>(null);
  const [emailChangeStatus, setEmailChangeStatus] = useState<EmailChangeStatus>("idle");
  const [emailChangeMessage, setEmailChangeMessage] = useState("");
  const [emailChangeNeedsReauthentication, setEmailChangeNeedsReauthentication] = useState(false);

  useEffect(() => {
    draftRef.current = draft;
  }, [draft]);

  useEffect(() => {
    if (
      savedAnswers !== null &&
      savedAnswers !== answerSnapshot(draft) &&
      (phase === "email_sent" || phase === "saved")
    ) {
      setPhase("idle");
    }
  }, [draft, phase, savedAnswers]);

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

  async function inspectLink(token: string): Promise<void> {
    setPhase("working");
    const response = await inspectAccessLink(token);
    if (!response.ok) return fail(response);
    const body = await linkBody(response);
    setAccessPurpose(body.purpose ?? "applicant_access");
    setAccessApplicationEmail(body.applicationEmail);
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
        clearApplicantStorage();
        onRememberDeviceChange(false);
        setPhase("idle");
      }
      return;
    }
    if (!response.ok) return fail(response);
    const body = (await response.json()) as ApplicationResponse;
    setApplicationId(body.applicationId);
    setPrimaryEmail(body.primaryEmail);
    setPendingEmailChange(body.pendingEmailChange);
    if (body.answers) {
      const stored = remembersDevice() ? loadApplicationDraft(body.applicationId) : null;
      const restored = stored?.draft ?? draftFromWorking(body.answers);
      restored.applicant.email = body.primaryEmail;
      setDraft(restored);
      setSavedAnswers(answerSnapshot(restored));
    }
    setPhase("idle");
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
        : "A confirmation was requested recently. Please check your inbox.",
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
    const body = (await response.json()) as { emailSent: boolean };
    setEmailChangeMessage(
      body.emailSent
        ? `Check ${primaryEmail ?? "your email"} for a fresh sign-in link.`
        : "A sign-in link was requested recently. Please check your inbox.",
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
    setPendingEmailChange(body.pendingEmailChange);
    setDraft((current) => ({
      ...current,
      applicant: { ...current.applicant, email: body.primaryEmail },
    }));
    setSavedAnswers((snapshot) => updateSnapshotEmail(snapshot, body.primaryEmail));
    if (emailChanged) {
      setEmailChangeMessage("");
      setEmailChangeNeedsReauthentication(false);
      setEmailChangeStatus("confirmed");
    }
  }

  async function start(intent: DraftIntent): Promise<void> {
    setLastIntent(intent);
    setMessage("");
    setPhase("working");
    if (applicationId != null) {
      await persistAuthenticatedApplication(intent);
      return;
    }

    const response = await savePendingDraft(
      workingAnswers(draftRef.current),
      intent,
      pendingDraftToken,
    );
    if (!response.ok) return fail(response);
    const body = (await response.json()) as { draftToken: string; emailSent: boolean };
    setPendingDraftToken(body.draftToken);
    setSavedAnswers(answerSnapshot(draftRef.current));
    setMessage(
      body.emailSent
        ? "Your draft is saved for 30 days. Use the secure link in your email to return."
        : "Your draft is saved for 30 days. A link was requested recently; please check your inbox.",
    );
    setPhase("email_sent");
  }

  async function saveForReview(): Promise<boolean> {
    if (applicationId == null) return true;
    setMessage("");
    setPhase("working");
    const saved = await persistAuthenticatedApplication("save");
    if (saved) setPhase("idle");
    return saved;
  }

  async function persistAuthenticatedApplication(intent: DraftIntent): Promise<boolean> {
    const response = intent === "submit"
      ? await submitApplication(canonicalAnswers(draftRef.current), true)
      : await saveApplication(workingAnswers(draftRef.current));
    if (!response.ok) {
      await fail(response);
      return false;
    }
    setSavedAnswers(answerSnapshot(draftRef.current));
    if (intent === "submit" && applicationId != null) clearApplicationDraft(applicationId);
    setPhase(intent === "submit" ? "submitted" : "saved");
    return true;
  }

  async function emailReturnLink(): Promise<boolean> {
    const response = await requestReturnAccessLink(workingAnswers(draftRef.current));
    if (!response.ok) return false;
    const body = (await response.json()) as { currentAnswersSaved: boolean };
    if (body.currentAnswersSaved) setSavedAnswers(answerSnapshot(draftRef.current));
    return true;
  }

  async function resendCurrentIntent(): Promise<void> {
    await start(lastIntent);
  }

  function clearActionFeedback(): void {
    setMessage("");
    setPhase((current) => (
      current === "saved" || current === "email_sent" || current === "error"
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
    const body = (await response.json()) as { emailSent: boolean };
    setMessage(body.emailSent ? "A new secure link is on its way." : "A link was requested recently. Please check your inbox.");
    setLinkConflict(null);
    setPhase("email_sent");
  }

  async function discardDraft(): Promise<void> {
    if (pendingDraftToken) await deletePendingDraft(pendingDraftToken);
    if (applicationId != null) clearApplicationDraft(applicationId);
    setPendingDraftToken(null);
  }

  async function signOut(): Promise<void> {
    await logoutApplicant();
    clearApplicantStorage();
    setApplicationId(null);
    setPrimaryEmail(null);
    setPendingEmailChange(null);
    setEmailChangeStatus("idle");
    setPhase("idle");
  }

  async function fail(response: Response): Promise<void> {
    setMessage(await responseDetail(response));
    setPhase("error");
  }

  return {
    phase,
    message,
    linkConflict,
    accessEmail,
    accessPurpose,
    accessApplicationEmail,
    reviewAfterAccess,
    clearReviewAfterAccess: () => setReviewAfterAccess(false),
    clearActionFeedback,
    start,
    saveForReview,
    emailReturnLink,
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
    signOut,
    authenticated: applicationId != null,
    applicationId,
    primaryEmail,
    pendingEmailChange,
    emailChangeStatus,
    emailChangeMessage,
    emailChangeNeedsReauthentication,
    hasUnsavedChanges: savedAnswers !== answerSnapshot(draft),
    busy: phase === "working",
  };
}

type AccessLinkBody = {
  state: "valid" | "expired" | "used" | "replaced" | "invalid" | "abandoned" | "email_in_use";
  purpose: "applicant_access" | "email_change" | null;
  currentEmail: string | null;
  linkEmail: string | null;
  applicationEmail: string | null;
  switchRequired: boolean;
  applicationId: number | null;
  pendingIntent: DraftIntent | null;
};

function linkBody(response: Response): Promise<AccessLinkBody> {
  return response.json() as Promise<AccessLinkBody>;
}

function accessCredentialFromFragment(): string | null {
  return new URLSearchParams(window.location.hash.slice(1)).get("applicant-link");
}

async function responseDetail(response: Response): Promise<string> {
  return (await responseProblem(response)).detail;
}

async function responseProblem(response: Response): Promise<{ code: string | null; detail: string }> {
  try {
    const body = (await response.json()) as { code?: string; detail?: string };
    return {
      code: body.code ?? null,
      detail: body.detail ?? TECH_SUPPORT_ERROR_MESSAGE,
    };
  } catch {
    return { code: null, detail: TECH_SUPPORT_ERROR_MESSAGE };
  }
}

function answerSnapshot(draft: ApplicantDraft): string {
  return JSON.stringify(workingAnswers(draft));
}

function updateSnapshotEmail(snapshot: string | null, email: string): string | null {
  if (snapshot === null) return null;
  const answers = JSON.parse(snapshot) as WorkingApplicationAnswers;
  return JSON.stringify({
    ...answers,
    applicant: { ...answers.applicant, email },
  });
}
