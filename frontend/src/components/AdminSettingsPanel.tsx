import { type ReactNode, type SyntheticEvent, useEffect, useState } from "react";
import * as api from "../api";
import { readProblem } from "../format";
import { isPickerConfigured, pickResponseSheet } from "../googlePicker";
import { AI_CHECKS, DETERMINISTIC_CHECKS } from "../constants";
import { NumberInput } from "./NumberInput";
import { AccessPanel } from "./AccessPanel";
import { CheckGroup } from "./CheckToggles";
import type { AppSettings, EligibilityRules, FeedbackItem, SettingsResponse, ViewTab } from "../types";

// The admin-only config surface, organized as sub-views:
//   Configuration      — the data source (Google Sheet) and AI screening knobs.
//   Committee Defaults — the shared eligibility-rules baseline every non-diverged member reads.
//   Access             — the sign-in allowlist (the existing AccessPanel, self-fetching).
//   Feedback           — member-submitted feedback with the context it came from (self-fetching).
// A member's OWN eligibility rules live on their Eligibility Settings tab; this edits only the
// shared committee default (M15 1f). Editing it has zero effect on members who've diverged.
type AdminSubtab = "configuration" | "defaults" | "access" | "feedback";

export function AdminSettingsPanel(props: {
  draft: AppSettings;
  setDraft: (next: AppSettings) => void;
  saved: SettingsResponse | null;
  isSaving: boolean;
  onSubmit: (event: SyntheticEvent<HTMLFormElement>) => void;
  onError: (message: string) => void;
  // Jump to an applicant's detail / a top-level view from a feedback item's context link.
  onOpenApplicant: (id: number) => void;
  onOpenView: (tab: ViewTab) => void;
}): ReactNode {
  const { draft, setDraft, saved } = props;
  const [subtab, setSubtab] = useState<AdminSubtab>("configuration");

  return (
    <section className="settings-panel no-print" aria-label="Admin settings">
      <div className="settings-header">
        <h3>Admin Settings</h3>
      </div>
      {/* Sub-tabs within the admin panel. Reuses the Observability/Evals underline-tab
          style (.subtabs) so nested navigation reads the same across the app. */}
      <div className="subtabs admin-settings-subtabs" role="tablist" aria-label="Admin settings sections">
        <button
          type="button"
          role="tab"
          aria-selected={subtab === "configuration"}
          className={`subtab${subtab === "configuration" ? " active" : ""}`}
          onClick={() => setSubtab("configuration")}
        >
          Configuration
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={subtab === "defaults"}
          className={`subtab${subtab === "defaults" ? " active" : ""}`}
          onClick={() => setSubtab("defaults")}
        >
          Committee Defaults
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={subtab === "access"}
          className={`subtab${subtab === "access" ? " active" : ""}`}
          onClick={() => setSubtab("access")}
        >
          Access
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={subtab === "feedback"}
          className={`subtab${subtab === "feedback" ? " active" : ""}`}
          onClick={() => setSubtab("feedback")}
        >
          Feedback
        </button>
      </div>

      {subtab === "feedback" ? (
        <FeedbackPanel
          onError={props.onError}
          onOpenApplicant={props.onOpenApplicant}
          onOpenView={props.onOpenView}
        />
      ) : subtab === "access" ? (
        <AccessPanel onError={props.onError} />
      ) : subtab === "defaults" ? (
        <CommitteeDefaultsPanel onError={props.onError} />
      ) : (
        <div className="settings-panel-body">
          <div className="settings-subtab-head">
            <h3>Configuration</h3>
            <p className="panel-hint">
              The application-responses source and the AI screening knobs shared by the whole
              committee.
            </p>
          </div>
          {/* Gate on `saved` so we don't flash the form before GET /settings resolves. */}
          {!saved ? null : (
            <form className="settings-form" onSubmit={props.onSubmit}>
              <SheetLinkField saved={saved} onError={props.onError} />

              <div className="rules-section">
                <h4>AI Screening</h4>
                <div className="settings-grid">
                  <label>
                    <span>Spending cap (USD per run)</span>
                    <NumberInput
                      min="0"
                      step="0.01"
                      value={draft.ai.spendingCapUsd}
                      onChange={(v) => setDraft({ ...draft, ai: { ...draft.ai, spendingCapUsd: v ?? 0 } })}
                    />
                    <span className="field-hint">
                      A Rank is blocked before it starts if its estimated cost exceeds this.
                    </span>
                  </label>
                  <label>
                    <span>Discovery fan-out (parallel passes)</span>
                    <NumberInput
                      min="1"
                      max="10"
                      step="1"
                      value={draft.ai.discoveryFanOut}
                      onChange={(v) => setDraft({ ...draft, ai: { ...draft.ai, discoveryFanOut: v ?? 0 } })}
                    />
                    <span className="field-hint">
                      Discovery passes run in parallel per Rank, then settled into one criteria set.
                      More passes find more axes but cost more.
                    </span>
                  </label>
                  <label>
                    <span>Consolidation correlation threshold</span>
                    <NumberInput
                      step="0.01"
                      value={draft.ai.consolidateCorrelationThreshold}
                      onChange={(v) =>
                        setDraft({ ...draft, ai: { ...draft.ai, consolidateCorrelationThreshold: v ?? 0 } })
                      }
                    />
                    <span className="field-hint">
                      After scoring, dimensions whose per-applicant scores correlate at or above this
                      are flagged as possible duplicates for an AI merge check. Lower catches subtler
                      overlaps; higher is stricter. The AI still confirms every merge.
                    </span>
                  </label>
                </div>
              </div>
              <div className="settings-actions">
                <button className="primary-button" type="submit" disabled={props.isSaving}>
                  {props.isSaving ? "Saving…" : "Save configuration"}
                </button>
              </div>
            </form>
          )}
        </div>
      )}
    </section>
  );
}

