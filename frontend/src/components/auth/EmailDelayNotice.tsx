import { MailWarning } from "lucide-react";

export function EmailDelayNotice() {
  return (
    <div className="email-delay-notice" role="status">
      <MailWarning size={18} aria-hidden="true" />
      <span>
        <strong>Email delivery is taking longer than usual.</strong>
        {" "}Google sign-in is immediate.
      </span>
    </div>
  );
}
