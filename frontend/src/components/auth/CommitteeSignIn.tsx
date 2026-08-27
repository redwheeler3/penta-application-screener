import { LoaderCircle, LogIn, ShieldCheck } from "lucide-react";
import { type FormEvent, type ReactNode, useState } from "react";

import * as api from "../../api/auth";
import type { CommitteeLinkConflict, SignInState } from "../../hooks/useSession";
import { TECH_SUPPORT_EMAIL } from "../../support";

type CommitteeSignInProps = {
  emailSignInEnabled: boolean;
  isLoadingUser: boolean;
  userLoadFailed: boolean;
  signInState: SignInState;
  linkConflict: CommitteeLinkConflict | null;
  linkedEmail: string | null;
  autoFocusEmail?: boolean;
  onRequestLink: (email: string, rememberDevice: boolean) => Promise<void>;
  onKeepCurrent: () => void;
  onOpenLinked: () => Promise<void>;
  onEmailNew: () => Promise<void>;
  onReset: () => void;
};

export function CommitteeSignIn(props: CommitteeSignInProps): ReactNode {
  const [email, setEmail] = useState("");
  const [rememberDevice, setRememberDevice] = useState(false);
  const busy = props.isLoadingUser || props.signInState === "requesting";

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const normalizedEmail = email.trim();
    if (!normalizedEmail || busy) return;
    void props.onRequestLink(normalizedEmail, rememberDevice);
  }

  function reset(): void {
    setEmail("");
    props.onReset();
  }

  if (props.userLoadFailed) {
    return (
      <SignInPanel title="We’re having trouble connecting">
        <p>We can’t connect to Penta right now. We’ll keep trying automatically.</p>
        <button className="primary-button is-busy" type="button" disabled>
          <LoaderCircle className="sign-in-retry-spinner" size={16} />
          <span>Retrying…</span>
        </button>
      </SignInPanel>
    );
  }

  if (props.signInState === "exchanging") {
    return <SignInPanel title="Signing you in" message="Checking your sign-in link…" />;
  }

  if (props.linkConflict?.newLinkSent) {
    return (
      <SignInPanel
        title="Check your email"
        message={`A new sign-in link is on its way to ${props.linkConflict.linkEmail}.`}
      />
    );
  }

  if (props.linkConflict) {
    return (
      <CommitteeAccountChoice
        conflict={props.linkConflict}
        busy={busy}
        onKeepCurrent={props.onKeepCurrent}
        onOpenLinked={props.onOpenLinked}
        onEmailNew={props.onEmailNew}
      />
    );
  }

  if (props.signInState === "staleLink" && props.linkedEmail) {
    return (
      <SignInPanel
        title="This link has expired"
        message={`We can send a new sign-in link to ${props.linkedEmail}.`}
      >
        <button className="primary-button" type="button" onClick={() => void props.onEmailNew()}>
          Email a new link
        </button>
      </SignInPanel>
    );
  }

  if (props.signInState === "emailSent") {
    return (
      <SignInPanel
        title="Check your email"
        message={
          props.linkedEmail
            ? `If ${props.linkedEmail} has committee access, a sign-in link is on its way.`
            : "If that address has committee access, a sign-in link is on its way."
        }
      >
        <button className="primary-button" type="button" onClick={reset}>
          Use a different email
        </button>
      </SignInPanel>
    );
  }

  return (
    <SignInPanel title={props.isLoadingUser ? "Checking session" : "Sign in to continue"}>
      {props.signInState === "invalidLink" ? (
        <p className="login-message login-message-error" role="alert">
          This sign-in link is invalid or has expired.
          {props.emailSignInEnabled
            ? " Request a new one or continue with Google."
            : " Continue with Google."}
        </p>
      ) : props.signInState === "requestFailed" ? (
        <p className="login-message login-message-error" role="alert">
          We couldn't send a sign-in link. Email{" "}
          <a href={`mailto:${TECH_SUPPORT_EMAIL}`} target="_blank" rel="noreferrer">
            Penta Tech Support
          </a>.
        </p>
      ) : props.signInState === "googleDenied" ? (
        <p className="login-message login-message-error" role="alert">
          We couldn't sign in with that Google account. Try another account or email{" "}
          <a href={`mailto:${TECH_SUPPORT_EMAIL}`} target="_blank" rel="noreferrer">
            {TECH_SUPPORT_EMAIL}
          </a>.
        </p>
      ) : (
        <p>
          {props.emailSignInEnabled
            ? "Sign in with Google or receive a sign-in link by email."
            : "Continue with a Google account that has committee access."}
        </p>
      )}

      {!props.isLoadingUser ? (
        <>
          <label className="remember-device-choice">
            <input
              type="checkbox"
              checked={rememberDevice}
              onChange={(event) => setRememberDevice(event.target.checked)}
            />
            <span>Keep me signed in on this device</span>
          </label>
          {props.emailSignInEnabled ? (
            <>
              <form className="login-form" onSubmit={submit}>
                <label>
                  <span>Email address</span>
                  <input
                    type="email"
                    required
                    autoComplete="email"
                    autoFocus={props.autoFocusEmail ?? true}
                    placeholder="name@example.com"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                  />
                </label>
                <button
                  className={`primary-button${busy ? " is-busy" : ""}`}
                  type="submit"
                  disabled={busy}
                >
                  <LogIn size={16} />
                  <span>Send sign-in link</span>
                </button>
              </form>
              <div className="login-divider" aria-hidden="true">
                <span>or use Google</span>
              </div>
            </>
          ) : null}
          <a
            className={`${props.emailSignInEnabled ? "secondary" : "primary"}-button login-google-button`}
            href={api.googleSignInUrl(rememberDevice)}
          >
            Continue with Google
          </a>
        </>
      ) : null}

    </SignInPanel>
  );
}

