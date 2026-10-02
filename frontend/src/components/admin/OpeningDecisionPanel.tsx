import { UserCheck, UserX } from "lucide-react";
import { type ReactNode, useState } from "react";

import * as api from "../../api/openings";
import { streamNdjson } from "../../api/client";
import { readProblem } from "../../api/problems";
import type { Opening, OpeningDecisionStreamEvent, OpeningSelection, OpeningSelectionCandidate } from "../../types";

type DecisionProgress = { processed: number; total: number | null; sent: number };
type DecisionChoice =
  | { kind: "candidates" }
  | { kind: "candidate"; candidate: OpeningSelectionCandidate }
  | { kind: "no-household" };

/** Owns decision confirmation and the streamed outcome-email progress. */
export function OpeningDecisionPanel(props: {
  selection: OpeningSelection;
  onSaved: (openings: Opening[], message: string) => void;
  busy: boolean;
  setBusy: (busy: boolean) => void;
  onError: (message: string) => void;
  onReview: (applicationId: number) => void;
  onClose: () => void;
}): ReactNode {
  const [choice, setChoice] = useState<DecisionChoice>({ kind: "candidates" });
  const { busy, setBusy } = props;
  const [progress, setProgress] = useState<DecisionProgress | null>(null);

  async function confirm(): Promise<void> {
    if (choice.kind === "candidates" || busy) return;
    setBusy(true);
    setProgress({ processed: 0, total: null, sent: 0 });
    try {
      const response = choice.kind === "candidate"
        ? await api.confirmOpeningSelection(props.selection.openingId, choice.candidate.applicationId)
        : await api.confirmNoHouseholdSelected(props.selection.openingId);
      if (!response.ok || !response.body) {
        props.onError((await readProblem(response)) ?? "Could not save the opening decision.");
        return;
      }
      const summaries: Array<Extract<OpeningDecisionStreamEvent, { type: "summary" }>> = [];
      await streamNdjson<OpeningDecisionStreamEvent>(response.body, (event) => {
        if (event.type === "progress") {
          setProgress({ processed: event.processed, total: event.total, sent: event.sent });
        } else summaries.push(event);
      });
      const summary = summaries.at(-1);
      if (!summary) {
        props.onError("The opening decision was saved, but email progress was interrupted.");
        return;
      }
      const message = choice.kind === "candidate"
        ? "Successful applicant selected." : "Opening decision recorded.";
      props.onSaved(await api.fetchOpenings(), decisionCompletionMessage(message, summary.sent, summary.total));
    } catch {
      props.onError(
        "The connection was interrupted. The decision may already be saved; review the opening before trying again.",
      );
    } finally {
      setProgress(null);
      setBusy(false);
    }
  }

  const [candidateFilter, setCandidateFilter] = useState("");
  const filterTerms = candidateFilter.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const filteredCandidates = props.selection.candidates.filter((candidate) => {
    const searchable = `${candidate.applicantName ?? ""} ${candidate.primaryEmail}`.toLocaleLowerCase();
    return filterTerms.every((term) => searchable.includes(term));
  });
  if (choice.kind === "no-household") {
    const count = props.selection.activeParticipantCount;
    return (
      <section className="opening-selection-panel">
        <h4>Confirm no household selected</h4>
        <p>
          No household will be selected for this opening. {count} {count === 1 ? "application" : "applications"} will be recorded as unsuccessful.
        </p>
        <p className="panel-hint">
          This decision is permanent. Eligible unsuccessful applicants will be emailed immediately.
        </p>
        {progress ? <DecisionProgressView progress={progress} /> : null}
        <div className="opening-form-actions">
          <button className="secondary-button" type="button" onClick={() => setChoice({ kind: "candidates" })} disabled={busy}>Back</button>
          <button className="primary-button" type="button" onClick={() => void confirm()} disabled={busy}>
            <UserX size={15} /> Confirm decision
          </button>
        </div>
      </section>
    );
  }
  if (choice.kind === "candidate") {
    const candidate = choice.candidate;
    const unsuccessfulCount = props.selection.activeParticipantCount - 1;
    return (
      <section className="opening-selection-panel">
        <h4>Confirm the successful applicant</h4>
        <p>
          <strong>{candidate.applicantName ?? candidate.primaryEmail}</strong>
          {" "}will be selected. {unsuccessfulCount} other {unsuccessfulCount === 1 ? "application" : "applications"} will be recorded as unsuccessful.
        </p>
        <p className="panel-hint">
          This selection is permanent. Eligible unsuccessful applicants will be emailed immediately.
        </p>
        {progress ? <DecisionProgressView progress={progress} /> : null}
        <div className="opening-form-actions">
          <button className="secondary-button" type="button" onClick={() => setChoice({ kind: "candidates" })} disabled={busy}>Back</button>
          <button className="primary-button" type="button" onClick={() => void confirm()} disabled={busy}>
            <UserCheck size={15} /> Confirm selection
          </button>
        </div>
      </section>
    );
  }
  return (
    <section className="opening-selection-panel">
      <div className="opening-form-heading">
        <div>
          <h4>Opening decision</h4>
          <span>Record the committee's decision for this opening.</span>
        </div>
        <button className="secondary-button" type="button" onClick={props.onClose}>Close</button>
      </div>
      <div>
        {props.selection.candidates.length === 0 ? (
          <p className="panel-hint">There are no available applicants to select.</p>
        ) : (
          <>
            {props.selection.candidates.length > 5 ? (
              <label className="opening-candidate-filter">
                <span>Filter candidates</span>
                <input
                  type="search"
                  value={candidateFilter}
                  onChange={(event) => setCandidateFilter(event.target.value)}
                  placeholder="Name or email"
                  autoComplete="off"
                  spellCheck={false}
                />
              </label>
            ) : null}
            {filteredCandidates.length === 0 ? (
              <p className="panel-hint opening-candidate-empty">No candidates match that filter.</p>
            ) : (
              <div className="opening-candidate-list">
                {filteredCandidates.map((candidate) => (
                  <div key={candidate.applicationId} className="opening-candidate-row">
                    <button className="opening-candidate-name" type="button" onClick={() => props.onReview(candidate.applicationId)}>
                      <strong>{candidate.applicantName ?? candidate.primaryEmail}</strong>
                      <span>{candidate.primaryEmail}</span>
                    </button>
                    <button className="secondary-button" type="button" onClick={() => setChoice({ kind: "candidate", candidate })}>
                      Select
                    </button>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
        <button className="opening-no-selection-button" type="button" onClick={() => setChoice({ kind: "no-household" })}>
          No household selected
        </button>
      </div>
    </section>
  );
}

function DecisionProgressView(props: { progress: DecisionProgress }): ReactNode {
  const { processed, total, sent } = props.progress;
  if (total === null) {
    return (
      <div className="opening-decision-progress" role="status">
        <strong>Preparing outcome emails…</strong>
        <progress aria-label="Preparing outcome emails" />
      </div>
    );
  }
  const percentage = total === 0 ? 100 : Math.round((processed / total) * 100);
  const detail = total === 0
    ? "No outcome emails are due yet."
    : `${sent} sent · ${processed} of ${total} processed (${percentage}%)`;
  return (
    <div className="opening-decision-progress" role="status" aria-live="polite">
      <div>
        <strong>Sending outcome emails</strong>
        <span>{detail}</span>
      </div>
      <progress
        aria-label="Outcome email progress"
        value={total === 0 ? 1 : processed}
        max={Math.max(total, 1)}
      />
    </div>
  );
}

function decisionCompletionMessage(prefix: string, sent: number, total: number): string {
  if (total === 0) return `${prefix} No outcome emails were due yet.`;
  if (sent === total) {
    return `${prefix} ${sent} outcome ${sent === 1 ? "email was" : "emails were"} sent.`;
  }
  const needsAttention = total - sent;
  const agreement = needsAttention === 1 ? "needs" : "need";
  return `${prefix} ${sent} of ${total} outcome emails were sent; ${needsAttention} ${agreement} attention in Email delivery.`;
}
