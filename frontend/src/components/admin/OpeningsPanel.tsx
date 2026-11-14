import { useCommitteeApi } from "../../api/identity";
import { CalendarDays, Eye, Pencil, Plus, UserCheck } from "lucide-react";
import { type ReactNode, useState } from "react";

import * as openingsApi from "../../api/openings";
import { formatDateOnly, formatHousingCharge } from "../../format";
import { useFetchResource } from "../../hooks/useFetchResource";
import { useRequestScope } from "../../hooks/useRequestScope";
import type { Opening, OpeningSelection } from "../../types";
import { RetryLoadError } from "../shared/RetryLoadError";
import { DirectSelectionOpeningForm } from "./DirectSelectionOpeningForm";
import { OpeningDecisionPanel } from "./OpeningDecisionPanel";
import { OpeningLaunchPanel } from "./OpeningLaunchPanel";
import { OpeningEditor } from "./OpeningEditor";

type OpeningPanelMode =
  | { kind: "list" }
  | { kind: "form"; opening: Opening | null }
  | { kind: "direct"; opening: Opening }
  | { kind: "launch"; opening: Opening }
  | { kind: "selection"; selection: OpeningSelection };

export function OpeningsPanel(props: {
  onError: (message: string) => void;
  onPoolChanged: () => void;
  onOpenApplicant: (id: number, openingId: number) => void;
  onOpenRetainedApplicant: (id: number) => void;
}): ReactNode {
  const api = useCommitteeApi(openingsApi);

  const openingsResource = useFetchResource<Opening[]>(api.fetchOpenings, {
    onError: () => props.onError("Could not load openings."),
  });
  const openings = openingsResource.data;
  const setOpenings = openingsResource.setData;
  const [mode, setMode] = useState<OpeningPanelMode>({ kind: "list" });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const navigation = useRequestScope();

  function changeMode(next: OpeningPanelMode): void {
    navigation.invalidate();
    setBusy(false);
    setMode(next);
  }

  function beginCreate(): void {
    changeMode({ kind: "form", opening: null });
    setMessage("");
  }

  function beginDirectSelection(opening: Opening): void {
    changeMode({ kind: "direct", opening });
    setMessage("");
  }

  function beginEdit(opening: Opening): void {
    if (opening.intakeMode !== "applications"
      || opening.applicationCloseDate === null) return;
    changeMode({ kind: "form", opening });
    setMessage("");
  }

  function completeWorkflow(items: Opening[], message: string, closeEditor = true): void {
    setOpenings(items);
    if (closeEditor) changeMode({ kind: "list" });
    setMessage(message);
  }

  async function manageSelection(opening: Opening): Promise<void> {
    const isCurrent = navigation.begin();
    setBusy(true);
    setMessage("");
    try {
      const selection = await api.fetchOpeningSelection(opening.id);
      if (!isCurrent()) return;
      if (selection.selectedApplicationId !== null || selection.noHouseholdSelected) {
        const refreshed = await api.fetchOpenings();
        if (!isCurrent()) return;
        setOpenings(refreshed);
        setMessage("Opening decision is already recorded.");
        return;
      }
      setMode({ kind: "selection", selection });
    } catch {
      if (isCurrent()) props.onError("Could not load the opening selection.");
    } finally {
      if (isCurrent()) setBusy(false);
    }
  }

  return (
    <div className="settings-panel-body openings-panel">
      <div className="settings-subtab-head openings-header">
        <div>
          <h3>Openings</h3>
          <p className="panel-hint">
            Create and manage openings for available homes.
          </p>
        </div>
        {mode.kind === "list" ? (
          <div className="opening-header-actions">
            <button className="primary-button" type="button" onClick={beginCreate}>
              <Plus size={16} /> New opening
            </button>
          </div>
        ) : null}
      </div>

      {mode.kind === "direct" ? (
        <DirectSelectionOpeningForm
          opening={mode.opening}
          onCancel={() => changeMode({ kind: "list" })}
          onSavingChange={setBusy}
          onUnconfirmed={() => { props.onPoolChanged(); return openingsResource.reload(); }}
          onCreated={(items, applicant) => {
            setOpenings(items);
            changeMode({ kind: "list" });
            setMessage(`${applicant.applicantName ?? applicant.primaryEmail} selected for the new opening.`);
            props.onPoolChanged();
          }}
          onError={props.onError}
          onReviewRetained={props.onOpenRetainedApplicant}
        />
      ) : null}

      {mode.kind === "launch" ? <OpeningLaunchPanel opening={mode.opening}
        busy={busy} setBusy={setBusy}
        onSaved={(items, message) => { completeWorkflow(items, message); props.onPoolChanged(); }}
        onCancel={() => { changeMode({ kind: "list" }); void openingsResource.reload(); }} onError={props.onError} /> : null}

      {mode.kind === "form" ? (
        <OpeningEditor
          key={mode.opening?.id ?? "new"}
          opening={mode.opening}
          onCancel={() => {
            changeMode({ kind: "list" });
            void openingsResource.reload();
          }}
          onSaved={(items, message, closeEditor) => {
            completeWorkflow(items, message, closeEditor);
            props.onPoolChanged();
          }}
          busy={busy}
          setBusy={setBusy}
          onError={props.onError}
        />
      ) : null}

      {mode.kind === "selection" ? (
        <OpeningDecisionPanel
          onUnconfirmed={() => { props.onPoolChanged(); return openingsResource.reload(); }}
          key={mode.selection.openingId}
          selection={mode.selection}
          onSaved={(items, message) => {
            completeWorkflow(items, message);
            props.onPoolChanged();
          }}
          busy={busy}
          setBusy={setBusy}
          onError={props.onError}
          onReview={(applicationId) => props.onOpenApplicant(applicationId, mode.selection.openingId)}
          onClose={() => changeMode({ kind: "list" })}
        />
      ) : null}

      {message ? <p className="opening-message" role="status">{message}</p> : null}
      {openingsResource.state === "error" ? (
        <RetryLoadError
          message="Couldn't load openings."
          onRetry={openingsResource.reload}
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
              onLaunch={() => changeMode({ kind: "launch", opening })}
              onDirect={() => beginDirectSelection(opening)}
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

function OpeningCard(props: {
  opening: Opening;
  busy: boolean;
  onEdit: () => void;
  onLaunch: () => void;
  onDirect: () => void;
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
          {opening.phase === "preparing" && opening.applicationCloseDate ? <div><dt>Application deadline</dt><dd>{formatDateOnly(opening.applicationCloseDate)}</dd></div> : null}
          <div><dt>Move-in</dt><dd>{formatDateOnly(opening.moveInDate)}</dd></div>
          {opening.intakeMode === "applications" ? (
            <div><dt>Submissions</dt><dd>{opening.submissionCount}</dd></div>
          ) : null}
          {opening.selectedApplicationId !== null ? (
            <div>
              <dt>Selected applicant</dt>
              <dd>{opening.selectedApplicantName ?? "Application selected"}</dd>
            </div>
          ) : opening.noHouseholdSelected ? (
            <div><dt>Opening decision</dt><dd>No household selected</dd></div>
          ) : null}
        </dl>
        {opening.needsDecision ? (
          <p className="opening-selection-needed">{opening.phase === "preparing"
            ? "The planned deadline has passed and this opening's retention protection has ended. Extend the deadline, fill the opening, or cancel it."
            : "An opening decision is required."}</p>
        ) : null}
      </div>
      <div className="opening-card-actions">
        {opening.phase === "preparing" ? <>
          <button className="primary-button" disabled={props.busy} onClick={props.onLaunch}>Open applications</button>
          <button className="secondary-button" disabled={props.busy} onClick={props.onDirect}>Fill from previous applicants</button>
          <button className="secondary-button" disabled={props.busy} onClick={props.onManageSelection}>Cancel opening</button>
        </> : null}
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
        {(opening.phase === "closed" || opening.phase === "archived")
          && opening.selectedApplicationId === null
          && !opening.noHouseholdSelected ? (
          <button className={opening.needsDecision ? "primary-button" : "secondary-button"} type="button" onClick={props.onManageSelection} disabled={props.busy}>
            <UserCheck size={15} /> Record decision
          </button>
        ) : null}
      </div>
    </article>
  );
}
