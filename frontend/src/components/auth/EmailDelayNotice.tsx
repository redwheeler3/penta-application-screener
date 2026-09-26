import { MailWarning } from "lucide-react";

export function EmailDelayNotice() {
  return (
    <div className="email-delay-notice" role="status">
      <MailWarning size={18} aria-hidden="true" />
      <span>
        Email delivery is temporarily delayed and may take up to 48 hours. Google sign-in is immediate.
      </span>
    </div>
  );
}
