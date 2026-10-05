import { MailWarning } from "lucide-react";

import { useEmailDeliveryStatus } from "../../hooks/useEmailDeliveryStatus";

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

/** Runtime work mounts only when the sign-in form actually renders its notice slot. */
export function EmailDeliveryAdvisory() {
  const delayed = useEmailDeliveryStatus();
  return delayed ? <EmailDelayNotice /> : null;
}