// Admin editor for the shared committee-default eligibility rules (M15 1f). Self-contained
// (fetches + saves its own resource, like AccessPanel) — it edits the committee baseline, not
// this admin's personal rules, and saving has zero effect on members who've already diverged.
const NUMERIC_FIELDS: { key: keyof EligibilityRules; label: string; min: string; max?: string }[] = [
  { key: "incomeMin", label: "Income minimum", min: "0" },
  { key: "incomeMax", label: "Income maximum", min: "0" },
  { key: "minAdultAge", label: "Min adult age", min: "1", max: "100" },
  { key: "maxChildAge", label: "Max child age", min: "0", max: "100" },
  { key: "minChildren", label: "Min children per unit", min: "0", max: "20" },
  { key: "maxChildren", label: "Max children per unit", min: "0", max: "20" },
  { key: "maxDogs", label: "Max dogs", min: "0", max: "10" },
  { key: "maxCats", label: "Max cats", min: "0", max: "10" },
];

// The response-sheet linker (M18). Replaces the old paste-a-link field with a least-privilege
// flow: the admin grants drive.file via the backend connect-sheet redirect, then picks the
// exact sheet in the Google Picker. Sync then reads with this admin's token, so members need
// no Drive/Sheets scope. Two entry points into "pick": (1) after the connect redirect returns
// with ?connect=sheet the Picker opens automatically; (2) the button re-runs the whole flow.
function SheetLinkField(props: {
  saved: SettingsResponse | null;
  onError: (message: string) => void;
}): ReactNode {
  const { saved } = props;
  const [busy, setBusy] = useState(false);
  const [linkedTitle, setLinkedTitle] = useState<string | null>(saved?.googleSheetTitle ?? null);
  const [linkedUrl, setLinkedUrl] = useState<string>(saved?.googleSheetUrl ?? "");

  // The whole one-click flow, fired from the button (a user gesture, so GIS's consent popup
  // isn't blocked): GIS code grant -> backend exchange -> Picker -> persist the picked file.
  async function connectAndPick() {
    setBusy(true);
    try {
      const picked = await pickResponseSheet();
      if (!picked) return; // cancelled at the Picker
      const response = await api.linkSheet(picked.id);
      if (!response.ok) {
        props.onError((await readProblem(response)) ?? "Could not link that sheet.");
        return;
      }
      const body = (await response.json()) as SettingsResponse;
      setLinkedTitle(body.googleSheetTitle ?? picked.name ?? "Linked sheet");
      setLinkedUrl(body.googleSheetUrl ?? "");
    } catch (err) {
      props.onError(err instanceof Error ? err.message : "Could not connect the response sheet.");
    } finally {
      setBusy(false);
    }
  }

  if (!isPickerConfigured()) {
    return (
      <div className="sheet-link-section">
        <h4>Application responses</h4>
        <p className="panel-hint">
          Google Picker isn't configured in this environment (missing API key / client id).
        </p>
      </div>
    );
  }

  return (
    <div className="sheet-link-section">
      <h4>Application responses</h4>
      <p className="rules-hint">
        Connect the Google Sheet of application responses. You'll grant access to just the one
        file you pick — members can sync without any Google Drive access of their own.
      </p>
      {linkedTitle ? (
        <p className="sheet-reference-line">
          Linked:{" "}
          {linkedUrl ? (
            <a className="sheet-reference" href={linkedUrl} target="_blank" rel="noreferrer noopener">
              {linkedTitle}
            </a>
          ) : (
            <strong>{linkedTitle}</strong>
          )}
        </p>
      ) : (
        <p className="panel-hint">No sheet linked yet.</p>
      )}
      <div className="settings-actions">
        <button type="button" className="primary-button" onClick={connectAndPick} disabled={busy}>
          {busy
            ? "Connecting…"
            : linkedTitle
              ? "Change response sheet"
              : "Connect response sheet"}
        </button>
      </div>
    </div>
  );
}


