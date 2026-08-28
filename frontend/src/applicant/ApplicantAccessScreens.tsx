import { CalendarDays, LoaderCircle, Mail, ShieldCheck } from "lucide-react";
import { type FormEvent, useState } from "react";

import { TECH_SUPPORT_EMAIL, TECH_SUPPORT_ERROR_MESSAGE } from "../support";
import type { ServiceRecoveryStage } from "../serviceRecovery";
import type { PendingCopy } from "./applicantPersistence";
import { pendingCopyDifferences } from "./pendingCopyDiff";
import type { ApplicantOpening } from "./types";
import { EMAIL_INVALID_MESSAGE, EMAIL_PATTERN } from "./validation";

export function ApplicationEntry(props: {
  allowGuest: boolean;
  busy: boolean;
  onContinueGuest: () => void;
  onEmailLink: (email: string) => Promise<boolean>;
}) {
  const [email, setEmail] = useState("");
  const [validationMessage, setValidationMessage] = useState("");

  function sendLink(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (!EMAIL_PATTERN.test(email.trim())) {
      setValidationMessage(EMAIL_INVALID_MESSAGE);
      return;
    }
    setValidationMessage("");
    void props.onEmailLink(email);
  }

  return (
    <section className="application-entry">
      <ShieldCheck size={30} />
      <h2>{props.allowGuest ? "Start or continue an application" : "Continue your application"}</h2>
      <p>
        {props.allowGuest
          ? "Enter your email address. We’ll send you a link to start an application or open one you saved."
          : "If you applied before the deadline, enter your email address to continue."}
      </p>
      <form onSubmit={sendLink} noValidate>
        <label className="applicant-field">
          <span>Email address</span>
          <input
            type="email"
            autoComplete="email"
            value={email}
            aria-invalid={validationMessage ? "true" : undefined}
            onChange={(event) => {
              setEmail(event.target.value);
              if (validationMessage) setValidationMessage("");
            }}
          />
          {validationMessage ? <small className="field-error">{validationMessage}</small> : null}
        </label>
        <button className="applicant-primary-button" type="submit" disabled={props.busy}>
          <Mail size={17} /> Email me a link
        </button>
      </form>
      {props.allowGuest ? (
        <>
          <div className="application-entry-divider"><span>or</span></div>
          <button className="applicant-secondary-button" type="button" onClick={props.onContinueGuest}>
            Continue as a guest
          </button>
          <small>You can save your application and receive a link to open it later.</small>
        </>
      ) : (
        <div className="application-entry-vacancies">
          <small>New applications aren’t being accepted right now.</small>
          <a href="https://www.pentacoop.com/apply.html">
            Sign up for vacancy notifications
          </a>
        </div>
      )}
    </section>
  );
}

export function PendingCopyDecision(props: {
  pendingCopy: PendingCopy;
  openings: ApplicantOpening[];
  busy: boolean;
  error: string | null;
  onChoose: (choice: "saved" | "guest") => void;
}) {
  const differences = pendingCopyDifferences(
    props.pendingCopy.savedAnswers,
    props.pendingCopy.savedOpeningIds,
    props.pendingCopy.guestAnswers,
    props.pendingCopy.guestOpeningIds,
    props.openings,
  );
  return (
    <section className="pending-copy-decision">
      <ShieldCheck size={30} />
      <h2>Choose which application to keep</h2>
      <p>
        We found a saved application and a second version you started before signing in.
        Compare the changes, then choose which version to keep.
      </p>
      <div className="pending-copy-table">
        <div className="pending-copy-heading"><span>Changed answer</span><strong>Saved application</strong><strong>Answers just entered</strong></div>
        {differences.map((difference) => (
          <div className="pending-copy-row" key={difference.label}>
            <strong>{difference.label}</strong>
            <span>{difference.saved}</span>
            <span>{difference.guest}</span>
          </div>
        ))}
      </div>
      {props.error ? (
        <div className="persistence-action-status error" role="alert">
          <strong>We couldn’t keep that copy</strong>
          <ApplicantErrorMessage message={props.error} />
        </div>
      ) : null}
      <div className="review-actions">
        <button
          className="applicant-secondary-button"
          type="button"
          disabled={props.busy}
          onClick={() => props.onChoose("saved")}
        >
          Keep saved application
        </button>
        <button
          className="applicant-primary-button"
          type="button"
          disabled={props.busy}
          onClick={() => props.onChoose("guest")}
        >
          Keep answers just entered
        </button>
      </div>
    </section>
  );
}

