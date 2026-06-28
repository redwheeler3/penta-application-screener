import { type ReactNode, type SyntheticEvent } from "react";
import { ALL_RULES } from "../constants";
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
              <input
                type="number"
                min="0"
                value={draft.incomeMin}
                onChange={(event) => setDraft({ ...draft, incomeMin: Number(event.target.value) })}
              />
            </label>
            <label>
              <span>Income maximum</span>
              <input
                type="number"
                min="0"
                value={draft.incomeMax}
                onChange={(event) => setDraft({ ...draft, incomeMax: Number(event.target.value) })}
              />
            </label>
            <label>
              <span>Min adult age</span>
              <input
                type="number"
                min="1"
                max="100"
                value={draft.minAdultAge}
                onChange={(event) => setDraft({ ...draft, minAdultAge: Number(event.target.value) })}
              />
            </label>
            <label>
              <span>Max child age</span>
              <input
                type="number"
                min="0"
                max="100"
                value={draft.maxChildAge}
                onChange={(event) => setDraft({ ...draft, maxChildAge: Number(event.target.value) })}
              />
            </label>
            <label>
              <span>Min children per unit</span>
              <input
                type="number"
                min="0"
                max="20"
                value={draft.minChildren}
                onChange={(event) => setDraft({ ...draft, minChildren: Number(event.target.value) })}
              />
            </label>
            <label>
              <span>Max children per unit</span>
              <input
                type="number"
                min="0"
                max="20"
                value={draft.maxChildren}
                onChange={(event) => setDraft({ ...draft, maxChildren: Number(event.target.value) })}
              />
            </label>
            <label>
              <span>Max dogs</span>
              <input
                type="number"
                min="0"
                max="10"
                value={draft.maxDogs}
                onChange={(event) => setDraft({ ...draft, maxDogs: Number(event.target.value) })}
              />
            </label>
            <label>
              <span>Max cats</span>
              <input
                type="number"
                min="0"
                max="10"
                value={draft.maxCats}
                onChange={(event) => setDraft({ ...draft, maxCats: Number(event.target.value) })}
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
              <p className="rules-hint">
                The screening run is blocked before it starts if its estimated cost exceeds this cap.
              </p>
              <label>
                <span>Spending cap (USD per run)</span>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={draft.ai.spendingCapUsd}
                  onChange={(event) =>
                    setDraft({ ...draft, ai: { ...draft.ai, spendingCapUsd: Number(event.target.value) } })
                  }
                />
              </label>
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
