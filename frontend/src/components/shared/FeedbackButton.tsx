import { useRef, useState } from "react";
import type { ReactNode } from "react";
import { MessageSquarePlus } from "lucide-react";
import * as api from "../../api/feedback";
import { readProblem } from "../../api/problems";
import { useRequestScope, type RequestIsCurrent } from "../../hooks/useRequestScope";

// A persistent, low-key corner button available on every page: the member's channel to
// flag friction. Clicking opens an inline composer —
// one textarea, submit. The context the member was in (route/tab/current ranking) rides
// along invisibly (silent capture); identity, app version, and time are stamped
// server-side. Success closes an unchanged composer; newer text stays available to send.
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
  const requests = useRequestScope(open);
  const currentBody = useRef(body);
  currentBody.current = body;
  const pending = useRef<RequestIsCurrent | null>(null);

  function close() {
    requests.reset();
    setOpen(false);
    setBody("");
    setSubmitting(false);
  }

  async function submit() {
    const text = body.trim();
    if (!text || pending.current?.()) return;
    const isCurrent = requests.capture();
    const submitted = body;
    pending.current = isCurrent;
    setSubmitting(true);
    try {
      const response = await api.submitFeedback({
        body: text,
        // The location.pathname is the most stable "where were they" signal; the active
        // tab names the in-app view (tabs don't change the path).
        route: window.location.pathname,
        activeTab: props.activeTab,
        analysisId: props.analysisId,
        applicantId: props.applicantId,
      });
      if (!isCurrent()) return;
      if (response.ok) {
        const unchanged = currentBody.current === submitted;
        if (unchanged) close();
        props.onToast(unchanged ? "Thanks — your feedback was sent to Jeff." : "Feedback sent. Your newer text hasn’t been sent yet.");
      } else {
        const problem = await readProblem(response);
        if (isCurrent()) props.onError(problem ? `Could not send feedback: ${problem}` : "Could not send feedback.");
      }
    } catch {
      if (isCurrent()) props.onError("Could not confirm feedback submission. Your draft is still here; please try again.");
    } finally {
      if (pending.current === isCurrent) pending.current = null;
      if (isCurrent()) setSubmitting(false);
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
