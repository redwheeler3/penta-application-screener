import { useEffect, useState } from "react";

import { ApplicantErrorMessage } from "./ApplicantAccessScreens";
import { Required, TextField } from "./ApplicantFormFields";
import { EMAIL_INVALID_MESSAGE, EMAIL_PATTERN } from "./validation";

export function PrimaryEmailField(props: {
  value: string;
  locked: boolean;
  wide: boolean;
  showChangeAction: boolean;
  onChange: (email: string) => void;
  onChangeEmail: () => void;
}) {
  if (!props.locked) {
    return <TextField label="Email" email value={props.value} required onChange={props.onChange} />;
  }
  return (
    <div className={`applicant-field authenticated-email-field${props.wide ? " wide" : ""}`}>
      <span>Email<Required /></span>
      <div className="verified-email-control">
        <input type="text" value={props.value} readOnly data-email="true" />
        {props.showChangeAction ? (
          <button className="text-button" type="button" onClick={props.onChangeEmail}>
            Change email address
          </button>
        ) : null}
      </div>
    </div>
  );
}
export function EmailChangeField(props: {
  currentEmail: string;
  pendingEmail: string | null;
  status: "idle" | "sending" | "sent" | "confirmed" | "error";
  message: string;
  onRequest: (email: string) => void;
  onCancelPending: () => void;
  onClose: () => void;
}) {
  const [newEmail, setNewEmail] = useState("");
  const [editing, setEditing] = useState(!props.pendingEmail);
  const [validationMessage, setValidationMessage] = useState("");

  useEffect(() => setEditing(!props.pendingEmail), [props.pendingEmail]);

  if (props.status === "confirmed") {
    return (
      <div className="email-change-field success" role="status">
        <span>Email address changed</span>
        <div className="email-change-status">
          <span>You are now signed in as {props.currentEmail}.</span>
        </div>
        <button className="applicant-secondary-button compact" type="button" onClick={props.onClose}>Done</button>
      </div>
    );
  }

  if (props.pendingEmail && !editing) {
    return (
      <div className="email-change-field" role="status">
        <span>New email address</span>
        <div className="email-change-status">
          <strong>Check {props.pendingEmail}</strong>
          <span>{props.message || "Use the confirmation link to finish changing your email address."}</span>
        </div>
        <div className="email-change-actions confirmation-actions">
          <button className="applicant-secondary-button compact" type="button" onClick={() => setEditing(true)}>Use a different email</button>
          <button className="applicant-secondary-button compact danger" type="button" onClick={props.onCancelPending}>Cancel change</button>
        </div>
      </div>
    );
  }

  function sendConfirmation(): void {
    const normalized = newEmail.trim();
    if (!EMAIL_PATTERN.test(normalized)) {
      setValidationMessage(EMAIL_INVALID_MESSAGE);
      return;
    }
    if (normalized.toLowerCase() === props.currentEmail.toLowerCase()) {
      setValidationMessage("Enter a different email address.");
      return;
    }
    setValidationMessage("");
    props.onRequest(normalized);
  }

  return (
    <div className="email-change-field">
      <label className="applicant-field">
        <span>New email address</span>
        <input
          type="text"
          inputMode="email"
          autoComplete="email"
          value={newEmail}
          onChange={(event) => { setNewEmail(event.target.value); setValidationMessage(""); }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              sendConfirmation();
            }
          }}
          autoFocus
        />
        {validationMessage ? <small className="field-error">{validationMessage}</small> : null}
        {props.status === "error" && props.message ? (
          <small className="field-error"><ApplicantErrorMessage message={props.message} /></small>
        ) : null}
      </label>
      <div className="email-change-actions">
        <button className="applicant-secondary-button compact" type="button" onClick={props.pendingEmail ? () => setEditing(false) : props.onClose}>Cancel</button>
        <button className="applicant-primary-button compact" type="button" disabled={props.status === "sending"} onClick={sendConfirmation}>
          {props.status === "sending" ? "Sending…" : "Send confirmation link"}
        </button>
      </div>
    </div>
  );
}
