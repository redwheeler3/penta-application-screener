import { useCommitteeApi } from "../../api/identity";
import { useRef, useState } from "react";
import type { ReactNode } from "react";
import { MessageSquarePlus } from "lucide-react";
import * as feedbackApi from "../../api/feedback";
import { readProblem } from "../../api/problems";
import { useRequestScope, type RequestIsCurrent } from "../../hooks/useRequestScope";

type FeedbackContext = {
  route: string;
  activeTab: string;
  analysisId: number | null;
  applicantId: number | null;
  openingId: number | null;
  retainedReview: boolean;
};

export function FeedbackButton(props: Omit<FeedbackContext, "route"> & {
  applicantName?: string | null;
  onToast: (message: string) => void;
  onError: (message: string) => void;
}): ReactNode {
  const api = useCommitteeApi(feedbackApi);

  const [draft, setDraft] = useState<{ context: FeedbackContext; label: string } | null>(null);
  const [body, setBody] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const requests = useRequestScope(draft !== null);
  const currentBody = useRef(body);
  currentBody.current = body;
  const pending = useRef<RequestIsCurrent | null>(null);

  function close() {
    requests.reset();
    setDraft(null);
    setBody("");
    setSubmitting(false);
  }

  async function submit() {
    const text = body.trim();
    if (!draft || !text || pending.current?.()) return;
    const isCurrent = requests.capture();
    const submitted = body;
    pending.current = isCurrent;
    setSubmitting(true);
    try {
      const response = await api.submitFeedback({ ...draft.context, body: text });
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
      {draft ? (
        <div className="feedback-composer" role="dialog" aria-label="Send feedback">
          <label className="feedback-composer-label" htmlFor="feedback-body">
            {draft.label}
          </label>
          <textarea
            id="feedback-body"
            className="feedback-composer-input"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="What's working, what's confusing, what's missing? Keep general feedback free of applicant details."
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
          onClick={() => {
            const { activeTab, analysisId, applicantId, openingId, retainedReview } = props;
            setDraft({
              context: { route: window.location.pathname, activeTab, analysisId, applicantId, openingId, retainedReview },
              label: applicantId === null ? "Send feedback to the admins" : `Feedback about ${props.applicantName || `applicant #${applicantId}`}`,
            });
          }}
          title="Send feedback to the admins"
        >
          <MessageSquarePlus size={16} />
          Feedback
        </button>
      )}
    </div>
  );
}
