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
              {saved.google_sheet_title && saved.google_sheet_url ? (
                <a className="sheet-reference" href={saved.google_sheet_url} target="_blank" rel="noreferrer">
                  {saved.google_sheet_title}
                </a>
              ) : (
                <strong>{saved.settings.google_sheet_id}</strong>
              )}
            </div>
            <div>
              <span>Income range</span>
              <strong>
                {`$${saved.settings.income_min.toLocaleString()} – $${saved.settings.income_max.toLocaleString()}`}
              </strong>
            </div>
          </div>
        ) : (
          <form className="settings-form" onSubmit={props.onSubmit}>
            <label>
              <span>Google Sheet link</span>
              <input
                value={draft.google_sheet_id}
                onChange={(event) => setDraft({ ...draft, google_sheet_id: event.target.value })}
                placeholder="Paste the response spreadsheet link"
              />
              {saved?.google_sheet_title && saved.google_sheet_url ? (
                <a className="sheet-reference" href={saved.google_sheet_url} target="_blank" rel="noreferrer">
                  {saved.google_sheet_title}
                </a>
              ) : null}
            </label>
            <label>
              <span>Income minimum</span>
              <input
                type="number"
                min="0"
                value={draft.income_min}
                onChange={(event) => setDraft({ ...draft, income_min: Number(event.target.value) })}
              />
            </label>
            <label>
              <span>Income maximum</span>
              <input
                type="number"
                min="0"
                value={draft.income_max}
                onChange={(event) => setDraft({ ...draft, income_max: Number(event.target.value) })}
              />
            </label>
            <label>
              <span>Min adult age</span>
              <input
                type="number"
                min="1"
                max="100"
                value={draft.min_adult_age}
                onChange={(event) => setDraft({ ...draft, min_adult_age: Number(event.target.value) })}
              />
            </label>
            <label>
              <span>Max child age</span>
              <input
                type="number"
                min="0"
                max="100"
                value={draft.max_child_age}
                onChange={(event) => setDraft({ ...draft, max_child_age: Number(event.target.value) })}
              />
            </label>
            <label>
              <span>Min children per unit</span>
              <input
                type="number"
                min="0"
                max="20"
                value={draft.min_children}
                onChange={(event) => setDraft({ ...draft, min_children: Number(event.target.value) })}
              />
            </label>
            <label>
              <span>Max children per unit</span>
              <input
                type="number"
                min="0"
                max="20"
                value={draft.max_children}
                onChange={(event) => setDraft({ ...draft, max_children: Number(event.target.value) })}
              />
            </label>
            <label>
              <span>Max dogs</span>
              <input
                type="number"
                min="0"
                max="10"
                value={draft.max_dogs}
                onChange={(event) => setDraft({ ...draft, max_dogs: Number(event.target.value) })}
              />
            </label>
            <label>
              <span>Max cats</span>
              <input
                type="number"
                min="0"
                max="10"
                value={draft.max_cats}
                onChange={(event) => setDraft({ ...draft, max_cats: Number(event.target.value) })}
              />
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={draft.allow_other_pets}
                onChange={(event) => setDraft({ ...draft, allow_other_pets: event.target.checked })}
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
                      checked={!draft.disabled_rules.includes(rule.id)}
                      onChange={(event) => {
                        const disabled = event.target.checked
                          ? draft.disabled_rules.filter((r) => r !== rule.id)
                          : [...draft.disabled_rules, rule.id];
                        setDraft({ ...draft, disabled_rules: disabled });
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
                  value={draft.ai.spending_cap_usd}
                  onChange={(event) =>
                    setDraft({ ...draft, ai: { ...draft.ai, spending_cap_usd: Number(event.target.value) } })
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