function CommitteeAccountChoice(props: {
  conflict: CommitteeLinkConflict;
  busy: boolean;
  onKeepCurrent: () => void;
  onOpenLinked: () => Promise<void>;
  onEmailNew: () => Promise<void>;
}): ReactNode {
  return (
    <section className="login-panel committee-account-choice">
      <ShieldCheck size={28} />
      <span className="panel-kicker">Member access</span>
      <h2>{props.conflict.linkIsValid ? "Choose which account to use" : "Choose how to continue"}</h2>
      <p>Another committee member is already signed in on this browser.</p>
      {!props.conflict.linkIsValid ? (
        <p>
          The link you clicked has expired or is no longer active. You’ll need a new link to sign in with that account.
        </p>
      ) : null}
      <dl className="login-identity-list">
        <div><dt>Signed in now</dt><dd>{props.conflict.currentEmail}</dd></div>
        <div><dt>Link sent to</dt><dd>{props.conflict.linkEmail}</dd></div>
      </dl>
      <div className="login-choice-actions">
        <button className="secondary-button" type="button" disabled={props.busy} onClick={props.onKeepCurrent}>
          Stay signed in as {props.conflict.currentEmail}
        </button>
        <button
          className="primary-button"
          type="button"
          disabled={props.busy}
          onClick={() => void (props.conflict.linkIsValid ? props.onOpenLinked() : props.onEmailNew())}
        >
          {props.conflict.linkIsValid
            ? `Sign in as ${props.conflict.linkEmail}`
            : `Email a new link to ${props.conflict.linkEmail}`}
        </button>
      </div>
    </section>
  );
}

function SignInPanel(props: { title: string; message?: string; children?: ReactNode }): ReactNode {
  return (
    <section className="login-panel">
      <span className="panel-kicker">Member access</span>
      <h2>{props.title}</h2>
      {props.message ? (
        <p className="login-message login-message-success" role="status">
          {props.message}
        </p>
      ) : null}
      {props.children}
      <p className="login-legal">
        By signing in you agree to our{" "}
        <a href="https://www.pentacoop.com/terms.html" target="_blank" rel="noopener noreferrer">
          Terms of Service
        </a>{" "}
        and{" "}
        <a href="https://www.pentacoop.com/privacy.html" target="_blank" rel="noopener noreferrer">
          Privacy Policy
        </a>
        .
      </p>
    </section>
  );
}
