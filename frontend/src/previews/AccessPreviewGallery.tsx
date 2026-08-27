import { useEffect, useState, type ReactNode } from "react";

import { request } from "../api/client";
import { APPLICATION_ACCESS_EMAIL_MESSAGE } from "../applicant/accessMessages";
import type { PendingCopy } from "../applicant/applicantPersistence";
import {
  AccessLinkDecision,
  AccessLinkReady,
  AccessLinkSent,
  ApplicationEntry,
  ApplicationLoadError,
  ApplicationsUnavailable,
  ApplicationSessionExpired,
  ExpiredAccessLink,
  InvalidAccessLink,
  PendingCopyDecision,
} from "../applicant/ApplicantAccessScreens";
import { emptyApplicantDraft, type ApplicantOpening, workingAnswers } from "../applicant/types";
import { BrandLockup } from "../BrandLockup";
import { CommitteeSignIn } from "../components/auth/CommitteeSignIn";
import type { CommitteeLinkConflict, SignInState } from "../hooks/useSession";
import "../styles/access-preview.css";

type EmailPreview = {
  key: string;
  title: string;
  subject: string;
  html: string;
};

const noAction = () => undefined;
const noAsyncAction = async () => undefined;
const emailLinkAccepted = async () => true;

export function AccessPreviewGallery() {
  const [emails, setEmails] = useState<EmailPreview[]>([]);
  const [emailError, setEmailError] = useState(false);

  useEffect(() => {
    let active = true;
    const loadEmails = async () => {
      try {
        const response = await request("/dev/previews/emails");
        if (!active) return;
        if (!response.ok) {
          setEmailError(true);
          return;
        }
        setEmails((await response.json()) as EmailPreview[]);
        setEmailError(false);
      } catch {
        if (active) setEmailError(true);
      }
    };

    void loadEmails();
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") void loadEmails();
    };
    window.addEventListener("focus", loadEmails);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      active = false;
      window.removeEventListener("focus", loadEmails);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, []);

  return (
    <div className="applicant-surface access-preview-gallery">
      <header className="access-preview-header">
        <BrandLockup />
        <span>Development preview</span>
      </header>
      <main>
        <div className="access-preview-introduction">
          <span className="panel-kicker">Design review</span>
          <h1>Access screens and emails</h1>
          <p>
            These are the production components and email templates populated with synthetic data.
            Buttons are intentionally inert, and nothing on this page sends email.
          </p>
          <nav aria-label="Preview sections">
            <a href="#applicant-access">Applicant access</a>
            <a href="#committee-access">Committee access</a>
            <a href="#email-previews">Emails</a>
          </nav>
        </div>

        <PreviewSection
          id="applicant-access"
          title="Applicant access"
          description="Entry, link, session, identity-conflict, and copy-reconciliation states."
        >
          <ApplicantAccessPreviews />
        </PreviewSection>

        <PreviewSection
          id="committee-access"
          title="Committee access"
          description="Google and email sign-in, link conflicts, loading, and error states."
        >
          <CommitteeAccessPreviews />
        </PreviewSection>

        <PreviewSection
          id="email-previews"
          title="Emails"
          description="Rendered before SocketLabs adds click tracking and the final unsubscribe destination."
        >
          {emailError ? (
            <p className="access-preview-error" role="alert">
              Email previews could not be loaded. Confirm the local backend is running in capture or development mode.
            </p>
          ) : emails.length === 0 ? (
            <p className="access-preview-loading" role="status">Rendering email previews…</p>
          ) : (
            <div className="email-preview-list">
              {emails.map((email) => (
                <article className="email-preview-card" key={email.key}>
                  <header>
                    <div>
                      <span>{email.title}</span>
                      <strong>Subject: {email.subject}</strong>
                    </div>
                    <a href={`#${email.key}`}>Link</a>
                  </header>
                  <iframe
                    id={email.key}
                    title={`${email.title} email preview`}
                    srcDoc={email.html}
                    sandbox=""
                  />
                </article>
              ))}
            </div>
          )}
        </PreviewSection>
      </main>
    </div>
  );
}

