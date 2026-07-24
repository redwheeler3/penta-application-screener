import { type ReactNode, type SyntheticEvent, useState } from "react";
import { NumberInput } from "./NumberInput";
import { AccessPanel } from "./AccessPanel";
import type { AppSettings, SettingsResponse } from "../types";

// The admin-only config surface, organized as two sub-views:
//   Configuration — the data source (Google Sheet), pet limits, and AI screening knobs.
//   Access        — the sign-in allowlist (the existing AccessPanel, self-fetching).
// Per-member eligibility rules are NOT here; each member tunes those on their own
// Eligibility Settings tab (see EligibilitySettingsPanel).
type AdminSubtab = "configuration" | "access";

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
          aria-selected={subtab === "access"}
          className={`insights-subtab${subtab === "access" ? " active" : ""}`}
          onClick={() => setSubtab("access")}
        >
          Access
        </button>
      </div>

      {subtab === "access" ? (
        <AccessPanel onError={props.onError} />
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
              <label>
                <span>Max dogs</span>
                <NumberInput
                  min="0"
                  max="10"
                  value={draft.maxDogs}
                  onChange={(v) => setDraft({ ...draft, maxDogs: v ?? 0 })}
                />
              </label>
              <label>
                <span>Max cats</span>
                <NumberInput
                  min="0"
                  max="10"
                  value={draft.maxCats}
                  onChange={(v) => setDraft({ ...draft, maxCats: v ?? 0 })}
                />
              </label>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={draft.allowOtherPets}
                  onChange={(event) => setDraft({ ...draft, allowOtherPets: event.target.checked })}
                />
                <span>Allow other pets</span>
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
