import { CalendarDays, Eye, Pencil, Plus, RotateCcw, UserCheck, UserX } from "lucide-react";
import { type FormEvent, type ReactNode, useEffect, useState } from "react";

import * as api from "../api";
import { readProblem } from "../format";
import type {
  Opening,
  OpeningSelection,
  OpeningSelectionCandidate,
  OpeningWrite,
} from "../types";
import { NumberInput } from "./NumberInput";
import { RetryLoadError } from "./RetryLoadError";

type OpeningDraft = {
  unitSizeBedrooms: number;
  housingChargeDollars: number;
  applicationOpenDate: string;
  applicationCloseDate: string;
  moveInDate: string;
};

const EMPTY_DRAFT: OpeningDraft = {
  unitSizeBedrooms: 2,
  housingChargeDollars: 0,
  applicationOpenDate: "",
  applicationCloseDate: "",
  moveInDate: "",
};

export function OpeningsPanel(props: {
  onError: (message: string) => void;
  onPoolChanged: () => void;
  onOpenApplicant: (id: number) => void;
  onOpenRetainedApplicant: (id: number) => void;
}): ReactNode {
  const [openings, setOpenings] = useState<Opening[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [loadVersion, setLoadVersion] = useState(0);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draft, setDraft] = useState<OpeningDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [selection, setSelection] = useState<OpeningSelection | null>(null);
  const [pendingCandidate, setPendingCandidate] = useState<OpeningSelectionCandidate | null>(null);
  const [confirmingNoHousehold, setConfirmingNoHousehold] = useState(false);
  const [confirmingUndo, setConfirmingUndo] = useState(false);

  useEffect(() => {
    let live = true;
    setLoadError(false);
    api.fetchOpenings().then((items) => {
      if (live) setOpenings(items);
    }).catch(() => {
      if (!live) return;
      setLoadError(true);
      props.onError("Could not load openings.");
    });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadVersion]);

  function beginCreate(): void {
    setEditingId(null);
    setDraft({ ...EMPTY_DRAFT });
    setMessage("");
    setSelection(null);
  }

  function beginEdit(opening: Opening): void {
    setEditingId(opening.id);
    setDraft({
      unitSizeBedrooms: opening.unitSizeBedrooms,
      housingChargeDollars: opening.housingChargeCents / 100,
      applicationOpenDate: opening.applicationOpenDate,
      applicationCloseDate: opening.applicationCloseDate,
      moveInDate: opening.moveInDate,
    });
    setMessage("");
    setSelection(null);
  }

  async function save(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!draft || busy) return;
    const payload: OpeningWrite = {
      unitSizeBedrooms: draft.unitSizeBedrooms,
      housingChargeCents: Math.round(draft.housingChargeDollars * 100),
      applicationOpenDate: draft.applicationOpenDate,
      applicationCloseDate: draft.applicationCloseDate,
      moveInDate: draft.moveInDate,
    };
    const response = await mutate(
      editingId === null
        ? api.createOpening(payload)
        : api.updateOpening(editingId, payload),
    );
    if (!response) return;
    setOpenings(response);
    setDraft(null);
    setEditingId(null);
    setMessage(editingId === null ? "Draft opening created." : "Opening updated.");
  }

  async function publish(opening: Opening): Promise<void> {
    const response = await mutate(api.publishOpening(opening.id));
    if (!response) return;
    setOpenings(response);
    setMessage("Opening published.");
  }

  async function manageSelection(opening: Opening): Promise<void> {
    setBusy(true);
    setMessage("");
    setPendingCandidate(null);
    setConfirmingNoHousehold(false);
    setConfirmingUndo(false);
    try {
      setSelection(await api.fetchOpeningSelection(opening.id));
    } catch {
      props.onError("Could not load the opening selection.");
    } finally {
      setBusy(false);
    }
  }

  async function confirmSelection(): Promise<void> {
    if (!selection || !pendingCandidate || busy) return;
    setBusy(true);
    try {
      const response = await api.confirmOpeningSelection(
        selection.openingId,
        pendingCandidate.applicationId,
      );
      if (!response.ok) {
        props.onError((await readProblem(response)) ?? "Could not save the selection.");
        return;
      }
      setSelection((await response.json()) as OpeningSelection);
      setPendingCandidate(null);
      setOpenings(await api.fetchOpenings());
      setMessage("Successful applicant selected.");
      props.onPoolChanged();
    } finally {
      setBusy(false);
    }
  }

  async function confirmNoHousehold(): Promise<void> {
    if (!selection || busy) return;
    setBusy(true);
    try {
      const response = await api.confirmNoHouseholdSelected(selection.openingId);
      if (!response.ok) {
        props.onError((await readProblem(response)) ?? "Could not save the decision.");
        return;
      }
      setSelection((await response.json()) as OpeningSelection);
      setConfirmingNoHousehold(false);
      setOpenings(await api.fetchOpenings());
      setMessage("Opening decision recorded.");
      props.onPoolChanged();
    } finally {
      setBusy(false);
    }
  }

  async function undoSelection(): Promise<void> {
    if (!selection || busy) return;
    setBusy(true);
    try {
      const response = await api.undoOpeningSelection(selection.openingId);
      if (!response.ok) {
        props.onError((await readProblem(response)) ?? "Could not undo the selection.");
        return;
      }
      setSelection((await response.json()) as OpeningSelection);
      setConfirmingUndo(false);
      setOpenings(await api.fetchOpenings());
      setMessage("Selection undone.");
      props.onPoolChanged();
    } finally {
      setBusy(false);
    }
  }

  async function mutate(request: Promise<Response>): Promise<Opening[] | null> {
    setBusy(true);
    setMessage("");
    try {
      const response = await request;
      if (!response.ok) {
        props.onError((await readProblem(response)) ?? "Could not update that opening.");
        return null;
      }
      return ((await response.json()) as { openings: Opening[] }).openings;
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="settings-panel-body openings-panel">
      <div className="settings-subtab-head openings-header">
        <div>
          <h3>Openings</h3>
          <p className="panel-hint">
            Configure unit offerings and publish them when they are ready. Availability follows
            the three dates; publishing never sends email.
          </p>
        </div>
        {!draft ? (
          <button className="primary-button" type="button" onClick={beginCreate}>
            <Plus size={16} /> New opening
          </button>
        ) : null}
      </div>

      {draft ? (
        <OpeningForm
          draft={draft}
          editing={editingId !== null}
          busy={busy}
          onChange={setDraft}
          onCancel={() => { setDraft(null); setEditingId(null); }}
          onSubmit={save}
        />
      ) : null}

      {selection ? (
        <OpeningSelectionPanel
          selection={selection}
          pendingCandidate={pendingCandidate}
          confirmingNoHousehold={confirmingNoHousehold}
          confirmingUndo={confirmingUndo}
          busy={busy}
          onChoose={setPendingCandidate}
          onRequestNoHousehold={() => setConfirmingNoHousehold(true)}
          onCancelNoHousehold={() => setConfirmingNoHousehold(false)}
          onConfirmNoHousehold={() => void confirmNoHousehold()}
          onBack={() => setPendingCandidate(null)}
          onConfirm={() => void confirmSelection()}
          onReview={props.onOpenApplicant}
          onReviewSelected={props.onOpenRetainedApplicant}
          onRequestUndo={() => setConfirmingUndo(true)}
          onCancelUndo={() => setConfirmingUndo(false)}
          onUndo={() => void undoSelection()}
          onClose={() => {
            setSelection(null);
            setPendingCandidate(null);
            setConfirmingNoHousehold(false);
            setConfirmingUndo(false);
          }}
        />
      ) : null}

      {message ? <p className="opening-message" role="status">{message}</p> : null}
      {loadError ? (
        <RetryLoadError
          message="Couldn't load openings."
          onRetry={() => setLoadVersion((version) => version + 1)}
        />
      ) : openings === null ? (
        <p className="panel-hint">Loading…</p>
      ) : openings.length === 0 ? (
        <div className="openings-empty">
          <CalendarDays size={28} />
          <strong>No openings configured</strong>
          <span>Create a draft offering before opening applications.</span>
        </div>
      ) : (
        <div className="opening-list">
          {openings.map((opening) => (
            <OpeningCard
              key={opening.id}
              opening={opening}
              busy={busy}
              onEdit={() => beginEdit(opening)}
              onPublish={() => void publish(opening)}
              onManageSelection={() => void manageSelection(opening)}
              onReviewSelected={() => {
                if (opening.selectedApplicationId !== null) {
                  props.onOpenRetainedApplicant(opening.selectedApplicationId);
                }
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function OpeningForm(props: {
  draft: OpeningDraft;
  editing: boolean;
  busy: boolean;
  onChange: (draft: OpeningDraft) => void;
  onCancel: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}): ReactNode {
  const set = (patch: Partial<OpeningDraft>) => props.onChange({ ...props.draft, ...patch });
  return (
    <form className="opening-form" onSubmit={props.onSubmit}>
      <div className="opening-form-heading">
        <h4>{props.editing ? "Edit opening" : "New draft opening"}</h4>
        <span>Applicants cannot see or submit to a draft.</span>
      </div>
      <div className="opening-form-grid">
        <label>
          <span>Unit size</span>
          <select value={props.draft.unitSizeBedrooms} onChange={(event) => set({ unitSizeBedrooms: Number(event.target.value) })}>
            <option value={1}>1 bedroom</option>
            <option value={2}>2 bedrooms</option>
            <option value={3}>3 bedrooms</option>
          </select>
        </label>
        <label>
          <span>Monthly housing charge</span>
          <div className="opening-money-input">
            <span>$</span>
            <NumberInput min="0" step="0.01" required value={props.draft.housingChargeDollars} onChange={(value) => set({ housingChargeDollars: value ?? 0 })} />
          </div>
        </label>
        <label>
          <span>Applications open</span>
          <input type="date" required value={props.draft.applicationOpenDate} onChange={(event) => set({ applicationOpenDate: event.target.value })} />
        </label>
        <label>
          <span>Applications close</span>
          <input type="date" required value={props.draft.applicationCloseDate} onChange={(event) => set({ applicationCloseDate: event.target.value })} />
        </label>
        <label>
          <span>Move-in date</span>
          <input type="date" required value={props.draft.moveInDate} onChange={(event) => set({ moveInDate: event.target.value })} />
        </label>
      </div>
      <div className="opening-form-actions">
        <button className="secondary-button" type="button" onClick={props.onCancel} disabled={props.busy}>Cancel</button>
        <button className="primary-button" type="submit" disabled={props.busy}>
          {props.busy ? "Saving…" : props.editing ? "Save changes" : "Create draft"}
        </button>
      </div>
    </form>
  );
}

function OpeningCard(props: {
  opening: Opening;
  busy: boolean;
  onEdit: () => void;
  onPublish: () => void;
  onManageSelection: () => void;
  onReviewSelected: () => void;
}): ReactNode {
  const { opening } = props;
  return (
    <article className="opening-card">
      <div className="opening-card-main">
        <div className="opening-card-title">
          <span className={`opening-status opening-status-${opening.phase}`}>{opening.phase}</span>
          <h4>{opening.unitSizeBedrooms}-bedroom opening</h4>
        </div>
        <dl className="opening-facts">
          <div><dt>Unit</dt><dd>{opening.unitSizeBedrooms} bedroom{opening.unitSizeBedrooms === 1 ? "" : "s"}</dd></div>
          <div><dt>Housing charge</dt><dd>{formatHousingCharge(opening.housingChargeCents)}</dd></div>
          <div><dt>Opens</dt><dd>{formatDateOnly(opening.applicationOpenDate)}</dd></div>
          <div><dt>Closes</dt><dd>{formatDateOnly(opening.applicationCloseDate)}</dd></div>
          <div><dt>Move-in</dt><dd>{formatDateOnly(opening.moveInDate)}</dd></div>
          <div><dt>Submissions</dt><dd>{opening.submissionCount}</dd></div>
        </dl>
        {opening.selectedApplicationId !== null ? (
          <div className="opening-selection-summary">
            <UserCheck size={17} />
            <span>
              Selected applicant
              <strong>{opening.selectedApplicantName ?? "Application selected"}</strong>
            </span>
            {opening.decisionPermanent ? <small>Permanent</small> : <small>Can be undone until move-in</small>}
          </div>
        ) : opening.noHouseholdSelected ? (
          <div className="opening-selection-summary opening-no-selection-summary">
            <UserX size={17} />
            <span>
              Opening decision
              <strong>No household selected</strong>
            </span>
            {opening.decisionPermanent ? <small>Permanent</small> : <small>Can be undone until move-in</small>}
          </div>
        ) : opening.needsDecision ? (
          <p className="opening-selection-needed">An opening decision is required.</p>
        ) : null}
      </div>
      <div className="opening-card-actions">
        <button className="secondary-button" type="button" onClick={props.onEdit} disabled={props.busy}>
          <Pencil size={15} /> Edit
        </button>
        {opening.phase === "draft" ? (
          <button className="primary-button" type="button" onClick={props.onPublish} disabled={props.busy}>
            Publish opening
          </button>
        ) : null}
        {opening.selectedApplicationId !== null ? (
          <button className="secondary-button" type="button" onClick={props.onReviewSelected} disabled={props.busy}>
            <Eye size={15} /> Review application
          </button>
        ) : null}
        {opening.phase === "closed" || opening.phase === "archived" ? (
          <button className={opening.needsDecision ? "primary-button" : "secondary-button"} type="button" onClick={props.onManageSelection} disabled={props.busy}>
            <UserCheck size={15} /> {opening.selectedApplicationId === null && !opening.noHouseholdSelected ? "Record decision" : "Manage decision"}
          </button>
        ) : null}
      </div>
    </article>
  );
}

function OpeningSelectionPanel(props: {
  selection: OpeningSelection;
  pendingCandidate: OpeningSelectionCandidate | null;
  confirmingNoHousehold: boolean;
  confirmingUndo: boolean;
  busy: boolean;
  onChoose: (candidate: OpeningSelectionCandidate) => void;
  onRequestNoHousehold: () => void;
  onCancelNoHousehold: () => void;
  onConfirmNoHousehold: () => void;
  onBack: () => void;
  onConfirm: () => void;
  onReview: (id: number) => void;
  onReviewSelected: (id: number) => void;
  onRequestUndo: () => void;
  onCancelUndo: () => void;
  onUndo: () => void;
  onClose: () => void;
}): ReactNode {
  const selected = props.selection.selectedApplicationId;
  if (props.confirmingUndo && (selected !== null || props.selection.noHouseholdSelected)) {
    return (
      <section className="opening-selection-panel">
        <h4>Undo this selection?</h4>
        <p>
          {selected !== null
            ? `${props.selection.selectedApplicantName ?? "The selected applicant"} will return to the committee workflow.`
            : "The opening will return to awaiting a decision."}
          {" "}No unsuccessful emails have been sent while this opening is closed.
        </p>
        <div className="opening-form-actions">
          <button className="secondary-button" type="button" onClick={props.onCancelUndo} disabled={props.busy}>Keep selection</button>
          <button className="danger-button" type="button" onClick={props.onUndo} disabled={props.busy}>
            <RotateCcw size={15} /> Undo selection
          </button>
        </div>
      </section>
    );
  }
  if (props.confirmingNoHousehold) {
    const count = props.selection.activeParticipantCount;
    return (
      <section className="opening-selection-panel">
        <h4>Confirm no household selected</h4>
        <p>
          No household will be selected for this opening. {count} {count === 1 ? "application" : "applications"} will be recorded as unsuccessful.
        </p>
        <p className="panel-hint">
          {props.selection.phase === "closed"
            ? "No unsuccessful email will be sent until the opening becomes archived. You can undo this decision before then."
            : "This archived decision is permanent. Eligible unsuccessful applicants will now be notified."}
        </p>
        <div className="opening-form-actions">
          <button className="secondary-button" type="button" onClick={props.onCancelNoHousehold} disabled={props.busy}>Back</button>
          <button className="primary-button" type="button" onClick={props.onConfirmNoHousehold} disabled={props.busy}>
            <UserX size={15} /> Confirm decision
          </button>
        </div>
      </section>
    );
  }
  if (props.pendingCandidate) {
    const unsuccessfulCount = props.selection.activeParticipantCount - 1;
    return (
      <section className="opening-selection-panel">
        <h4>Confirm the successful applicant</h4>
        <p>
          <strong>{props.pendingCandidate.applicantName ?? props.pendingCandidate.primaryEmail}</strong>
          {" "}will be selected. {unsuccessfulCount} other {unsuccessfulCount === 1 ? "application" : "applications"} will be recorded as unsuccessful.
        </p>
        <p className="panel-hint">
          {props.selection.phase === "closed"
            ? "No unsuccessful email will be sent until the opening becomes archived. You can undo this selection before then."
            : "This archived selection is permanent. Eligible unsuccessful applicants will now be notified."}
        </p>
        <div className="opening-form-actions">
          <button className="secondary-button" type="button" onClick={props.onBack} disabled={props.busy}>Back</button>
          <button className="primary-button" type="button" onClick={props.onConfirm} disabled={props.busy}>
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
      {selected !== null ? (
        <div className="opening-selected-detail">
          <div>
            <strong>{props.selection.selectedApplicantName ?? "Selected application"}</strong>
            <span>{props.selection.decisionPermanent ? "Permanent archived selection" : "Confirmed for this closed opening"}</span>
          </div>
          <button className="secondary-button" type="button" onClick={() => props.onReviewSelected(selected)}>
            <Eye size={15} /> Review application
          </button>
          {!props.selection.decisionPermanent ? (
            <button className="text-danger-button" type="button" onClick={props.onRequestUndo}>Undo selection</button>
          ) : null}
        </div>
      ) : props.selection.noHouseholdSelected ? (
        <div className="opening-selected-detail">
          <div>
            <strong>No household selected</strong>
            <span>{props.selection.decisionPermanent ? "Permanent archived decision" : "Confirmed for this closed opening"}</span>
          </div>
          {!props.selection.decisionPermanent ? (
            <button className="text-danger-button" type="button" onClick={props.onRequestUndo}>Undo decision</button>
          ) : null}
        </div>
      ) : (
        <div>
          {props.selection.candidates.length === 0 ? (
            <p className="panel-hint">There are no available applicants to select.</p>
          ) : (
            <div className="opening-candidate-list">
              {props.selection.candidates.map((candidate) => (
                <div key={candidate.applicationId} className="opening-candidate-row">
                  <button className="opening-candidate-name" type="button" onClick={() => props.onReview(candidate.applicationId)}>
                    <strong>{candidate.applicantName ?? candidate.primaryEmail}</strong>
                    <span>{candidate.primaryEmail}</span>
                  </button>
                  <button className="secondary-button" type="button" onClick={() => props.onChoose(candidate)}>
                    Select
                  </button>
                </div>
              ))}
            </div>
          )}
          <button className="opening-no-selection-button" type="button" onClick={props.onRequestNoHousehold}>
            No household selected
          </button>
        </div>
      )}
    </section>
  );
}

function formatDateOnly(value: string): string {
  return new Intl.DateTimeFormat("en-CA", { dateStyle: "medium", timeZone: "UTC" })
    .format(new Date(`${value}T12:00:00Z`));
}

function formatHousingCharge(cents: number): string {
  return (cents / 100).toLocaleString("en-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: cents % 100 === 0 ? 0 : 2,
  });
}
