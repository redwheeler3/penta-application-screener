import { type FormEvent, type ReactNode, useRef, useState } from "react";

import * as api from "../../api/openings";
import { problemMessage, readProblemBody } from "../../api/problems";
import { useRequestScope } from "../../hooks/useRequestScope";
import { useFetchResource } from "../../hooks/useFetchResource";
import type { Opening, OpeningCreate, OpeningCommit, OpeningDetails, OpeningPreview, OpeningUpdated, OpeningWrite } from "../../types";
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
    applicationOpenDate: opening.applicationOpenDate ?? "", applicationCloseDate: opening.applicationCloseDate ?? "",
    moveInDate: opening.moveInDate,
  };
}

function editableDraft(values: OpeningWrite): OpeningDraft {
  return { unitSizeBedrooms: values.unitSizeBedrooms, housingChargeDollars: values.housingChargeCents / 100,
    applicationOpenDate: values.applicationOpenDate, applicationCloseDate: values.applicationCloseDate, moveInDate: values.moveInDate };
}

/** Owns the editable draft and the preview-before-publication workflow. */
export function OpeningEditor(props: {
  opening: Opening | null;
  onCancel: () => void;
  onSaved: (openings: Opening[], message: string, closeEditor?: boolean) => void;
  busy: boolean;
  setBusy: (busy: boolean) => void;
  onError: (message: string) => void;
}): ReactNode {
  const [draft, setDraft] = useState<OpeningDraft>(() => props.opening ? editableDraft(openingValues(props.opening)) : { ...EMPTY_DRAFT });
  const [launchPreview, setLaunchPreview] = useState<OpeningPreview | null>(null);
  const { busy, setBusy } = props;
  const previewRequests = useRequestScope();
  const accepted = useRef(props.opening ? openingValues(props.opening) : null);
  const currentDraft = useRef(draft);
  currentDraft.current = draft;
  const pending = useRef(false);
  const [publishing, setPublishing] = useState(false);
  const [publicationUnconfirmed, setPublicationUnconfirmed] = useState(false);
  const publicationRequestId = useRef<string | null>(null);
  const [reloading, setReloading] = useState(false);
  const [conflict, setConflict] = useState(false);

  function payload(): OpeningWrite {
    return {
      unitSizeBedrooms: draft.unitSizeBedrooms,
      housingChargeCents: Math.round(draft.housingChargeDollars * 100),
      applicationOpenDate: draft.applicationOpenDate,
      applicationCloseDate: draft.applicationCloseDate,
      moveInDate: draft.moveInDate,
    };
  }

  async function preview(): Promise<void> {
    const isCurrent = previewRequests.begin();
    try {
      const result = await api.previewOpening(createPayload(payload()));
      if (isCurrent()) setLaunchPreview(result);
    } catch {
      if (isCurrent()) props.onError("Could not preview the opening and notification audience.");
    }
  }

  async function publish(): Promise<void> {
    if (!launchPreview) return;
    const isCurrent = previewRequests.capture();
    setPublishing(true);
    publicationRequestId.current ??= crypto.randomUUID();
    const response = await api.createOpening(createPayload(payload()), launchPreview.audienceCount, publicationRequestId.current);
    if (!isCurrent()) return;
    if (!response.ok) {
      const problem = await readProblemBody(response);
      if (!isCurrent()) return;
      if (response.status >= 500 || problem?.code === "opening_publication_changed") setPublicationUnconfirmed(true);
      else if (problem?.code === "opening_audience_changed") {
        setLaunchPreview(null);
        publicationRequestId.current = null;
        setPublicationUnconfirmed(false);
      }
      props.onError(problemMessage(problem) ?? "Could not create that opening.");
      return;
    }
    const created = (await response.json()) as OpeningCommit;
    if (!isCurrent()) return;
    props.onSaved(created.openings,
      `Applications are open and ${created.queuedNotificationCount} ${created.queuedNotificationCount === 1 ? "email is" : "emails are"} queued.`,
    );
  }

  async function update(): Promise<void> {
    if (!props.opening || !accepted.current) return;
    const isCurrent = previewRequests.capture();
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
    const isCurrent = previewRequests.capture();
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
    const isCurrent = previewRequests.capture();
    pending.current = true;
    setBusy(true);
    try {
      if (props.opening) await update();
      else if (launchPreview) await publish();
      else await preview();
    } catch {
      if (isCurrent()) {
        if (!props.opening && publicationRequestId.current !== null) setPublicationUnconfirmed(true);
        props.onError(props.opening ? "Could not confirm the opening save. Your edits are still here." : "Could not confirm opening publication. Retry to check the saved result safely.");
      }
    } finally {
      pending.current = false;
      if (isCurrent()) {
        setPublishing(false);
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
        fieldsDisabled={publishing || publicationUnconfirmed || reloading}
        conflict={conflict}
        onChange={(next) => {
          previewRequests.invalidate();
          publicationRequestId.current = null;
          setDraft(next);
          setLaunchPreview(null);
        }}
        onCancel={props.onCancel}
        onSubmit={(event) => void submit(event)}
        launchPreview={launchPreview}
      />
      {publicationUnconfirmed ? <p className="opening-message" role="status">
        Publication may already be saved. Retry this request to confirm it before changing the opening facts.
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
        {props.editing ? (
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
      {!props.editing && props.launchPreview ? (
        <OpeningLaunchPreview preview={props.launchPreview} />
      ) : null}
      <div className="opening-form-actions">
        <button className="secondary-button" type="button" onClick={props.onCancel} disabled={props.busy}>Cancel</button>
        <button className="primary-button" type="submit" disabled={props.busy || props.conflict}>
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
  const usageResource = useFetchResource(() => api.fetchOpeningEmailUsage(preview.audienceCount), {
    reloadKey: preview.audienceCount,
  });
  const usage = usageResource.data;
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
      {usageResource.state === "loading" ? (
        <p className="opening-quota-summary">Checking current email usage… You can confirm the opening while this loads.</p>
      ) : usage?.available ? (
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
