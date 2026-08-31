import { CalendarDays, Eye, Pencil, Plus, RotateCcw, UserCheck, UserX } from "lucide-react";
import { type FormEvent, type ReactNode, useEffect, useState } from "react";

import * as api from "../../api/openings";
import { readProblem } from "../../api/problems";
import type {
  Opening,
  OpeningCreate,
  OpeningCreated,
  OpeningPreview,
  OpeningSelection,
  OpeningSelectionCandidate,
  OpeningWrite,
} from "../../types";
import { NumberInput } from "../shared/NumberInput";
import { RetryLoadError } from "../shared/RetryLoadError";
import { DirectSelectionOpeningForm } from "./DirectSelectionOpeningForm";

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
  onOpenApplicant: (id: number, openingId: number) => void;
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
  const [launchPreview, setLaunchPreview] = useState<OpeningPreview | null>(null);
  const [fillingDirectly, setFillingDirectly] = useState(false);

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
    setLaunchPreview(null);
    setFillingDirectly(false);
  }

  function beginDirectSelection(): void {
    setDraft(null);
    setEditingId(null);
    setSelection(null);
    setMessage("");
    setFillingDirectly(true);
  }

  function beginEdit(opening: Opening): void {
    if (
      opening.intakeMode !== "applications"
      || opening.applicationOpenDate === null
      || opening.applicationCloseDate === null
    ) return;
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
    setLaunchPreview(null);
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
    if (editingId === null && launchPreview === null) {
      setBusy(true);
      try {
        setLaunchPreview(await api.previewOpening(createPayload(payload)));
      } catch {
        props.onError("Could not preview the opening and notification audience.");
      } finally {
        setBusy(false);
      }
      return;
    }
    if (editingId === null && launchPreview !== null) {
      setBusy(true);
      try {
        const createResponse = await api.createOpening(
          createPayload(payload),
          launchPreview.audienceCount,
        );
        if (!createResponse.ok) {
          const problem = await readProblem(createResponse);
          if (createResponse.status === 409) setLaunchPreview(null);
          props.onError(problem ?? "Could not create that opening.");
          return;
        }
        const created = (await createResponse.json()) as OpeningCreated;
        setOpenings(created.openings);
        setDraft(null);
        setLaunchPreview(null);
        setMessage(
          `Applications are open and ${created.queuedNotificationCount} ${created.queuedNotificationCount === 1 ? "email is" : "emails are"} queued.`,
        );
        return;
      } finally {
        setBusy(false);
      }
    }
    const response = await mutate(api.updateOpening(editingId as number, payload));
    if (!response) return;
    setOpenings(response);
    setDraft(null);
    setEditingId(null);
    setMessage("Opening updated.");
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
      if (selection.intakeMode === "direct_selection") {
        const response = await api.removeDirectSelectionOpening(selection.openingId);
        if (!response.ok) {
          props.onError((await readProblem(response)) ?? "Could not remove that opening.");
          return;
        }
        setOpenings(((await response.json()) as { openings: Opening[] }).openings);
        setSelection(null);
        setConfirmingUndo(false);
        setMessage("Directly filled opening removed.");
        props.onPoolChanged();
        return;
      }
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
            Open applications and notify the matching audience, or fill a home from previous
            applicants.
          </p>
        </div>
        {!draft && !fillingDirectly ? (
          <div className="opening-header-actions">
            <button className="secondary-button" type="button" onClick={beginDirectSelection}>
              <UserCheck size={16} /> Fill from previous applicants
            </button>
            <button className="primary-button" type="button" onClick={beginCreate}>
              <Plus size={16} /> New opening
            </button>
          </div>
        ) : null}
      </div>

      {fillingDirectly ? (
        <DirectSelectionOpeningForm
          onCancel={() => setFillingDirectly(false)}
          onCreated={(items, applicant) => {
            setOpenings(items);
            setFillingDirectly(false);
            setMessage(`${applicant.applicantName ?? applicant.primaryEmail} selected for the new opening.`);
            props.onPoolChanged();
          }}
          onError={props.onError}
          onReviewRetained={props.onOpenRetainedApplicant}
        />
      ) : null}

      {draft ? (
        <OpeningForm
          draft={draft}
          editing={editingId !== null}
          busy={busy}
          onChange={(next) => { setDraft(next); setLaunchPreview(null); }}
          onCancel={() => { setDraft(null); setEditingId(null); setLaunchPreview(null); }}
          onSubmit={save}
          launchPreview={launchPreview}
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
          onReview={(applicationId) =>
            props.onOpenApplicant(applicationId, selection.openingId)
          }
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
          <span>Create an opening when a home becomes available.</span>
        </div>
      ) : (
        <div className="opening-list">
          {openings.map((opening) => (
            <OpeningCard
              key={opening.id}
              opening={opening}
              busy={busy}
              onEdit={() => beginEdit(opening)}
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
  launchPreview: OpeningPreview | null;
}): ReactNode {
  const set = (patch: Partial<OpeningDraft>) => props.onChange({ ...props.draft, ...patch });
  return (
    <form className="opening-form" onSubmit={props.onSubmit}>
      <div className="opening-form-heading">
        <h4>{props.editing ? "Edit opening" : "New opening"}</h4>
        <span>{props.editing ? "Update the opening details." : "Applications open as soon as you confirm."}</span>
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
        {props.editing ? (
          <label>
            <span>Applications opened</span>
            <input type="date" value={props.draft.applicationOpenDate} readOnly />
          </label>
        ) : null}
        <label>
          <span>Applications close</span>
          <input type="date" required value={props.draft.applicationCloseDate} onChange={(event) => set({ applicationCloseDate: event.target.value })} />
        </label>
        <label>
          <span>Move-in date</span>
          <input type="date" required value={props.draft.moveInDate} onChange={(event) => set({ moveInDate: event.target.value })} />
        </label>
      </div>
      {!props.editing && props.launchPreview ? (
        <OpeningLaunchPreview preview={props.launchPreview} />
      ) : null}
      <div className="opening-form-actions">
        <button className="secondary-button" type="button" onClick={props.onCancel} disabled={props.busy}>Cancel</button>
        <button className="primary-button" type="submit" disabled={props.busy}>
          {props.busy
            ? "Working…"
            : props.editing
              ? "Save changes"
              : props.launchPreview
                ? `Open applications and queue ${props.launchPreview.audienceCount} ${props.launchPreview.audienceCount === 1 ? "email" : "emails"}`
                : "Review opening and emails"}
        </button>
      </div>
    </form>
  );
}

function OpeningLaunchPreview({ preview }: { preview: OpeningPreview }): ReactNode {
  const usage = preview.socketlabs;
  const variantLabels: Record<string, string> = {
    notification_list: "Notification list email",
    current_application: "Current application email",
    application_and_notification_list: "Combined application and notification-list email",
  };
  return (
    <section className="opening-launch-preview" aria-label="Opening and email confirmation">
      <h5>Ready to open applications</h5>
      <p>
        <strong>{preview.audienceCount}</strong> {preview.audienceCount === 1 ? "person" : "people"}
        {" "}will receive an email.
      </p>
      <dl className="opening-preview-variants">
        {preview.variants.map((variant) => (
          <div key={variant.kind}>
            <dt>{variantLabels[variant.kind] ?? variant.kind}</dt>
            <dd>{variant.recipientCount}</dd>
          </div>
        ))}
      </dl>
      {usage.available ? (
        <p className="opening-quota-summary">
          SocketLabs usage will move from <strong>{usage.messagesUsed?.toLocaleString()}</strong> to{" "}
          <strong>{usage.projectedMessagesUsed?.toLocaleString()}</strong> of{" "}
          <strong>{usage.messageAllowance?.toLocaleString()}</strong> messages this billing period.
          {usage.allowOverages === false && usage.projectedMessagesUsed !== null && usage.messageAllowance !== null
            && usage.projectedMessagesUsed > usage.messageAllowance
            ? " Messages beyond the allowance will remain queued until SocketLabs accepts them."
            : ""}
        </p>
      ) : (
        <p className="opening-quota-summary">
          Current SocketLabs usage is unavailable. Emails will be queued and retried automatically
          if needed.
        </p>
      )}
    </section>
  );
}

function createPayload(payload: OpeningWrite): OpeningCreate {
  return {
    unitSizeBedrooms: payload.unitSizeBedrooms,
    housingChargeCents: payload.housingChargeCents,
    applicationCloseDate: payload.applicationCloseDate,
    moveInDate: payload.moveInDate,
  };
}

function OpeningCard(props: {
  opening: Opening;
  busy: boolean;
  onEdit: () => void;
  onManageSelection: () => void;
  onReviewSelected: () => void;
}): ReactNode {
  const { opening } = props;
  return (
    <article className="opening-card">
      <div className="opening-card-main">
        <div className="opening-card-title">
          <span className={`opening-status opening-status-${opening.phase}`}>
            {opening.intakeMode === "direct_selection" ? "filled directly" : opening.phase}
          </span>
          <h4>{opening.unitSizeBedrooms}-bedroom opening</h4>
        </div>
        <dl className="opening-facts">
          <div><dt>Unit</dt><dd>{opening.unitSizeBedrooms} bedroom{opening.unitSizeBedrooms === 1 ? "" : "s"}</dd></div>
          <div><dt>Housing charge</dt><dd>{formatHousingCharge(opening.housingChargeCents)}</dd></div>
          {opening.intakeMode === "applications" && opening.applicationOpenDate && opening.applicationCloseDate ? (
            <>
              <div><dt>Opens</dt><dd>{formatDateOnly(opening.applicationOpenDate)}</dd></div>
              <div><dt>Closes</dt><dd>{formatDateOnly(opening.applicationCloseDate)}</dd></div>
            </>
          ) : (
            <div><dt>Applications</dt><dd>Not opened</dd></div>
          )}
          <div><dt>Move-in</dt><dd>{formatDateOnly(opening.moveInDate)}</dd></div>
          {opening.intakeMode === "applications" ? (
            <div><dt>Submissions</dt><dd>{opening.submissionCount}</dd></div>
          ) : null}
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
        {opening.intakeMode === "applications" ? (
          <button className="secondary-button" type="button" onClick={props.onEdit} disabled={props.busy}>
            <Pencil size={15} /> Edit
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
  const [candidateFilter, setCandidateFilter] = useState("");
  const selected = props.selection.selectedApplicationId;
  const filterTerms = candidateFilter.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const filteredCandidates = props.selection.candidates.filter((candidate) => {
    const searchable = `${candidate.applicantName ?? ""} ${candidate.primaryEmail}`.toLocaleLowerCase();
    return filterTerms.every((term) => searchable.includes(term));
  });
  if (props.confirmingUndo && (selected !== null || props.selection.noHouseholdSelected)) {
    const directSelection = props.selection.intakeMode === "direct_selection";
    return (
      <section className="opening-selection-panel">
        <h4>{directSelection ? "Remove this filled opening?" : "Undo this selection?"}</h4>
        <p>
          {directSelection
            ? `${props.selection.selectedApplicantName ?? "The selected applicant"} will return to their previous retention and application scope.`
            : selected !== null
            ? `${props.selection.selectedApplicantName ?? "The selected applicant"} will return to the committee workflow.`
            : "The opening will return to awaiting a decision."}
          {" "}{directSelection ? "The opening and its direct participation will be removed." : "No unsuccessful emails have been sent while this opening is closed."}
        </p>
        <div className="opening-form-actions">
          <button className="secondary-button" type="button" onClick={props.onCancelUndo} disabled={props.busy}>
            {directSelection ? "Keep opening" : "Keep selection"}
          </button>
          <button className="danger-button" type="button" onClick={props.onUndo} disabled={props.busy}>
            <RotateCcw size={15} /> {directSelection ? "Remove opening" : "Undo selection"}
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
            ? "Unsuccessful applicants will not be emailed until the move-in date. You can undo this decision before then."
            : "This decision is permanent. Eligible unsuccessful applicants will be emailed now."}
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
            ? "Unsuccessful applicants will not be emailed until the move-in date. You can undo this selection before then."
            : "This selection is permanent. Eligible unsuccessful applicants will be emailed now."}
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
            <span>
              {props.selection.decisionPermanent
                ? "Permanent archived selection"
                : props.selection.intakeMode === "direct_selection"
                  ? "Filled from previous applicants"
                  : "Confirmed for this closed opening"}
            </span>
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
                      <button className="secondary-button" type="button" onClick={() => props.onChoose(candidate)}>
                        Select
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </>
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
