import { AlertTriangle, ArrowRight } from "lucide-react";
import type { ReactNode } from "react";

import { formatPacificDateTime } from "../format";
import type { AdminActions } from "../types";

export function AdminActionBanner(props: {
  actions: AdminActions | null;
  onReviewOpenings: () => void;
}): ReactNode {
  const openings = props.actions?.archivedOpeningsNeedingSelection ?? [];
  const queuedEmails = props.actions?.queuedEmailCount ?? 0;
  const quotaBlockedEmails = props.actions?.quotaBlockedEmailCount ?? 0;
  if (openings.length === 0 && queuedEmails === 0) return null;

  return (
    <>
      {queuedEmails > 0 && (
        <aside className="admin-action-banner no-print" role="alert">
          <AlertTriangle size={20} aria-hidden="true" />
          <div>
            <strong>{quotaBlockedEmails > 0 ? "Email quota reached" : "Email delivery delayed"}</strong>
            <span>
              {queuedEmails === 1 ? "One email is waiting" : `${queuedEmails} emails are waiting`}.
              Penta will retry once each day until SocketLabs accepts {queuedEmails === 1 ? "it" : "them"}.
            </span>
            {quotaBlockedEmails > 0 && (
              <span>
                {quotaBlockedEmails === 1
                  ? "One email is blocked by the SocketLabs quota."
                  : `${quotaBlockedEmails} emails are blocked by the SocketLabs quota.`}
              </span>
            )}
            <dl className="admin-action-details">
              <QueueTime label="Oldest queued" value={props.actions?.oldestQueuedEmailAt} />
              <QueueTime label="Newest queued" value={props.actions?.newestQueuedEmailAt} />
              <QueueTime label="Last attempt" value={props.actions?.lastEmailAttemptAt} />
            </dl>
          </div>
        </aside>
      )}
      {openings.length > 0 && (
        <aside className="admin-action-banner no-print" role="alert">
          <AlertTriangle size={20} aria-hidden="true" />
          <div>
            <strong>Opening decision required</strong>
            <span>
              {openings.length === 1
                ? "An archived opening needs a final decision before closeout email can be sent."
                : `${openings.length} archived openings need a final decision before closeout email can be sent.`}
            </span>
          </div>
          <button type="button" onClick={props.onReviewOpenings}>
            Review {openings.length === 1 ? "opening" : "openings"}
            <ArrowRight size={16} aria-hidden="true" />
          </button>
        </aside>
      )}
    </>
  );
}

function QueueTime(props: { label: string; value?: string | null }): ReactNode {
  if (!props.value) return null;
  return (
    <div>
      <dt>{props.label}</dt>
      <dd>{formatPacificDateTime(props.value)}</dd>
    </div>
  );
}