function ApplicantAccessPreviews() {
  const openings = previewOpenings();
  const pendingCopy = previewPendingCopy();
  return (
    <div className="access-preview-grid">
      <PreviewCard title="Applications open" description="A new or returning applicant arrives while guest access is available.">
        <ApplicationEntry allowGuest busy={false} onContinueGuest={noAction} onEmailLink={emailLinkAccepted} />
      </PreviewCard>
      <PreviewCard title="Applications closed" description="Only an existing applicant may request access.">
        <ApplicationEntry allowGuest={false} busy={false} onContinueGuest={noAction} onEmailLink={emailLinkAccepted} />
      </PreviewCard>
      <PreviewCard title="Applications unavailable" description="No opening currently accepts applications or changes.">
        <ApplicationsUnavailable />
      </PreviewCard>
      <PreviewCard title="Session expired" description="The applicant session reached its inactivity or absolute limit.">
        <ApplicationSessionExpired onEmail={noAction} />
      </PreviewCard>
      <PreviewCard title="Access link ready" description="A valid applicant link is opened with no conflicting session.">
        <AccessLinkReady email="applicant@example.test" applicationEmail={null} purpose="applicant_access" onOpen={noAction} />
      </PreviewCard>
      <PreviewCard title="Email change ready" description="A valid email-change confirmation is opened.">
        <AccessLinkReady email="new-address@example.test" applicationEmail="applicant@example.test" purpose="email_change" onOpen={noAction} />
      </PreviewCard>
      <PreviewCard title="Application access email sent" description="The same response is shown for every application-access request.">
        <AccessLinkSent purpose="applicant_access" message={APPLICATION_ACCESS_EMAIL_MESSAGE} />
      </PreviewCard>
      <PreviewCard title="Email-change confirmation sent" description="The new address must open its confirmation link.">
        <AccessLinkSent purpose="email_change" message="A confirmation link is on its way to new-address@example.test." />
      </PreviewCard>
      <PreviewCard title="Different applicant — link works" description="Another applicant is signed in when an application link is opened.">
        <AccessLinkDecision conflict={applicantConflict(true)} onKeepCurrent={noAction} onOpenLinked={noAction} onEmailNew={noAction} />
      </PreviewCard>
      <PreviewCard title="Different applicant — link expired" description="Another applicant is signed in and the emailed link has expired.">
        <AccessLinkDecision conflict={applicantConflict(false)} onKeepCurrent={noAction} onOpenLinked={noAction} onEmailNew={noAction} />
      </PreviewCard>
      <PreviewCard title="Email change, different application" description="The browser has another applicant’s application open.">
        <AccessLinkDecision conflict={emailChangeConflict(true)} onKeepCurrent={noAction} onOpenLinked={noAction} onEmailNew={noAction} />
      </PreviewCard>
      <PreviewCard title="Applicant link expired" description="The applicant can request a fresh 24-hour link.">
        <ExpiredAccessLink purpose="applicant_access" onEmailNew={noAction} />
      </PreviewCard>
      <PreviewCard title="Email-change link expired" description="The address remains unchanged until a new confirmation is opened.">
        <ExpiredAccessLink purpose="email_change" onEmailNew={noAction} />
      </PreviewCard>
      <PreviewCard title="Application link does not work" description="The emailed link cannot open an application.">
        <InvalidAccessLink />
      </PreviewCard>
      <PreviewCard title="Application could not be loaded" description="The applicant can try loading the application again.">
        <ApplicationLoadError message="The application service could not be reached." onRetry={noAction} />
      </PreviewCard>
      <PreviewCard wide title="Two application copies" description="A returning applicant entered guest answers before opening their saved application.">
        <PendingCopyDecision pendingCopy={pendingCopy} openings={openings} busy={false} error={null} onChoose={noAction} />
      </PreviewCard>
    </div>
  );
}

function CommitteeAccessPreviews() {
  return (
    <div className="access-preview-grid">
      <CommitteePreview title="Google or email" description="Normal committee sign-in when email delivery is configured." />
      <CommitteePreview title="Google only" description="Email sign-in is hidden when delivery is not configured." emailSignInEnabled={false} />
      <CommitteePreview title="Checking session" description="The existing browser session is being loaded." isLoadingUser />
      <CommitteePreview title="Checking sign-in link" description="A committee sign-in link is being checked." signInState="exchanging" />
      <CommitteePreview title="Check your email" description="A committee member has requested a sign-in link." signInState="emailSent" linkedEmail="member@example.test" />
      <CommitteePreview title="Expired committee link" description="The committee member can request a new sign-in link." signInState="staleLink" linkedEmail="member@example.test" />
      <CommitteePreview title="Different member, valid link" description="The browser and link belong to different committee members." linkConflict={committeeConflict(true)} />
      <CommitteePreview title="Different member, stale link" description="The conflicting link must be regenerated." linkConflict={committeeConflict(false)} />
      <CommitteePreview title="Replacement link sent" description="A new link was sent after resolving a stale conflict." linkConflict={{ ...committeeConflict(false), newLinkSent: true }} />
      <CommitteePreview title="Invalid committee link" description="The sign-in token is invalid or expired." signInState="invalidLink" />
      <CommitteePreview title="Email delivery failed" description="The sign-in email could not be sent." signInState="requestFailed" />
      <CommitteePreview title="Google access denied" description="The Google account does not have committee access." signInState="googleDenied" />
      <CommitteePreview title="Sign-in check failed" description="The app could not determine whether the committee member is signed in." userLoadFailed />
    </div>
  );
}

