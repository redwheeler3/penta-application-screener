import { Settings } from "lucide-react";
import { type ReactNode, type SyntheticEvent } from "react";
import { ALL_RULES } from "../constants";
import { resolveSheetId } from "../format";
import type { AppSettings, SettingsResponse } from "../types";

export function SettingsPanel(props: {
  draft: AppSettings;
  setDraft: (next: AppSettings) => void;
  saved: SettingsResponse | null;
  isExpanded: boolean;
  onToggleExpanded: () => void;
  isSaving: boolean;
  message: string;
  onSubmit: (event: SyntheticEvent<HTMLFormElement>) => void;
}): ReactNode {
  const { draft, setDraft, saved, isExpanded } = props;
  const hasGoogleSheetLink = Boolean(saved && resolveSheetId(saved));
  // Explicit open/closed state, not derived from the field value — else typing a
  // link would collapse the form before saving.
  const showSettingsForm = isExpanded;

  return (
    <section className="settings-panel no-print" aria-label="Admin settings">
      <div className="settings-panel-header">
        <div>
          <h2>Settings</h2>
        </div>
        {hasGoogleSheetLink ? (
          <button className="secondary-button secondary-button-accent" type="button" onClick={props.onToggleExpanded}>
            <Settings size={16} />
            <span>{isExpanded ? "Hide settings" : "Edit settings"}</span>
          </button>
        ) : null}
      </div>

      <div className="settings-panel-body">
        {/* Render nothing until the GET /settings fetch resolves. Before it does,
            `saved` is null and the summary condition below is false, so the panel
            would briefly fall through to the full form — a flash of the expanded
            form on every load. Gating on `saved` avoids it; the first-run case (no
            sheet) still opens the form, since `saved` is set then with an empty id. */}
        {!saved ? null : hasGoogleSheetLink && !showSettingsForm ? (
          <div className="settings-summary">
            <div>
              <span>Google Sheet</span>
              {saved.googleSheetTitle && saved.googleSheetUrl ? (
                <a className="sheet-reference" href={saved.googleSheetUrl} target="_blank" rel="noreferrer">
                  {saved.googleSheetTitle}
                </a>
              ) : (
                <strong>{saved.settings.googleSheetId}</strong>
              )}
            </div>
            <div>
              <span>Income range</span>
              <strong>
                {`$${saved.settings.incomeMin.toLocaleString()} – $${saved.settings.incomeMax.toLocaleString()}`}
              </strong>
            </div>
          </div>
        ) : (
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
                The quality-flag run is blocked before it starts if its estimated cost exceeds this cap.
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
              {props.message ? <span>{props.message}</span> : null}
            </div>
          </form>
        )}
      </div>
    </section>
  );
}
