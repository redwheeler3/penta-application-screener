import { RefreshCw } from "lucide-react";
import { type ReactNode } from "react";

import {
  fetchEmailDeliveryIssues,
  refreshSocketLabsDeliveryStatus,
} from "../../api/dashboard";
import { formatPacificDateTime } from "../../format";
import { useFetchResource } from "../../hooks/useFetchResource";
import type { EmailDeliveryIssue, SocketLabsQueueStatus } from "../../types";
import { RetryLoadError } from "../shared/RetryLoadError";

export function EmailDeliveryPanel(props: { onError: (message: string) => void }): ReactNode {
  const delivery = useFetchResource<{
    items: EmailDeliveryIssue[];
    socketlabs: SocketLabsQueueStatus;
  }>(
    fetchEmailDeliveryIssues,
    { onError: () => props.onError("Could not load email delivery.") },
  );
  const provider = useFetchResource<SocketLabsQueueStatus>(
    refreshSocketLabsDeliveryStatus,
  );
  const issues = delivery.data?.items ?? null;
  const socketlabs = provider.data ?? delivery.data?.socketlabs ?? null;

  const refresh = () => {
    void delivery.reload();
    void provider.reload();
  };

  return (
    <section className="access-panel email-delivery-panel no-print" aria-label="Email delivery">
      <div className="settings-subtab-head openings-header">
        <div>
          <h3>Email delivery</h3>
          <p className="panel-hint">
            Delivery status in the Application Screener and at SocketLabs.
          </p>
        </div>
        <button className="secondary-button" type="button" onClick={refresh}>
          <RefreshCw size={16} aria-hidden="true" />
          Refresh
        </button>
      </div>

      <SocketLabsStatus status={socketlabs} />
      <ScreenerDeliveryStatus
        state={delivery.state}
        issues={issues}
        onRetry={refresh}
      />
    </section>
  );
}

function SocketLabsStatus(props: { status: SocketLabsQueueStatus | null }): ReactNode {
  const { status } = props;
  if (status === null) {
    return (
      <section className="email-delivery-status" aria-label="SocketLabs delivery queue">
        <h4>SocketLabs delivery queue</h4>
        <div className="email-delivery-status-details"><span>Loading…</span></div>
      </section>
    );
  }
  const details = !status.available ? (
    <span>Current status unavailable. The Application Screener will continue sending normally.</span>
  ) : (
    <>
      <span>
        {status.queuedCount === 0
          ? "No messages are waiting at SocketLabs."
          : `${status.queuedCount} message${status.queuedCount === 1 ? " is" : "s are"} waiting at SocketLabs.`}
      </span>
      {status.oldestQueuedAt ? (
        <span>Oldest waiting since: {formatPacificDateTime(status.oldestQueuedAt)}</span>
      ) : null}
      {status.retrievedAt ? (
        <span>Checked: {formatPacificDateTime(status.retrievedAt)}</span>
      ) : null}
    </>
  );
  return (
    <section
      className={`email-delivery-status${status.delayed ? " is-delayed" : ""}`}
      aria-label="SocketLabs delivery queue"
    >
      <h4>SocketLabs delivery queue</h4>
      <div className="email-delivery-status-details">{details}</div>
    </section>
  );
}

function ScreenerDeliveryStatus(props: {
  state: "loading" | "ready" | "error";
  issues: EmailDeliveryIssue[] | null;
  onRetry: () => void;
}): ReactNode {
  return (
    <section className="email-delivery-status" aria-label="Application Screener delivery queue">
      <h4>Application Screener delivery queue</h4>
      {props.state === "error" ? (
        <RetryLoadError message="Couldn't load Application Screener email delivery." onRetry={props.onRetry} />
      ) : props.issues === null ? (
        <p className="panel-hint">Loading…</p>
      ) : props.issues.length === 0 ? (
        <p className="panel-hint">No emails are waiting to retry or failed.</p>
      ) : (
        <div className="access-table-scroll" role="region" aria-label="Application Screener email delivery issues">
          <table className="access-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Email address</th>
                <th>Email</th>
                <th>Status</th>
                <th>Attempts</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {props.issues.map((issue) => (
                <tr key={issue.id}>
                  <td>{formatPacificDateTime(issue.attemptedAt)}</td>
                  <td>{issue.recipientEmail}</td>
                  <td>{emailKindLabel(issue.messageKind)}</td>
                  <td>{deliveryStatus(issue)}</td>
                  <td>{issue.attemptCount}</td>
                  <td>{issue.errorCode ?? "Not reported"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function deliveryStatus(issue: EmailDeliveryIssue): string {
  if (issue.state === "failed") return "Failed";
  return issue.quotaBlocked ? "Waiting for quota" : "Waiting to retry";
}

const EMAIL_KIND_LABELS: Record<string, string> = {
  application_saved: "Saved application link",
  application_submitted: "Submitted application link",
  applicant_magic_link: "Applicant sign-in link",
  committee_magic_link: "Committee sign-in link",
  committee_invitation: "Committee invitation",
  application_email_change_confirmation: "Email change confirmation",
  application_email_changed: "Email change notice",
  application_unavailable: "Application unavailable",
  application_selected_locked: "Member application closed",
  application_unsuccessful: "Application decision",
  vacancy_opening: "Vacancy notification",
  application_opening: "Opening notification",
  application_opening_with_vacancy_notice: "Opening and vacancy notification",
};

function emailKindLabel(kind: string): string {
  return EMAIL_KIND_LABELS[kind]
    ?? kind.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}
