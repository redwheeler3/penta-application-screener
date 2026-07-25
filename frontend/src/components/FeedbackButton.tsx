import { useState } from "react";
import type { ReactNode } from "react";
import { MessageSquarePlus } from "lucide-react";
import * as api from "../api";
import { readProblem } from "../format";

// A persistent, low-key corner button available on every page: the member's channel to
// flag friction (M15 "Future UX Enhancements" #2). Clicking opens an inline composer —
// one textarea, submit. The context the member was in (route/tab/current ranking) rides
// along invisibly (silent capture); identity, app version, and time are stamped
// server-side. On success a toast confirms and the composer closes.
export function FeedbackButton(props: {
  // The context attached to the submission, read from the app's live state. `activeTab`
  // is the accurate view label — when a candidate detail is open it names the detail, not
  // the tab behind it. `applicantId` is set only while that detail is open.
  activeTab: string;
  analysisId: number | null;
  applicantId: number | null;
  onToast: (message: string) => void;
  onError: (message: string) => void;
}): ReactNode {
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState("");
  const [submitting, setSubmitting] = useState(false);

  function close() {
    setOpen(false);
    setBody("");
  }

  async function submit() {
    const text = body.trim();
    if (!text || submitting) return;
    setSubmitting(true);
    const response = await api.submitFeedback({
      body: text,
      // The location.pathname is the most stable "where were they" signal; the active
      // tab names the in-app view (tabs don't change the path).
      route: window.location.pathname,
      activeTab: props.activeTab,
      analysisId: props.analysisId,
      applicantId: props.applicantId,
    });
    setSubmitting(false);
    if (response.ok) {
      close();
      props.onToast("Thanks — your feedback was sent to Jeff.");
    } else {
      const problem = await readProblem(response);
      props.onError(problem ? `Could not send feedback: ${problem}` : "Could not send feedback.");
    }
  }

  return (
    <div className="feedback-widget no-print">
      {open ? (
        <div className="feedback-composer" role="dialog" aria-label="Send feedback">
          <label className="feedback-composer-label" htmlFor="feedback-body">
            Send feedback to the admins
          </label>
          <textarea
            id="feedback-body"
            className="feedback-composer-input"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="What's working, what's confusing, what's missing?"
            rows={4}
            maxLength={5000}
            autoFocus
          />
          <div className="feedback-composer-actions">
            <button
              type="button"
              className="primary-button"
              onClick={submit}
              disabled={submitting || body.trim().length === 0}
            >
              {submitting ? "Sending" : "Send"}
            </button>
            <button type="button" className="secondary-button" onClick={close}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          className="feedback-fab"
          onClick={() => setOpen(true)}
          title="Send feedback to the admins"
        >
          <MessageSquarePlus size={16} />
          Feedback
        </button>
      )}
    </div>
  );
}
