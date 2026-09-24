import { RefreshCw } from "lucide-react";
import { type ReactNode } from "react";

import { fetchEmailDeliveryIssues } from "../../api/dashboard";
import { formatPacificDateTime } from "../../format";
import { useFetchResource } from "../../hooks/useFetchResource";
import type { EmailDeliveryIssue } from "../../types";
import { RetryLoadError } from "../shared/RetryLoadError";

export function EmailDeliveryPanel(props: { onError: (message: string) => void }): ReactNode {
  const delivery = useFetchResource<EmailDeliveryIssue[]>(
    async () => (await fetchEmailDeliveryIssues()).items,
    { onError: () => props.onError("Could not load email delivery.") },
  );
  const issues = delivery.data;

  const refresh = () => {
    delivery.setData(null);
    void delivery.reload();
  };

  return (
    <section className="access-panel no-print" aria-label="Email delivery">
      <div className="settings-subtab-head openings-header">
        <div>
          <h3>Email delivery</h3>
          <p className="panel-hint">
            Emails waiting for another attempt and emails that could not be sent. Accepted emails
            are not listed.
          </p>
        </div>
        <button className="secondary-button" type="button" onClick={refresh}>
          <RefreshCw size={16} aria-hidden="true" />
          Refresh
        </button>
      </div>

      {delivery.state === "error" ? (
        <RetryLoadError message="Couldn't load email delivery." onRetry={refresh} />
      ) : issues === null ? (
        <p className="panel-hint">Loading…</p>
      ) : issues.length === 0 ? (
        <p className="panel-hint">No emails are waiting or failed.</p>
      ) : (
        <div className="access-table-scroll" role="region" aria-label="Email delivery issues">
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
              {issues.map((issue) => (
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