function CommitteeDefaultsPanel(props: { onError: (message: string) => void }): ReactNode {
  const [draft, setDraft] = useState<EligibilityRules | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedTick, setSavedTick] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .fetchCommitteeDefaultRules()
      .then((rules) => live && setDraft(rules))
      .catch(() => {
        if (!live) return;
        setLoadError(true); // inline error, not a perpetual "Loading…"
        props.onError("Could not load the committee default rules.");
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function save(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft || saving) return;
    setSaving(true);
    const response = await api.saveCommitteeDefaultRules(draft);
    setSaving(false);
    if (!response.ok) {
      props.onError((await readProblem(response)) ?? "The committee default rules could not be saved.");
      return;
    }
    setDraft(await response.json());
    setSavedTick(true);
    setTimeout(() => setSavedTick(false), 2000);
  }

  const set = (patch: Partial<EligibilityRules>) => draft && setDraft({ ...draft, ...patch });
  const toggle = (id: string, on: boolean) =>
    draft &&
    setDraft({
      ...draft,
      disabledChecks: on
        ? draft.disabledChecks.filter((c) => c !== id)
        : [...draft.disabledChecks, id],
    });

  return (
    <div className="settings-panel-body">
      <div className="settings-subtab-head">
        <h3>Committee Defaults</h3>
        <p className="panel-hint">
          The shared eligibility baseline every member follows until they personalize their own
          rules. Changing it does not affect members who've already diverged.
        </p>
      </div>
      {loadError ? (
        <p className="panel-hint">Couldn't load the committee default rules.</p>
      ) : !draft ? (
        <p className="panel-hint">Loading…</p>
      ) : (
        <>
          <form className="settings-form" onSubmit={save}>
            {NUMERIC_FIELDS.map((f) => (
              <label key={f.key}>
                <span>{f.label}</span>
                <NumberInput
                  min={f.min}
                  max={f.max}
                  value={draft[f.key] as number}
                  onChange={(v) => set({ [f.key]: v ?? 0 } as Partial<EligibilityRules>)}
                />
              </label>
            ))}
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={draft.allowOtherPets}
                onChange={(event) => set({ allowOtherPets: event.target.checked })}
              />
              <span>Allow other pets</span>
            </label>
            <div className="rules-section">
              <h4>Screening checks</h4>
              <p className="rules-hint">Unchecked checks are off in the committee default.</p>
              <CheckGroup
                title="Deterministic rules"
                checks={DETERMINISTIC_CHECKS}
                disabledChecks={draft.disabledChecks}
                onToggle={toggle}
              />
              <CheckGroup
                title="AI screening checks"
                checks={AI_CHECKS}
                disabledChecks={draft.disabledChecks}
                onToggle={toggle}
              />
            </div>
            <div className="settings-actions">
              <button className="primary-button" type="submit" disabled={saving}>
                {saving ? "Saving…" : savedTick ? "Saved" : "Save committee defaults"}
              </button>
            </div>
          </form>
        </>
      )}
    </div>
  );
}


// Friendly labels for the navigable top-level views captured on feedback (App's activeTab
// values). These are exactly the ViewTab keys, so a label's presence here also marks the
// key as navigable — an admin can click through to it.
const VIEW_LABELS: Record<ViewTab, string> = {
  applications: "Applications",
  ranking: "Ranking",
  observability: "Observability",
  evals: "Evals",
  eligibilitySettings: "Eligibility Settings",
  adminSettings: "Admin Settings",
};

