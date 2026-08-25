import { CalendarDays, Pencil, Plus } from "lucide-react";
import { type FormEvent, type ReactNode, useEffect, useState } from "react";

import * as api from "../api";
import { readProblem } from "../format";
import type { Opening, OpeningWrite } from "../types";
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

export function OpeningsPanel(props: { onError: (message: string) => void }): ReactNode {
  const [openings, setOpenings] = useState<Opening[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [loadVersion, setLoadVersion] = useState(0);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draft, setDraft] = useState<OpeningDraft | null>(null);
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
    setEditingId(null);
    setDraft({ ...EMPTY_DRAFT });
    setMessage("");
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
      </div>
    </article>
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
