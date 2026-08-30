import { RefreshCw } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import { fetchEmailDeliveryIssues } from "../../api/dashboard";
import { formatPacificDateTime } from "../../format";
import type { EmailDeliveryIssue } from "../../types";
import { RetryLoadError } from "../shared/RetryLoadError";

export function EmailDeliveryPanel(props: { onError: (message: string) => void }): ReactNode {
  const [issues, setIssues] = useState<EmailDeliveryIssue[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [loadVersion, setLoadVersion] = useState(0);

  useEffect(() => {
    let live = true;
    setLoadFailed(false);
    fetchEmailDeliveryIssues()
      .then(({ items }) => {
        if (live) setIssues(items);
      })
      .catch(() => {
        if (!live) return;
        setLoadFailed(true);
        props.onError("Could not load email delivery.");
      });
    return () => {
      live = false;
    };
    // The parent toast callback is recreated when toast state changes. Retrying only when the
    // requested load version changes prevents a failed request from triggering a fetch loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadVersion]);

  const refresh = () => {
    setIssues(null);
    setLoadVersion((version) => version + 1);
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

      {loadFailed ? (
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
  application_email_change_confirmation: "Email change confirmation",
  application_email_changed: "Email change notice",
  application_unavailable: "Application unavailable",
  application_selected_locked: "Selected profile locked",
  application_unsuccessful: "Application decision",
  vacancy_opening: "Vacancy notification",
  application_opening: "Opening notification",
  application_opening_with_vacancy_notice: "Opening and vacancy notification",
};

function emailKindLabel(kind: string): string {
  return EMAIL_KIND_LABELS[kind]
    ?? kind.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}
