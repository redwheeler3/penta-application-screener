import { Search, UserCheck } from "lucide-react";
import { type FormEvent, type ReactNode, useRef, useState } from "react";

import * as api from "../../api/openings";
import { readProblem } from "../../api/problems";
import type { Opening, OpeningSelectionCandidate } from "../../types";
import { useRequestScope } from "../../hooks/useRequestScope";
import { NumberInput } from "../shared/NumberInput";

type DirectDraft = {
  unitSizeBedrooms: number;
  housingChargeDollars: number;
  moveInDate: string;
};

const EMPTY_DRAFT: DirectDraft = {
  unitSizeBedrooms: 2,
  housingChargeDollars: 0,
  moveInDate: "",
};

export function DirectSelectionOpeningForm(props: {
  onCancel: () => void;
  onCreated: (openings: Opening[], applicant: OpeningSelectionCandidate) => void;
  onError: (message: string) => void;
  onReviewRetained: (applicationId: number) => void;
  onSavingChange?: (saving: boolean) => void;
}): ReactNode {
  const [draft, setDraft] = useState(EMPTY_DRAFT);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<OpeningSelectionCandidate[] | null>(null);
  const [selected, setSelected] = useState<OpeningSelectionCandidate | null>(null);
  const [searching, setSearching] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const searches = useRequestScope(query);
  const requests = useRequestScope();
  const pending = useRef(false);

  async function search(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const trimmed = query.trim();
    if (trimmed.length < 2 || searching) return;
    const isCurrent = searches.begin();
    setSearching(true);
    try {
      const candidates = await api.searchPreviousApplicants(trimmed);
      if (isCurrent()) setResults(candidates);
    } catch {
      if (isCurrent()) props.onError("Could not search previous applicants.");
    } finally {
      if (isCurrent()) setSearching(false);
    }
  }

  async function create(): Promise<void> {
    if (!selected || pending.current) return;
    const isCurrent = requests.capture();
    pending.current = true;
    setSaving(true);
    props.onSavingChange?.(true);
    try {
      const response = await api.createDirectSelectionOpening({
        unitSizeBedrooms: draft.unitSizeBedrooms,
        housingChargeCents: Math.round(draft.housingChargeDollars * 100),
        moveInDate: draft.moveInDate,
        applicationId: selected.applicationId,
      });
      if (!isCurrent()) return;
      if (!response.ok) {
        const problem = await readProblem(response);
        if (!isCurrent()) return;
        props.onError(problem ?? "Could not fill that opening.");
        setConfirming(false);
        return;
      }
      const payload = (await response.json()) as { openings: Opening[] };
      if (!isCurrent()) return;
      props.onCreated(payload.openings, selected);
    } catch {
      if (isCurrent()) {
        props.onError("Could not fill that opening.");
        setConfirming(false);
      }
    } finally {
      pending.current = false;
      if (isCurrent()) {
        setSaving(false);
        props.onSavingChange?.(false);
      }
    }
  }

  const set = (patch: Partial<DirectDraft>) => {
    setDraft((current) => ({ ...current, ...patch }));
    setConfirming(false);
  };

  return (
    <section className="opening-form direct-opening-form">
      <div className="opening-form-heading">
        <div>
          <h4>Fill from previous applicants</h4>
          <span>Use this after the applicant has confirmed they are interested.</span>
        </div>
      </div>

      <div className="opening-form-grid">
        <label>
          <span>Unit size</span>
          <select disabled={saving} value={draft.unitSizeBedrooms} onChange={(event) => set({ unitSizeBedrooms: Number(event.target.value) })}>
            <option value={1}>1 bedroom</option>
            <option value={2}>2 bedrooms</option>
            <option value={3}>3 bedrooms</option>
          </select>
        </label>
        <label>
          <span>Monthly housing charge</span>
          <div className="opening-money-input">
            <span>$</span>
            <NumberInput disabled={saving} min="0" step="0.01" required value={draft.housingChargeDollars} onChange={(value) => set({ housingChargeDollars: value ?? 0 })} />
          </div>
        </label>
        <label>
          <span>Move-in date</span>
          <input disabled={saving} type="date" required value={draft.moveInDate} onChange={(event) => set({ moveInDate: event.target.value })} />
        </label>
      </div>

      <form className="direct-applicant-search" onSubmit={(event) => void search(event)}>
        <label>
          <span>Previous applicant</span>
          <div>
            <input
              type="search"
              disabled={saving}
              value={query}
              onChange={(event) => {
                searches.invalidate();
                setQuery(event.target.value);
                setResults(null);
                setSearching(false);
              }}
              placeholder="Name or email"
              autoComplete="off"
              spellCheck={false}
              minLength={2}
              required
            />
            <button className="secondary-button" type="submit" disabled={saving || searching || query.trim().length < 2}>
              <Search size={15} /> {searching ? "Searching…" : "Search"}
            </button>
          </div>
        </label>
      </form>

      {results !== null ? (
        results.length === 0 ? (
          <p className="panel-hint">No previous applicants match that search.</p>
        ) : (
          <div className="opening-candidate-list direct-opening-results">
            {results.map((candidate) => (
              <div key={candidate.applicationId} className="opening-candidate-row">
                <button disabled={saving} className="opening-candidate-name" type="button" onClick={() => props.onReviewRetained(candidate.applicationId)}>
                  <strong>{candidate.applicantName ?? candidate.primaryEmail}</strong>
                  <span>{candidate.primaryEmail}</span>
                </button>
                <button
                  className={selected?.applicationId === candidate.applicationId ? "primary-button" : "secondary-button"}
                  type="button"
                  disabled={saving}
                  onClick={() => { setSelected(candidate); setConfirming(false); }}
                >
                  {selected?.applicationId === candidate.applicationId ? "Chosen" : "Choose"}
                </button>
              </div>
            ))}
          </div>
        )
      ) : null}

      {selected ? (
        <div className="direct-opening-selected">
          <UserCheck size={17} />
          <span>
            Selected applicant
            <strong>{selected.applicantName ?? selected.primaryEmail}</strong>
          </span>
        </div>
      ) : null}

      {confirming && selected ? (
        <div className="opening-launch-preview direct-opening-confirmation" role="alertdialog" aria-label="Confirm direct selection">
          <h5>Create this filled opening?</h5>
          <p>
            Selecting <strong>{selected.applicantName ?? selected.primaryEmail}</strong> removes them
            from the active pool and retains their application for seven years after this decision.
          </p>
          <p>No vacancy or applicant email will be sent.</p>
          <div className="opening-form-actions">
            <button className="secondary-button" type="button" onClick={() => setConfirming(false)} disabled={saving}>Back</button>
            <button className="primary-button" type="button" onClick={() => void create()} disabled={saving}>
              {saving ? "Saving…" : "Create opening and select applicant"}
            </button>
          </div>
        </div>
      ) : (
        <div className="opening-form-actions">
          <button className="secondary-button" type="button" onClick={props.onCancel} disabled={saving}>Cancel</button>
          <button
            className="primary-button"
            type="button"
            disabled={!selected || !draft.moveInDate || saving}
            onClick={() => setConfirming(true)}
          >
            Review direct selection
          </button>
        </div>
      )}
    </section>
  );
}
