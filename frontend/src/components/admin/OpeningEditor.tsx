import { type FormEvent, type ReactNode, useState } from "react";

import * as api from "../../api/openings";
import { readProblem } from "../../api/problems";
import { useRequestScope } from "../../hooks/useRequestScope";
import type { Opening, OpeningCreate, OpeningCreated, OpeningPreview, OpeningWrite } from "../../types";
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

/** Owns the editable draft and the preview-before-publication workflow. */
export function OpeningEditor(props: {
  opening: Opening | null;
  onCancel: () => void;
  onSaved: (openings: Opening[], message: string) => void;
  busy: boolean;
  setBusy: (busy: boolean) => void;
  onError: (message: string) => void;
}): ReactNode {
  const [draft, setDraft] = useState<OpeningDraft>(() => props.opening ? {
    unitSizeBedrooms: props.opening.unitSizeBedrooms,
    housingChargeDollars: props.opening.housingChargeCents / 100,
    applicationOpenDate: props.opening.applicationOpenDate ?? "",
    applicationCloseDate: props.opening.applicationCloseDate ?? "",
    moveInDate: props.opening.moveInDate,
  } : { ...EMPTY_DRAFT });
  const [launchPreview, setLaunchPreview] = useState<OpeningPreview | null>(null);
  const { busy, setBusy } = props;
  const previewRequests = useRequestScope();

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
    const response = await api.createOpening(createPayload(payload()), launchPreview.audienceCount);
    if (!response.ok) {
      if (response.status === 409) setLaunchPreview(null);
      props.onError((await readProblem(response)) ?? "Could not create that opening.");
      return;
    }
    const created = (await response.json()) as OpeningCreated;
    props.onSaved(created.openings,
      `Applications are open and ${created.queuedNotificationCount} ${created.queuedNotificationCount === 1 ? "email is" : "emails are"} queued.`,
    );
  }

  async function update(): Promise<void> {
    if (!props.opening) return;
    const response = await api.updateOpening(props.opening.id, payload());
    if (!response.ok) {
      props.onError((await readProblem(response)) ?? "Could not update that opening.");
      return;
    }
    const result = (await response.json()) as { openings: Opening[] };
    props.onSaved(result.openings, "Opening updated.");
  }

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      if (props.opening) await update();
      else if (launchPreview) await publish();
      else await preview();
    } catch {
      props.onError(props.opening ? "Could not update that opening." : "Could not create that opening.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <OpeningForm
      draft={draft}
      editing={props.opening !== null}
      busy={busy}
      onChange={(next) => {
        previewRequests.invalidate();
        setDraft(next);
        setLaunchPreview(null);
      }}
      onCancel={props.onCancel}
      onSubmit={(event) => void submit(event)}
      launchPreview={launchPreview}
    />
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
