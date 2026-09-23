import { CalendarDays, Eye, Pencil, Plus, UserCheck, UserX } from "lucide-react";
import { type FormEvent, type ReactNode, useEffect, useState } from "react";

import * as api from "../../api/openings";
import { readProblem } from "../../api/problems";
import { formatDateOnly, formatHousingCharge } from "../../format";
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

type OpeningPanelMode =
  | { kind: "list" }
  | {
      kind: "form";
      editingId: number | null;
      draft: OpeningDraft;
      launchPreview: OpeningPreview | null;
    }
  | { kind: "direct" }
  | {
      kind: "selection";
      selection: OpeningSelection;
      pendingCandidate: OpeningSelectionCandidate | null;
      confirmingNoHousehold: boolean;
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
  const [mode, setMode] = useState<OpeningPanelMode>({ kind: "list" });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

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
    setMode({
      kind: "form",
      editingId: null,
      draft: { ...EMPTY_DRAFT },
      launchPreview: null,
    });
    setMessage("");
  }

  function beginDirectSelection(): void {
    setMode({ kind: "direct" });
    setMessage("");
  }

  function beginEdit(opening: Opening): void {
    if (
      opening.intakeMode !== "applications"
      || opening.applicationOpenDate === null
      || opening.applicationCloseDate === null
    ) return;
    setMode({
      kind: "form",
      editingId: opening.id,
      draft: {
        unitSizeBedrooms: opening.unitSizeBedrooms,
        housingChargeDollars: opening.housingChargeCents / 100,
        applicationOpenDate: opening.applicationOpenDate,
        applicationCloseDate: opening.applicationCloseDate,
        moveInDate: opening.moveInDate,
      },
      launchPreview: null,
    });
    setMessage("");
  }

  async function save(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (mode.kind !== "form" || busy) return;
    const payload: OpeningWrite = {
      unitSizeBedrooms: mode.draft.unitSizeBedrooms,
      housingChargeCents: Math.round(mode.draft.housingChargeDollars * 100),
      applicationOpenDate: mode.draft.applicationOpenDate,
      applicationCloseDate: mode.draft.applicationCloseDate,
      moveInDate: mode.draft.moveInDate,
    };
    if (mode.editingId === null && mode.launchPreview === null) {
      setBusy(true);
      try {
        setMode({ ...mode, launchPreview: await api.previewOpening(createPayload(payload)) });
      } catch {
        props.onError("Could not preview the opening and notification audience.");
      } finally {
        setBusy(false);
      }
      return;
    }
    if (mode.editingId === null && mode.launchPreview !== null) {
      setBusy(true);
      try {
        const createResponse = await api.createOpening(
          createPayload(payload),
          mode.launchPreview.audienceCount,
        );
        if (!createResponse.ok) {
          const problem = await readProblem(createResponse);
          if (createResponse.status === 409) setMode({ ...mode, launchPreview: null });
          props.onError(problem ?? "Could not create that opening.");
          return;
        }
        const created = (await createResponse.json()) as OpeningCreated;
        setOpenings(created.openings);
        setMode({ kind: "list" });
        setMessage(
          `Applications are open and ${created.queuedNotificationCount} ${created.queuedNotificationCount === 1 ? "email is" : "emails are"} queued.`,
        );
        return;
      } finally {
        setBusy(false);
      }
    }
    if (mode.editingId === null) return;
    const response = await mutate(api.updateOpening(mode.editingId, payload));
    if (!response) return;
    setOpenings(response);
    setMode({ kind: "list" });
    setMessage("Opening updated.");
  }

  async function manageSelection(opening: Opening): Promise<void> {
    setBusy(true);
    setMessage("");
    try {
      setMode({
        kind: "selection",
        selection: await api.fetchOpeningSelection(opening.id),
        pendingCandidate: null,
        confirmingNoHousehold: false,
      });
    } catch {
      props.onError("Could not load the opening selection.");
    } finally {
      setBusy(false);
    }
  }

  async function confirmSelection(): Promise<void> {
    if (mode.kind !== "selection" || !mode.pendingCandidate || busy) return;
    setBusy(true);
    try {
      const response = await api.confirmOpeningSelection(
        mode.selection.openingId,
        mode.pendingCandidate.applicationId,
      );
      if (!response.ok) {
        props.onError((await readProblem(response)) ?? "Could not save the selection.");
        return;
      }
      setMode({
        ...mode,
        selection: (await response.json()) as OpeningSelection,
        pendingCandidate: null,
      });
      setOpenings(await api.fetchOpenings());
      setMessage("Successful applicant selected.");
      props.onPoolChanged();
    } finally {
      setBusy(false);
    }
  }

  async function confirmNoHousehold(): Promise<void> {
    if (mode.kind !== "selection" || busy) return;
    setBusy(true);
    try {
      const response = await api.confirmNoHouseholdSelected(mode.selection.openingId);
      if (!response.ok) {
        props.onError((await readProblem(response)) ?? "Could not save the decision.");
        return;
      }
      setMode({
        ...mode,
        selection: (await response.json()) as OpeningSelection,
        confirmingNoHousehold: false,
      });
      setOpenings(await api.fetchOpenings());
      setMessage("Opening decision recorded.");
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
        {mode.kind === "list" ? (
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

      {mode.kind === "direct" ? (
        <DirectSelectionOpeningForm
          onCancel={() => setMode({ kind: "list" })}
          onCreated={(items, applicant) => {
            setOpenings(items);
            setMode({ kind: "list" });
            setMessage(`${applicant.applicantName ?? applicant.primaryEmail} selected for the new opening.`);
            props.onPoolChanged();
          }}
          onError={props.onError}
          onReviewRetained={props.onOpenRetainedApplicant}
        />
      ) : null}

      {mode.kind === "form" ? (
        <OpeningForm
          draft={mode.draft}
          editing={mode.editingId !== null}
          busy={busy}
          onChange={(next) => setMode({ ...mode, draft: next, launchPreview: null })}
          onCancel={() => setMode({ kind: "list" })}
          onSubmit={save}
          launchPreview={mode.launchPreview}
        />
      ) : null}

      {mode.kind === "selection" ? (
        <OpeningSelectionPanel
          selection={mode.selection}
          pendingCandidate={mode.pendingCandidate}
          confirmingNoHousehold={mode.confirmingNoHousehold}
          busy={busy}
          onChoose={(pendingCandidate) => setMode({ ...mode, pendingCandidate })}
          onRequestNoHousehold={() => setMode({ ...mode, confirmingNoHousehold: true })}
          onCancelNoHousehold={() => setMode({ ...mode, confirmingNoHousehold: false })}
          onConfirmNoHousehold={() => void confirmNoHousehold()}
          onBack={() => setMode({ ...mode, pendingCandidate: null })}
          onConfirm={() => void confirmSelection()}
          onReview={(applicationId) =>
            props.onOpenApplicant(applicationId, mode.selection.openingId)
          }
          onReviewSelected={props.onOpenRetainedApplicant}
          onClose={() => setMode({ kind: "list" })}
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
            <small>Permanent</small>
          </div>
        ) : opening.noHouseholdSelected ? (
          <div className="opening-selection-summary opening-no-selection-summary">
            <UserX size={17} />
            <span>
              Opening decision
              <strong>No household selected</strong>
            </span>
            <small>Permanent</small>
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
  busy: boolean;
  onChoose: (candidate: OpeningSelectionCandidate) => void;
  onRequestNoHousehold: () => void;
  onCancelNoHousehold: () => void;
  onConfirmNoHousehold: () => void;
  onBack: () => void;
  onConfirm: () => void;
  onReview: (id: number) => void;
  onReviewSelected: (id: number) => void;
  onClose: () => void;
}): ReactNode {
  const [candidateFilter, setCandidateFilter] = useState("");
  const selected = props.selection.selectedApplicationId;
  const filterTerms = candidateFilter.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const filteredCandidates = props.selection.candidates.filter((candidate) => {
    const searchable = `${candidate.applicantName ?? ""} ${candidate.primaryEmail}`.toLocaleLowerCase();
    return filterTerms.every((term) => searchable.includes(term));
  });
  if (props.confirmingNoHousehold) {
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
          This selection is permanent. Eligible unsuccessful applicants will be emailed immediately.
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
            <span>Permanent archived selection</span>
          </div>
          <button className="secondary-button" type="button" onClick={() => props.onReviewSelected(selected)}>
            <Eye size={15} /> Review application
          </button>
        </div>
      ) : props.selection.noHouseholdSelected ? (
        <div className="opening-selected-detail">
          <div>
            <strong>No household selected</strong>
            <span>Permanent archived decision</span>
          </div>
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
