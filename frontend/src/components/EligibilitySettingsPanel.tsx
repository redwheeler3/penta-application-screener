import { type ReactNode, useEffect, useState } from "react";
import { ALL_RULES } from "../constants";
import * as api from "../api";
import { readProblem } from "../format";
import { NumberInput } from "./NumberInput";
import type { EligibilityRules } from "../types";

// A member's own screening rules: the numeric eligibility thresholds plus which rules
// run. Self-contained — it fetches its rules on mount (like AccessPanel), edits a local
// draft, and saves through PUT /eligibility-rules. Every member sees this tab.
//
// A member starts on the shared committee default and only gets their own rules once
// they save; `isDefault` tracks that so we can hint that saving forks off the default.
export function EligibilitySettingsPanel(props: { onError: (message: string) => void }): ReactNode {
  const [draft, setDraft] = useState<EligibilityRules | null>(null);
  const [isDefault, setIsDefault] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .fetchEligibilityRules()
      .then((payload) => {
        if (!live) return;
        setDraft(payload.rules);
        setIsDefault(payload.isDefault);
      })
      .catch(() => live && props.onError("Could not load your eligibility rules."));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!draft || saving) return;
    setSaving(true);
    const response = await api.saveEligibilityRules(draft);
    setSaving(false);
    if (!response.ok) {
      // The server validates cross-field constraints (e.g. incomeMax >= incomeMin) and
      // returns a problem+json detail; surface it rather than a generic message.
      props.onError((await readProblem(response)) ?? "Your eligibility rules could not be saved.");
      return;
    }
    const payload: { rules: EligibilityRules; isDefault: boolean } = await response.json();
    setDraft(payload.rules);
    setIsDefault(payload.isDefault);
  }

  return (
    <section className="settings-panel no-print" aria-label="Eligibility rules">
      <div className="settings-header">
        <h3>Eligibility Settings</h3>
      </div>
      <div className="settings-panel-body">
        {!draft ? (
          <p className="panel-hint">Loading…</p>
        ) : (
          <form className="settings-form" onSubmit={save}>
            {isDefault ? (
              <p className="panel-hint eligibility-default-hint">
                You're using the committee default — saving creates your own copy to tune.
              </p>
            ) : null}
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
            <div className="settings-actions">
              <button className="primary-button" type="submit" disabled={saving}>
                {saving ? "Saving" : "Save eligibility rules"}
              </button>
            </div>
          </form>
        )}
      </div>
    </section>
  );
}