export function ApplicationsUnavailable() {
  return (
    <section className="applications-unavailable">
      <CalendarDays size={30} />
      <h2>Applications aren’t open right now</h2>
      <p>Visit the Penta website for current housing and vacancy information.</p>
      <a className="applicant-primary-button" href="https://www.pentacoop.com/apply.html">
        View vacancy information
      </a>
    </section>
  );
}

export function ApplicationLoadRecovery(props: { stage: ServiceRecoveryStage }) {
  if (props.stage === "failed") {
    return (
      <section className="existing-application-choice" role="alert">
        <ShieldCheck size={28} />
        <h2>We still couldn’t load your application</h2>
        <p>
          We’re sorry. Please email Penta Tech Support at{" "}
          <a href={`mailto:${TECH_SUPPORT_EMAIL}`} target="_blank" rel="noreferrer">
            {TECH_SUPPORT_EMAIL}
          </a>.
        </p>
      </section>
    );
  }

  return (
    <section className="existing-application-choice" role="status">
      <ShieldCheck size={28} />
      <h2>{props.stage === "extended" ? "This is taking longer than usual" : "We’re having trouble connecting"}</h2>
      <p>
        {props.stage === "extended"
          ? "We still can’t load your application. We’ll keep trying automatically for another 60 seconds."
          : "The application service is waking up. This is normal, and we’re retrying automatically. Please give us a minute."}
      </p>
      <button className="applicant-primary-button is-busy" type="button" disabled>
        <LoaderCircle className="sign-in-retry-spinner" size={16} />
        <span>Retrying…</span>
      </button>
    </section>
  );
}

export function ApplicationSessionExpired(props: { onEmail: () => void }) {
  return (
    <section className="existing-application-choice">
      <ShieldCheck size={28} />
      <h2>Sign in to continue</h2>
      <p>For your security, you’ve been signed out. We can email you a new sign-in link.</p>
      <button className="applicant-primary-button" type="button" onClick={props.onEmail}>
        Email me a sign-in link
      </button>
    </section>
  );
}

export function AccessLinkReady(props: {
  email: string;
  applicationEmail: string | null;
  purpose: "applicant_access" | "email_change";
  onOpen: (rememberDevice: boolean) => void;
}) {
  const [rememberDevice, setRememberDevice] = useState(false);
  return (
    <section className="existing-application-choice">
      <ShieldCheck size={28} />
      <h2>
        {props.purpose === "email_change" ? "Change your application email to" : "You’re signing in as"}
        <span className="access-email">{props.email}</span>
      </h2>
      {props.purpose === "email_change" && props.applicationEmail ? (
        <p>The application currently uses {props.applicationEmail}.</p>
      ) : null}
      <label className="remember-device-choice">
        <input
          type="checkbox"
          checked={rememberDevice}
          onChange={(event) => setRememberDevice(event.target.checked)}
        />
        <span>Keep me signed in on this device</span>
      </label>
      <button
        className="applicant-primary-button"
        type="button"
        onClick={() => props.onOpen(rememberDevice)}
      >
        {props.purpose === "email_change" ? "Confirm email address" : "Open application"}
      </button>
    </section>
  );
}

export function AccessLinkSent(props: {
  purpose: "applicant_access" | "email_change";
  message: string;
}) {
  return (
    <section className="existing-application-choice">
      <Mail size={28} />
      <h2>Check your email</h2>
      <p>{props.message}</p>
      {props.purpose === "email_change" ? (
        <p>Your email address will not change until you open the link.</p>
      ) : null}
    </section>
  );
}