function CommitteePreview(props: {
  title: string;
  description: string;
  emailSignInEnabled?: boolean;
  isLoadingUser?: boolean;
  userLoadFailed?: boolean;
  signInState?: SignInState;
  linkConflict?: CommitteeLinkConflict | null;
  linkedEmail?: string | null;
}) {
  return (
    <PreviewCard title={props.title} description={props.description} committee>
      <CommitteeSignIn
        emailSignInEnabled={props.emailSignInEnabled ?? true}
        isLoadingUser={props.isLoadingUser ?? false}
        userLoadFailed={props.userLoadFailed ?? false}
        signInState={props.signInState ?? "idle"}
        linkConflict={props.linkConflict ?? null}
        linkedEmail={props.linkedEmail ?? null}
        autoFocusEmail={false}
        onRequestLink={noAsyncAction}
        onKeepCurrent={noAction}
        onOpenLinked={noAsyncAction}
        onEmailNew={noAsyncAction}
        onReset={noAction}
      />
    </PreviewCard>
  );
}

function PreviewSection(props: {
  id: string;
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="access-preview-section" id={props.id}>
      <header>
        <h2>{props.title}</h2>
        <p>{props.description}</p>
      </header>
      {props.children}
    </section>
  );
}

function PreviewCard(props: {
  title: string;
  description: string;
  children: ReactNode;
  wide?: boolean;
  committee?: boolean;
}) {
  return (
    <article className={`access-preview-card${props.wide ? " is-wide" : ""}${props.committee ? " is-committee" : ""}`}>
      <header>
        <h3>{props.title}</h3>
        <p>{props.description}</p>
      </header>
      <div
        className="access-preview-canvas"
        onClickCapture={(event) => {
          if (event.target instanceof Element && event.target.closest("a")) {
            event.preventDefault();
          }
        }}
      >
        {props.children}
      </div>
    </article>
  );
}

function previewOpenings(): ApplicantOpening[] {
  return [
    {
      id: 1,
      unitSizeBedrooms: 2,
      housingChargeCents: 125000,
      applicationOpenDate: "2026-08-01",
      applicationCloseDate: "2026-08-20",
      moveInDate: "2026-10-01",
      phase: "closed",
      selected: true,
      participating: true,
      hasParticipated: true,
      canSelect: false,
      canWithdraw: false,
    },
    {
      id: 2,
      unitSizeBedrooms: 3,
      housingChargeCents: 145000,
      applicationOpenDate: "2026-09-01",
      applicationCloseDate: "2026-09-15",
      moveInDate: "2026-10-01",
      phase: "open",
      selected: false,
      participating: false,
      hasParticipated: false,
      canSelect: true,
      canWithdraw: false,
    },
  ];
}

function previewPendingCopy(): PendingCopy {
  const savedDraft = emptyApplicantDraft();
  savedDraft.applicant = {
    firstName: "Alex",
    lastName: "Rivera",
    birthDate: "1987-04-12",
    email: "applicant@example.test",
    phone: "604-555-0101",
  };
  savedDraft.essays.householdIntroduction = "We are a family of four looking for a long-term co-op community.";
  const guestDraft = structuredClone(savedDraft);
  guestDraft.applicant.phone = "604-555-0199";
  guestDraft.essays.householdIntroduction = "We are a family of four who enjoy gardening and community meals.";
  return {
    savedAnswers: workingAnswers(savedDraft),
    savedOpeningIds: [1],
    guestAnswers: workingAnswers(guestDraft),
    guestOpeningIds: [2],
  };
}

function applicantConflict(linkIsValid: boolean) {
  return {
    currentEmail: "current@example.test",
    linkEmail: "linked@example.test",
    applicationEmail: "linked@example.test",
    purpose: "applicant_access" as const,
    linkIsValid,
  };
}

function emailChangeConflict(linkIsValid: boolean) {
  return {
    currentEmail: "other-applicant@example.test",
    linkEmail: "new-address@example.test",
    applicationEmail: "applicant@example.test",
    purpose: "email_change" as const,
    linkIsValid,
  };
}

function committeeConflict(linkIsValid: boolean): CommitteeLinkConflict {
  return {
    currentEmail: "current-member@example.test",
    linkEmail: "linked-member@example.test",
    linkIsValid,
  };
}
