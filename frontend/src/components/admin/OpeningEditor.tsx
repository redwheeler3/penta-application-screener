import { useCommitteeApi } from "../../api/identity";
import { type FormEvent, type ReactNode, useRef, useState } from "react";

import * as openingsApi from "../../api/openings";
import { problemMessage, readProblemBody } from "../../api/problems";
import { useRequestScope } from "../../hooks/useRequestScope";
import type { Opening, OpeningCreate, OpeningCommit, OpeningDetails, OpeningUpdated, OpeningWrite } from "../../types";
import { NumberInput } from "../shared/NumberInput";

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

function openingValues(opening: Opening | OpeningDetails): OpeningWrite {
  return {
    unitSizeBedrooms: opening.unitSizeBedrooms, housingChargeCents: opening.housingChargeCents,
    applicationOpenDate: opening.applicationOpenDate, applicationCloseDate: opening.applicationCloseDate ?? "",
    moveInDate: opening.moveInDate,
  };
}

function editableDraft(values: OpeningWrite): OpeningDraft {
  return { unitSizeBedrooms: values.unitSizeBedrooms, housingChargeDollars: values.housingChargeCents / 100,
    applicationOpenDate: values.applicationOpenDate ?? "", applicationCloseDate: values.applicationCloseDate, moveInDate: values.moveInDate };
}