export function AccessLinkDecision(props: {
  conflict: {
    currentEmail: string;
    linkEmail: string;
    applicationEmail: string | null;
    purpose: "applicant_access" | "email_change";
    linkIsValid: boolean;
  };
  onKeepCurrent: () => void;
  onOpenLinked: (rememberDevice: boolean) => void;
  onEmailNew: () => void;
}) {
  const [rememberDevice, setRememberDevice] = useState(false);
  return (
    <section className="existing-application-choice">
      <ShieldCheck size={28} />
      <h2>{props.conflict.purpose === "applicant_access" && props.conflict.linkIsValid ? "Choose which application to open" : "Choose how to continue"}</h2>
      <p>
        {props.conflict.purpose === "email_change"
          ? "You clicked an email change link for a different applicant account than the one signed in on this browser."
          : "Another applicant is already signed in on this browser."}
      </p>
      {!props.conflict.linkIsValid ? (
        <p>
          {props.conflict.purpose === "email_change"
            ? "The confirmation link you clicked has expired or is no longer active. You’ll need a new confirmation link to finish changing the email address."
            : "The link you clicked has expired or is no longer active. You’ll need a new link to sign in with that account."}
        </p>
      ) : null}
      <dl className="access-identity-list">
        <div><dt>Signed in now</dt><dd>{props.conflict.currentEmail}</dd></div>
        {props.conflict.purpose === "email_change" && props.conflict.applicationEmail ? (
          <div><dt>Old email address</dt><dd>{props.conflict.applicationEmail}</dd></div>
        ) : null}
        <div><dt>{props.conflict.purpose === "email_change" ? "New email address" : "Link sent to"}</dt><dd>{props.conflict.linkEmail}</dd></div>
      </dl>
      {props.conflict.linkIsValid ? (
        <label className="remember-device-choice">
          <input
            type="checkbox"
            checked={rememberDevice}
            onChange={(event) => setRememberDevice(event.target.checked)}
          />
          <span>Keep {props.conflict.linkEmail} signed in on this device</span>
        </label>
      ) : null}
      <div className="review-actions">
        <button className="applicant-secondary-button" type="button" onClick={props.onKeepCurrent}>
          Stay signed in as {props.conflict.currentEmail}
        </button>
        <button
          className="applicant-primary-button"
          type="button"
          onClick={
            props.conflict.linkIsValid
              ? () => props.onOpenLinked(rememberDevice)
              : props.onEmailNew
          }
        >
          {props.conflict.linkIsValid
            ? props.conflict.purpose === "email_change" ? `Confirm change to ${props.conflict.linkEmail}` : `Sign in as ${props.conflict.linkEmail}`
            : props.conflict.purpose === "email_change" ? `Email a new confirmation to ${props.conflict.linkEmail}` : `Email a new link to ${props.conflict.linkEmail}`}
        </button>
      </div>
    </section>
  );
}

export function ExpiredAccessLink(props: {
  purpose: "applicant_access" | "email_change";
  onEmailNew: () => void;
}) {
  return (
    <section className="existing-application-choice">
      <Mail size={28} />
      <h2>This link has expired</h2>
      <p>
        {props.purpose === "email_change"
          ? "Your email address has not changed. We can send a new confirmation to the same address."
          : "We can email a new sign-in link to the same address."}
      </p>
      <button className="applicant-primary-button" type="button" onClick={props.onEmailNew}>
        {props.purpose === "email_change" ? "Email a new confirmation" : "Email a new link"}
      </button>
    </section>
  );
}

export function InvalidAccessLink() {
  return (
    <section className="existing-application-choice">
      <ShieldCheck size={28} />
      <h2>This link doesn’t work</h2>
      <p>Go to the application page to start or open an application.</p>
      <a className="applicant-primary-button" href={window.location.pathname}>
        Go to the application page
      </a>
    </section>
  );
}

export function ApplicantErrorMessage(props: { message: string }) {
  if (props.message !== TECH_SUPPORT_ERROR_MESSAGE) return <>{props.message}</>;
  return (
    <>
      Something went wrong. Email{" "}
      <a href={`mailto:${TECH_SUPPORT_EMAIL}`} target="_blank" rel="noreferrer">
        Penta Tech Support
      </a>.
    </>
  );
}

export function openingLabel(opening: ApplicantOpening): string {
  const unit = `${opening.unitSizeBedrooms}-bedroom home`;
  const charge = (opening.housingChargeCents / 100).toLocaleString("en-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: opening.housingChargeCents % 100 === 0 ? 0 : 2,
  });
  return `${unit} · ${charge} per month`;
}

export function formatOpeningDate(value: string): string {
  return new Intl.DateTimeFormat("en-CA", { dateStyle: "medium", timeZone: "UTC" })
    .format(new Date(`${value}T12:00:00Z`));
}
