import { useCommitteeApi } from "../../api/identity";
import { type ReactNode, useRef, useState } from "react";

import * as feedbackApi from "../../api/feedback";
import { readProblem } from "../../api/problems";
import { formatPacificDateTime } from "../../format";
import { useFetchResource } from "../../hooks/useFetchResource";
import { useRequestScope } from "../../hooks/useRequestScope";
import type { FeedbackItem, ViewTab } from "../../types";
import { RetryLoadError } from "../shared/RetryLoadError";

const VIEW_LABELS: Record<ViewTab, string> = {
  applications: "Applications",
  ranking: "Ranking",
  observability: "Observability",
  evals: "Evals",
  eligibilitySettings: "Eligibility Settings",
  adminSettings: "Admin Settings",
};

function isViewTab(tab: string): tab is ViewTab {
  return tab in VIEW_LABELS;
}

function viewLabel(tab: string | null): string {
  if (!tab) return "unknown view";
  return isViewTab(tab) ? VIEW_LABELS[tab] : tab;
}

export function FeedbackPanel(props: {
  onError: (message: string) => void;
  onOpenApplicant: (id: number, openingId: number | null, retainedReview: boolean) => void;
  onOpenView: (tab: ViewTab, openingId: number | null) => void;
}): ReactNode {
  const api = useCommitteeApi(feedbackApi);

  const [showResolved, setShowResolved] = useState(false);
  const [busyIds, setBusyIds] = useState<Set<number>>(new Set());
  const pending = useRef(new Set<number>());
  const requests = useRequestScope();
  const feedback = useFetchResource<FeedbackItem[]>(
    () => api.fetchFeedback(showResolved),
    {
      reloadKey: showResolved,
      onError: () => props.onError("Could not load feedback."),
    },
  );
  const items = feedback.data;

  async function act(id: number, action: "resolve" | "reopen") {
    if (pending.current.has(id)) return;
    const isCurrent = requests.capture();
    pending.current.add(id);
    setBusyIds((current) => new Set(current).add(id));
    try {
      const response = await (
        action === "resolve" ? api.resolveFeedback(id) : api.reopenFeedback(id)
      );
      if (!isCurrent()) return;
      if (!response.ok) {
        const problem = await readProblem(response);
        if (isCurrent()) props.onError(problem ?? `Could not ${action} the feedback item.`);
        return;
      }
      void feedback.reload();
    } catch {
      if (isCurrent()) props.onError(`Could not confirm the feedback ${action}. Please try again.`);
    } finally {
      pending.current.delete(id);
      if (isCurrent()) setBusyIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
    }
  }

  return (
    <div className="settings-panel-body">
      <div className="settings-subtab-head">
        <h3>Feedback</h3>
        <p className="panel-hint">
          Feedback members sent from anywhere in the app, newest first. May contain applicant
          details — treat it as sensitive.
        </p>
      </div>
      <div className="feedback-admin-header">
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={showResolved}
            onChange={(event) => setShowResolved(event.target.checked)}
          />
          <span>Show resolved</span>
        </label>
      </div>
      {feedback.state === "error" ? (
        <RetryLoadError
          message="Couldn't load feedback."
          onRetry={feedback.reload}
        />
      ) : items === null ? (
        <p className="panel-hint">Loading…</p>
      ) : items.length === 0 ? (
        <p className="panel-hint">{showResolved ? "No feedback yet." : "No open feedback."}</p>
      ) : (
        <ul className="feedback-list">
          {items.map((item) => (
            <li key={item.id} className={`feedback-item${item.resolvedAt ? " is-resolved" : ""}`}>
              <p className="feedback-item-body">{item.body}</p>
              <div className="feedback-item-meta">
                <span>{item.userName}</span>
                <span>{item.userEmail}</span>
                <span>{formatPacificDateTime(item.createdAt)}</span>
                {item.applicantId !== null ? (
                  <button
                    type="button"
                    className="feedback-context-link"
                    onClick={() => props.onOpenApplicant(item.applicantId as number, item.openingId, item.retainedReview)}
                  >
                    {item.applicantName ?? `applicant #${item.applicantId}`}
                  </button>
                ) : item.activeTab && isViewTab(item.activeTab) ? (
                  <button
                    type="button"
                    className="feedback-context-link"
                    onClick={() => props.onOpenView(item.activeTab as ViewTab, item.openingId)}
                  >
                    {viewLabel(item.activeTab)}
                  </button>
                ) : (
                  <span>{viewLabel(item.activeTab)}</span>
                )}
                {item.analysisId !== null ? <span>ranking #{item.analysisId}</span> : null}
                <span>v{item.appVersion}</span>
              </div>
              <div className="feedback-item-actions">
                <button
                  type="button"
                  className="secondary-button"
                  disabled={busyIds.has(item.id)}
                  onClick={() => act(item.id, item.resolvedAt ? "reopen" : "resolve")}
                >
                  {item.resolvedAt ? "Reopen" : "Mark resolved"}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