/** Owns vacancy creation and optimistic editing of saved opening facts. */
export function OpeningEditor(props: {
  opening: Opening | null;
  onCancel: () => void;
  onSaved: (openings: Opening[], message: string, closeEditor?: boolean) => void;
  busy: boolean;
  setBusy: (busy: boolean) => void;
  onError: (message: string) => void;
}): ReactNode {
  const api = useCommitteeApi(openingsApi);

  const [draft, setDraft] = useState<OpeningDraft>(() => props.opening ? editableDraft(openingValues(props.opening)) : { ...EMPTY_DRAFT });
  const { busy, setBusy } = props;
  const requests = useRequestScope();
  const accepted = useRef(props.opening ? openingValues(props.opening) : null);
  const currentDraft = useRef(draft);
  currentDraft.current = draft;
  const pending = useRef(false);
  const [creating, setCreating] = useState(false);
  const [creationUnconfirmed, setCreationUnconfirmed] = useState(false);
  const creationRequestId = useRef<string | null>(null);
  const [reloading, setReloading] = useState(false);
  const [conflict, setConflict] = useState(false);

  function payload(): OpeningWrite {
    return {
      unitSizeBedrooms: draft.unitSizeBedrooms,
      housingChargeCents: Math.round(draft.housingChargeDollars * 100),
      applicationOpenDate: draft.applicationOpenDate || null,
      applicationCloseDate: draft.applicationCloseDate,
      moveInDate: draft.moveInDate,
    };
  }

  async function create(): Promise<void> {
    const isCurrent = requests.capture();
    setCreating(true);
    creationRequestId.current ??= crypto.randomUUID();
    const response = await api.createOpening(createPayload(payload()), creationRequestId.current);
    if (!isCurrent()) return;
    if (!response.ok) {
      const problem = await readProblemBody(response);
      if (!isCurrent()) return;
      if (response.status >= 500 || problem?.code === "opening_creation_changed") setCreationUnconfirmed(true);
      props.onError(problemMessage(problem) ?? "Could not create that opening.");
      return;
    }
    const created = (await response.json()) as OpeningCommit;
    if (!isCurrent()) return;
    props.onSaved(created.openings,
      "Opening created. You can open applications when you’re ready.",
    );
  }

  async function update(): Promise<void> {
    if (!props.opening || !accepted.current) return;
    const isCurrent = requests.capture();
    const snapshot = JSON.stringify(draft);
    const response = await api.updateOpening(props.opening.id, accepted.current, payload());
    if (!isCurrent()) return;
    if (!response.ok) {
      const problem = await readProblemBody(response);
      if (!isCurrent()) return;
      if (problem?.code === "stale_opening") setConflict(true);
      props.onError(problemMessage(problem) ?? "Could not update that opening.");
      return;
    }
    const result = (await response.json()) as OpeningUpdated;
    if (!isCurrent()) return;
    accepted.current = openingValues(result.saved);
    const unchanged = JSON.stringify(currentDraft.current) === snapshot;
    props.onSaved(result.openings, unchanged ? "Opening updated." : "Opening updated. Your newer edits are still unsaved.", unchanged);
  }

  async function reloadSavedFacts(): Promise<void> {
    if (!props.opening || pending.current) return;
    const isCurrent = requests.capture();
    pending.current = true;
    setBusy(true);
    setReloading(true);
    try {
      const openings = await api.fetchOpenings();
      if (!isCurrent()) return;
      const opening = openings.find((item) => item.id === props.opening?.id);
      if (!opening) throw new Error("Opening unavailable");
      accepted.current = openingValues(opening);
      setDraft(editableDraft(accepted.current));
      setConflict(false);
      props.onSaved(openings, "Saved opening facts reloaded.", false);
    } catch {
      if (isCurrent()) props.onError("Could not reload the opening. Your edits are still here.");
    } finally {
      pending.current = false;
      if (isCurrent()) {
        setReloading(false);
        setBusy(false);
      }
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (busy || pending.current || conflict) return;
    const isCurrent = requests.capture();
    pending.current = true;
    setBusy(true);
    try {
      if (props.opening) await update();
      else await create();
    } catch {
      if (isCurrent()) {
        if (!props.opening && creationRequestId.current !== null) setCreationUnconfirmed(true);
        props.onError(props.opening ? "Could not confirm the opening save. Your edits are still here." : "Could not confirm opening creation. Retry to check the saved result safely.");
      }
    } finally {
      pending.current = false;
      if (isCurrent()) {
        setCreating(false);
        setBusy(false);
      }
    }
  }

  return (
    <>
      <OpeningForm
        draft={draft}
        editing={props.opening !== null}
        busy={busy}
        fieldsDisabled={creating || creationUnconfirmed || reloading}
        conflict={conflict}
        onChange={(next) => {
          requests.invalidate();
          creationRequestId.current = null;
          setDraft(next);
        }}
        onCancel={props.onCancel}
        onSubmit={(event) => void submit(event)}
      />
      {creationUnconfirmed ? <p className="opening-message" role="status">
        Creation may already be saved. Retry this request to confirm it before changing the opening facts.
      </p> : null}
      {conflict ? <div className="opening-launch-preview" role="alert">
        <p>This opening changed elsewhere. Your edits are still here and haven’t been saved.</p>
        <p>Reloading replaces these edits with the saved opening facts.</p>
        <button className="secondary-button" type="button" disabled={busy} onClick={() => void reloadSavedFacts()}>Reload saved facts</button>
      </div> : null}
    </>
  );
}

function OpeningForm(props: {
  draft: OpeningDraft;
  editing: boolean;
  busy: boolean;
  fieldsDisabled: boolean;
  conflict: boolean;
  onChange: (draft: OpeningDraft) => void;
  onCancel: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}): ReactNode {
  const set = (patch: Partial<OpeningDraft>) => props.onChange({ ...props.draft, ...patch });
  return (
    <form className="opening-form" onSubmit={props.onSubmit}>
      <div className="opening-form-heading">
        <h4>{props.editing ? "Edit opening" : "New opening"}</h4>
        <span>{props.editing ? "Update the opening details." : "Create the vacancy now; open applications when you are ready."}</span>
      </div>
      {props.editing ? <p className="panel-hint">Shortening the deadline can make previous applications due for deletion sooner.</p> : null}
      <div className="opening-form-grid">
        <label>
          <span>Unit size</span>
          <select disabled={props.fieldsDisabled} value={props.draft.unitSizeBedrooms} onChange={(event) => set({ unitSizeBedrooms: Number(event.target.value) })}>
            <option value={1}>1 bedroom</option>
            <option value={2}>2 bedrooms</option>
            <option value={3}>3 bedrooms</option>
          </select>
        </label>
        <label>
          <span>Monthly housing charge</span>
          <div className="opening-money-input">
            <span>$</span>
            <NumberInput disabled={props.fieldsDisabled} min="0" step="0.01" required value={props.draft.housingChargeDollars} onChange={(value) => set({ housingChargeDollars: value ?? 0 })} />
          </div>
        </label>
        {props.editing && props.draft.applicationOpenDate ? (
          <label>
            <span>Applications opened</span>
            <input type="date" value={props.draft.applicationOpenDate} readOnly />
          </label>
        ) : null}
        <label>
          <span>Applications close</span>
          <input type="date" disabled={props.fieldsDisabled} required value={props.draft.applicationCloseDate} onChange={(event) => set({ applicationCloseDate: event.target.value })} />
        </label>
        <label>
          <span>Move-in date</span>
          <input type="date" disabled={props.fieldsDisabled} required value={props.draft.moveInDate} onChange={(event) => set({ moveInDate: event.target.value })} />
        </label>
      </div>
      <div className="opening-form-actions">
        <button className="secondary-button" type="button" onClick={props.onCancel} disabled={props.busy}>Cancel</button>
        <button className="primary-button" type="submit" disabled={props.busy || props.conflict}>
          {props.busy
            ? "Working…"
            : props.editing
              ? "Save changes"
              : "Create opening"}
        </button>
      </div>
    </form>
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
