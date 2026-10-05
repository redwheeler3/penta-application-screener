import { useCommitteeApi } from "../../api/identity";
import { UserCheck, UserX } from "lucide-react";
import { type ReactNode, useState } from "react";

import * as openingsApi from "../../api/openings";
import { useRequestScope } from "../../hooks/useRequestScope";
import { readProblem } from "../../api/problems";
import type { Opening, OpeningCommit, OpeningSelection, OpeningSelectionCandidate } from "../../types";

type DecisionChoice =
  | { kind: "candidates" }
  | { kind: "candidate"; candidate: OpeningSelectionCandidate }
  | { kind: "no-household" };

/** Owns permanent decision confirmation and its outcome-email queue acknowledgement. */
export function OpeningDecisionPanel(props: {
  selection: OpeningSelection;
  onSaved: (openings: Opening[], message: string) => void;
  busy: boolean;
  setBusy: (busy: boolean) => void;
  onError: (message: string) => void;
  onReview: (applicationId: number) => void;
  onClose: () => void;
}): ReactNode {
  const api = useCommitteeApi(openingsApi);

  const [choice, setChoice] = useState<DecisionChoice>({ kind: "candidates" });
  const { busy, setBusy } = props;
  const requests = useRequestScope(props.selection.openingId);

  async function confirm(): Promise<void> {
    if (choice.kind === "candidates" || busy) return;
    setBusy(true);
    const isCurrent = requests.capture();
    try {
      const response = choice.kind === "candidate"
        ? await api.confirmOpeningSelection(props.selection.openingId, choice.candidate.applicationId)
        : await api.confirmNoHouseholdSelected(props.selection.openingId);
      if (!isCurrent()) return;
      if (!response.ok) {
        const problem = await readProblem(response);
        if (isCurrent()) props.onError(problem ?? "Could not save the opening decision.");
        return;
      }
      const saved = await response.json() as OpeningCommit;
      if (!isCurrent()) return;
      const prefix = choice.kind === "candidate" ? "Successful applicant selected." : "Opening decision recorded.";
      const message = saved.queuedNotificationCount > 0
        ? `${prefix} ${saved.queuedNotificationCount} outcome ${saved.queuedNotificationCount === 1 ? "email is" : "emails are"} queued. Check Email delivery for status.`
        : `${prefix} No new outcome emails were needed. Check Email delivery for existing deliveries.`;
      props.onSaved(saved.openings, message);
    } catch {
      if (isCurrent()) props.onError(
        "The connection was interrupted. The decision may already be saved; review the opening before trying again.",
      );
    } finally {
      if (isCurrent()) setBusy(false);
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
          This decision is permanent. Eligible outcome emails will be queued and sent in the background.
        </p>
        <div className="opening-form-actions">
          <button className="secondary-button" type="button" onClick={() => setChoice({ kind: "candidates" })} disabled={busy}>Back</button>
          <button className="primary-button" type="button" onClick={() => void confirm()} disabled={busy}>
            <UserX size={15} /> {busy ? "Saving decision…" : "Confirm decision"}
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
          This selection is permanent. Eligible outcome emails will be queued and sent in the background.
        </p>
        <div className="opening-form-actions">
          <button className="secondary-button" type="button" onClick={() => setChoice({ kind: "candidates" })} disabled={busy}>Back</button>
          <button className="primary-button" type="button" onClick={() => void confirm()} disabled={busy}>
            <UserCheck size={15} /> {busy ? "Saving decision…" : "Confirm selection"}
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
