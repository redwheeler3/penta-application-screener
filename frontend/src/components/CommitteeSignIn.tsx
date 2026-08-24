import { LogIn, ShieldCheck } from "lucide-react";
import { type FormEvent, type ReactNode, useState } from "react";

import * as api from "../api";
import type { CommitteeLinkConflict, SignInState } from "../hooks/useSession";
import { TECH_SUPPORT_EMAIL } from "../support";

type CommitteeSignInProps = {
  emailSignInEnabled: boolean;
  isLoadingUser: boolean;
  userLoadFailed: boolean;
  signInState: SignInState;
  linkConflict: CommitteeLinkConflict | null;
  linkedEmail: string | null;
  onRequestLink: (email: string, rememberDevice: boolean) => Promise<void>;
  onKeepCurrent: () => void;
  onOpenLinked: () => Promise<void>;
  onEmailNew: () => Promise<void>;
  onReset: () => void;
  onRetrySession: () => Promise<void>;
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

  if (props.signInState === "exchanging") {
    return <SignInPanel title="Signing you in" message="Checking your secure sign-in link…" />;
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
        title="This secure link is no longer active"
        message={`We can send a new secure link to ${props.linkedEmail}.`}
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
        message="If that address has committee access, a sign-in link is on its way."
      >
        <button className="secondary-button" type="button" onClick={reset}>
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
          We couldn't sign in with that Google account. Try another account or ask an
          administrator to check its committee access.
        </p>
      ) : props.userLoadFailed ? (
        <p className="login-message login-message-error" role="alert">
          The server may have been starting up. Try checking your session again.
        </p>
      ) : (
        <p>
          {props.emailSignInEnabled
            ? "Choose Google or receive a secure sign-in link by email."
            : "Continue with your allowlisted Google account."}
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
          <a
            className={`${props.emailSignInEnabled ? "secondary" : "primary"}-button login-google-button`}
            href={api.googleSignInUrl(rememberDevice)}
          >
            Continue with Google
          </a>
          {props.emailSignInEnabled ? (
            <>
              <div className="login-divider" aria-hidden="true">
                <span>or use email</span>
              </div>
              <form className="login-form" onSubmit={submit}>
                <label>
                  <span>Email address</span>
                  <input
                    type="email"
                    required
                    autoComplete="email"
                    autoFocus
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
            </>
          ) : null}
        </>
      ) : null}

      {props.userLoadFailed ? (
        <button className="secondary-button" type="button" onClick={() => void props.onRetrySession()}>
          Retry session check
        </button>
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
      <h2>Choose which account to use</h2>
      <p>This browser and the email link belong to different committee members.</p>
      <dl className="login-identity-list">
        <div><dt>Currently signed in</dt><dd>{props.conflict.currentEmail}</dd></div>
        <div><dt>Email link</dt><dd>{props.conflict.linkEmail}</dd></div>
      </dl>
      {props.conflict.newLinkSent ? (
        <>
          <p className="login-message login-message-success" role="status">
            A new secure link is on its way to {props.conflict.linkEmail}.
          </p>
          <button className="primary-button" type="button" onClick={props.onKeepCurrent}>
            Continue as {props.conflict.currentEmail}
          </button>
        </>
      ) : (
        <div className="login-choice-actions">
          <button className="secondary-button" type="button" disabled={props.busy} onClick={props.onKeepCurrent}>
            Continue as {props.conflict.currentEmail}
          </button>
          <button
            className="primary-button"
            type="button"
            disabled={props.busy}
            onClick={() => void (props.conflict.linkIsValid ? props.onOpenLinked() : props.onEmailNew())}
          >
            {props.conflict.linkIsValid ? `Sign in as ${props.conflict.linkEmail}` : "Email a new link"}
          </button>
        </div>
      )}
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
