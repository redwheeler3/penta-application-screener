import { LogIn } from "lucide-react";
import { type FormEvent, type ReactNode, useState } from "react";

import type { SignInState } from "../hooks/useSession";

type CommitteeSignInProps = {
  isLoadingUser: boolean;
  userLoadFailed: boolean;
  signInState: SignInState;
  onRequestLink: (email: string) => Promise<void>;
  onReset: () => void;
  onRetrySession: () => Promise<void>;
};

export function CommitteeSignIn(props: CommitteeSignInProps): ReactNode {
  const [email, setEmail] = useState("");
  const busy = props.isLoadingUser || props.signInState === "requesting";

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const normalizedEmail = email.trim();
    if (!normalizedEmail || busy) return;
    void props.onRequestLink(normalizedEmail);
  }

  function reset(): void {
    setEmail("");
    props.onReset();
  }

  if (props.signInState === "exchanging") {
    return <SignInPanel title="Signing you in" message="Checking your secure sign-in link…" />;
  }

  if (props.signInState === "emailSent") {
    return (
      <SignInPanel
        title="Check your email"
        message="If that address has committee access, a sign-in link is on its way. It expires in 15 minutes."
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
          This sign-in link is invalid or has expired. Request a new one.
        </p>
      ) : props.signInState === "requestFailed" ? (
        <p className="login-message login-message-error" role="alert">
          We couldn't send a sign-in link. Please try again.
        </p>
      ) : props.userLoadFailed ? (
        <p className="login-message login-message-error" role="alert">
          The server may have been starting up. Try checking your session again.
        </p>
      ) : (
        <p>We'll email you a secure sign-in link. No password needed.</p>
      )}

      {!props.isLoadingUser ? (
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
          <button className={`primary-button${busy ? " is-busy" : ""}`} type="submit" disabled={busy}>
            <LogIn size={16} />
            <span>Send sign-in link</span>
          </button>
        </form>
      ) : null}

      {props.userLoadFailed ? (
        <button className="secondary-button" type="button" onClick={() => void props.onRetrySession()}>
          Retry session check
        </button>
      ) : null}
    </SignInPanel>
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
