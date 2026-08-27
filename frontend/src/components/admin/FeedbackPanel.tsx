import { type ReactNode, useEffect, useState } from "react";

import * as api from "../../api/feedback";
import { readProblem } from "../../api/problems";
import { formatPacificDateTime } from "../../format";
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
  onOpenApplicant: (id: number) => void;
  onOpenView: (tab: ViewTab) => void;
}): ReactNode {
  const [items, setItems] = useState<FeedbackItem[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [loadVersion, setLoadVersion] = useState(0);
  const [showResolved, setShowResolved] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);

  useEffect(() => {
    let live = true;
    setLoadError(false);
    api
      .fetchFeedback(showResolved)
      .then((list) => live && setItems(list))
      .catch(() => {
        if (!live) return;
        setLoadError(true);
        props.onError("Could not load feedback.");
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showResolved, loadVersion]);

  async function act(id: number, action: "resolve" | "reopen") {
    setBusyId(id);
    const response = await (
      action === "resolve" ? api.resolveFeedback(id) : api.reopenFeedback(id)
    );
    setBusyId(null);
    if (!response.ok) {
      props.onError((await readProblem(response)) ?? `Could not ${action} the feedback item.`);
      return;
    }
    api
      .fetchFeedback(showResolved)
      .then(setItems)
      .catch(() => props.onError("Could not refresh feedback."));
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
      {loadError ? (
        <RetryLoadError
          message="Couldn't load feedback."
          onRetry={() => setLoadVersion((version) => version + 1)}
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
                    onClick={() => props.onOpenApplicant(item.applicantId as number)}
                  >
                    {item.applicantName ?? `applicant #${item.applicantId}`}
                  </button>
                ) : item.activeTab && isViewTab(item.activeTab) ? (
                  <button
                    type="button"
                    className="feedback-context-link"
                    onClick={() => props.onOpenView(item.activeTab as ViewTab)}
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
                  disabled={busyId === item.id}
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