function isViewTab(tab: string): tab is ViewTab {
  return tab in VIEW_LABELS;
}

function viewLabel(tab: string | null): string {
  if (!tab) return "unknown view";
  return isViewTab(tab) ? VIEW_LABELS[tab] : tab;
}

// Admin reader for member feedback (M15 "Future UX Enhancements" #2). Self-contained, like
// AccessPanel: fetches its own list. Open items by default; a toggle reveals resolved ones
// (retained, not deleted, so the friction history survives). Resolving an item drops it from
// the open list; reopening restores it. Each item shows who sent it and the context they were
// in, so the admin can act without a back-and-forth.
function FeedbackPanel(props: {
  onError: (message: string) => void;
  onOpenApplicant: (id: number) => void;
  onOpenView: (tab: ViewTab) => void;
}): ReactNode {
  const [items, setItems] = useState<FeedbackItem[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [showResolved, setShowResolved] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);

  useEffect(() => {
    let live = true;
    setLoadError(false); // reset on each (re)fetch — the showResolved toggle re-runs this
    api
      .fetchFeedback(showResolved)
      .then((list) => live && setItems(list))
      .catch(() => {
        if (!live) return;
        setLoadError(true); // inline error, not a perpetual "Loading…"
        props.onError("Could not load feedback.");
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showResolved]);

  async function act(id: number, action: "resolve" | "reopen") {
    setBusyId(id);
    const response = await (action === "resolve" ? api.resolveFeedback(id) : api.reopenFeedback(id));
    setBusyId(null);
    if (!response.ok) {
      props.onError((await readProblem(response)) ?? `Could not ${action} the feedback item.`);
      return;
    }
    // Re-fetch under the current filter so the item lands in (or leaves) the visible list.
    api
      .fetchFeedback(showResolved)
      .then(setItems)
      .catch(() => props.onError("Could not refresh feedback."));
  }

  return (
    <div className="settings-panel-body">
      <div className="settings-subtab-head">
        <h3>Feedback</h3>
        <p className="panel-hint">
          Feedback members sent from anywhere in the app, newest first. May contain applicant
          details — treat it as sensitive.
        </p>
      </div>
      <div className="feedback-admin-header">
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={showResolved}
            onChange={(event) => setShowResolved(event.target.checked)}
          />
          <span>Show resolved</span>
        </label>
      </div>
      {loadError ? (
        <p className="panel-hint">Couldn't load feedback.</p>
      ) : items === null ? (
        <p className="panel-hint">Loading…</p>
      ) : items.length === 0 ? (
        <p className="panel-hint">{showResolved ? "No feedback yet." : "No open feedback."}</p>
      ) : (
        <ul className="feedback-list">
          {items.map((item) => (
            <li key={item.id} className={`feedback-item${item.resolvedAt ? " is-resolved" : ""}`}>
              <p className="feedback-item-body">{item.body}</p>
              <div className="feedback-item-meta">
                <span>{item.userName}</span>
                <span>{item.userEmail}</span>
                <span>{new Date(item.createdAt).toLocaleString()}</span>
                {/* Where they were. An applicant-detail item links to that applicant;
                    everything else names the view. Applicant takes precedence — it's the
                    most specific "jump here" the admin can act on. */}
                {item.applicantId !== null ? (
                  <button
                    type="button"
                    className="feedback-context-link"
                    onClick={() => props.onOpenApplicant(item.applicantId as number)}
                  >
                    {item.applicantName ?? `applicant #${item.applicantId}`}
                  </button>
                ) : item.activeTab && isViewTab(item.activeTab) ? (
                  <button
                    type="button"
                    className="feedback-context-link"
                    onClick={() => props.onOpenView(item.activeTab as ViewTab)}
                  >
                    {viewLabel(item.activeTab)}
                  </button>
                ) : (
                  <span>{viewLabel(item.activeTab)}</span>
                )}
                {item.analysisId !== null ? <span>ranking #{item.analysisId}</span> : null}
                <span>v{item.appVersion}</span>
              </div>
              <div className="feedback-item-actions">
                {item.resolvedAt ? (
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={busyId === item.id}
                    onClick={() => act(item.id, "reopen")}
                  >
                    Reopen
                  </button>
                ) : (
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={busyId === item.id}
                    onClick={() => act(item.id, "resolve")}
                  >
                    Mark resolved
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
