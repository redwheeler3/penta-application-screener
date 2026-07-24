import { type ReactNode, type SyntheticEvent, useEffect, useState } from "react";
import * as api from "../api";
import { readProblem } from "../format";
import { AI_CHECKS, DETERMINISTIC_CHECKS } from "../constants";
import { NumberInput } from "./NumberInput";
import { AccessPanel } from "./AccessPanel";
import type { AppSettings, EligibilityRules, SettingsResponse } from "../types";

// The admin-only config surface, organized as sub-views:
//   Configuration      — the data source (Google Sheet) and AI screening knobs.
//   Committee Defaults — the shared eligibility-rules baseline every non-diverged member reads.
//   Access             — the sign-in allowlist (the existing AccessPanel, self-fetching).
// A member's OWN eligibility rules live on their Eligibility Settings tab; this edits only the
// shared committee default (M15 1f). Editing it has zero effect on members who've diverged.
type AdminSubtab = "configuration" | "defaults" | "access";

export function AdminSettingsPanel(props: {
  draft: AppSettings;
  setDraft: (next: AppSettings) => void;
  saved: SettingsResponse | null;
  isSaving: boolean;
  onSubmit: (event: SyntheticEvent<HTMLFormElement>) => void;
  onError: (message: string) => void;
}): ReactNode {
  const { draft, setDraft, saved } = props;
  const [subtab, setSubtab] = useState<AdminSubtab>("configuration");

  return (
    <section className="settings-panel no-print" aria-label="Admin settings">
      <div className="settings-header">
        <h3>Admin Settings</h3>
      </div>
      {/* Sub-tabs within the admin panel. Reuses the Observability/Evals underline-tab
          style (.insights-subtabs) so nested navigation reads the same across the app. */}
      <div className="insights-subtabs admin-settings-subtabs" role="tablist" aria-label="Admin settings sections">
        <button
          type="button"
          role="tab"
          aria-selected={subtab === "configuration"}
          className={`insights-subtab${subtab === "configuration" ? " active" : ""}`}
          onClick={() => setSubtab("configuration")}
        >
          Configuration
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={subtab === "defaults"}
          className={`insights-subtab${subtab === "defaults" ? " active" : ""}`}
          onClick={() => setSubtab("defaults")}
        >
          Committee Defaults
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={subtab === "access"}
          className={`insights-subtab${subtab === "access" ? " active" : ""}`}
          onClick={() => setSubtab("access")}
        >
          Access
        </button>
      </div>

      {subtab === "access" ? (
        <AccessPanel onError={props.onError} />
      ) : subtab === "defaults" ? (
        <CommitteeDefaultsPanel onError={props.onError} />
      ) : (
        <div className="settings-panel-body">
          {/* Gate on `saved` so we don't flash the form before GET /settings resolves. */}
          {!saved ? null : (
            <form className="settings-form" onSubmit={props.onSubmit}>
              <label className="settings-field-wide">
                <span>Google Sheet link</span>
                <input
                  value={draft.googleSheetId}
                  onChange={(event) => setDraft({ ...draft, googleSheetId: event.target.value })}
                  placeholder="Paste the response spreadsheet link"
                />
                {saved?.googleSheetTitle && saved.googleSheetUrl ? (
                  <a className="sheet-reference" href={saved.googleSheetUrl} target="_blank" rel="noreferrer">
                    {saved.googleSheetTitle}
                  </a>
                ) : null}
              </label>
              <div className="rules-section">
                <h3>AI Screening</h3>
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
                  {props.isSaving ? "Saving" : "Save settings"}
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

function CommitteeDefaultsPanel(props: { onError: (message: string) => void }): ReactNode {
  const [draft, setDraft] = useState<EligibilityRules | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedTick, setSavedTick] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .fetchCommitteeDefaultRules()
      .then((rules) => live && setDraft(rules))
      .catch(() => live && props.onError("Could not load the committee default rules."));
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
      {!draft ? (
        <p className="panel-hint">Loading…</p>
      ) : (
        <>
          <p className="panel-hint committee-defaults-intro">
            The shared baseline every member follows until they personalize their own rules.
            Changing it does not affect members who've already diverged.
          </p>
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
              <h3>Screening checks</h3>
              <p className="rules-hint">Unchecked checks are off in the committee default.</p>
              <DefaultCheckGroup title="Deterministic rules" checks={DETERMINISTIC_CHECKS} draft={draft} toggle={toggle} />
              <DefaultCheckGroup title="AI screening checks" checks={AI_CHECKS} draft={draft} toggle={toggle} />
            </div>
            <div className="settings-actions">
              <button className="primary-button" type="submit" disabled={saving}>
                {saving ? "Saving" : savedTick ? "Saved" : "Save committee defaults"}
              </button>
            </div>
          </form>
        </>
      )}
    </div>
  );
}

function DefaultCheckGroup(props: {
  title: string;
  checks: readonly { id: string; label: string }[];
  draft: EligibilityRules;
  toggle: (id: string, on: boolean) => void;
}): ReactNode {
  const { title, checks, draft, toggle } = props;
  return (
    <div className="check-group">
      <h4>{title}</h4>
      <div className="rules-grid">
        {[...checks].sort((a, b) => a.label.localeCompare(b.label)).map((check) => (
          <label key={check.id} className="checkbox-label rule-toggle">
            <input
              type="checkbox"
              checked={!draft.disabledChecks.includes(check.id)}
              onChange={(event) => toggle(check.id, event.target.checked)}
            />
            <span>{check.label}</span>
          </label>
        ))}
      </div>
    </div>
  );
}
