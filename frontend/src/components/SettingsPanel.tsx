import { type ReactNode, type SyntheticEvent } from "react";
import { ALL_RULES } from "../constants";
import { NumberInput } from "./NumberInput";
import type { AppSettings, SettingsResponse } from "../types";

export function SettingsPanel(props: {
  draft: AppSettings;
  setDraft: (next: AppSettings) => void;
  saved: SettingsResponse | null;
  isSaving: boolean;
  onSubmit: (event: SyntheticEvent<HTMLFormElement>) => void;
}): ReactNode {
  const { draft, setDraft, saved } = props;

  return (
    <section className="settings-panel no-print" aria-label="Admin settings">
      <div className="settings-panel-body">
        {/* Rendered as the Settings tab's content: the form shows directly (you
            navigated here to view/edit config), no summary/expand dance. Still gate
            on `saved` so we don't flash the form before GET /settings resolves. */}
        {!saved ? null : (
          <form className="settings-form" onSubmit={props.onSubmit}>
            <label>
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
              <span>Income minimum</span>
              <NumberInput
                min="0"
                value={draft.incomeMin}
                onChange={(v) => setDraft({ ...draft, incomeMin: v ?? 0 })}
              />
            </label>
            <label>
              <span>Income maximum</span>
              <NumberInput
                min="0"
                value={draft.incomeMax}
                onChange={(v) => setDraft({ ...draft, incomeMax: v ?? 0 })}
              />
            </label>
            <label>
              <span>Min adult age</span>
              <NumberInput
                min="1"
                max="100"
                value={draft.minAdultAge}
                onChange={(v) => setDraft({ ...draft, minAdultAge: v ?? 0 })}
              />
            </label>
            <label>
              <span>Max child age</span>
              <NumberInput
                min="0"
                max="100"
                value={draft.maxChildAge}
                onChange={(v) => setDraft({ ...draft, maxChildAge: v ?? 0 })}
              />
            </label>
            <label>
              <span>Min children per unit</span>
              <NumberInput
                min="0"
                max="20"
                value={draft.minChildren}
                onChange={(v) => setDraft({ ...draft, minChildren: v ?? 0 })}
              />
            </label>
            <label>
              <span>Max children per unit</span>
              <NumberInput
                min="0"
                max="20"
                value={draft.maxChildren}
                onChange={(v) => setDraft({ ...draft, maxChildren: v ?? 0 })}
              />
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
              <h3>Screening Rules</h3>
              <p className="rules-hint">Uncheck a rule to disable it. Disabled rules will not run during screening.</p>
              <div className="rules-grid">
                {[...ALL_RULES].sort((a, b) => a.label.localeCompare(b.label)).map((rule) => (
                  <label key={rule.id} className="checkbox-label rule-toggle">
                    <input
                      type="checkbox"
                      checked={!draft.disabledRules.includes(rule.id)}
                      onChange={(event) => {
                        const disabled = event.target.checked
                          ? draft.disabledRules.filter((r) => r !== rule.id)
                          : [...draft.disabledRules, rule.id];
                        setDraft({ ...draft, disabledRules: disabled });
                      }}
                    />
                    <span>{rule.label}</span>
                  </label>
                ))}
              </div>
            </div>
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
    </section>
  );
}
