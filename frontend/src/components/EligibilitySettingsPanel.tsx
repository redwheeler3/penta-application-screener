import { type ReactNode, useEffect, useState } from "react";
import { AI_CHECKS, DETERMINISTIC_CHECKS } from "../constants";
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
  // The current committee default, for the "compared to committee default" divergence diff
  // (M15 1f). Computed lazily on read (member's blob vs current default) — no stored state.
  const [committeeDefault, setCommitteeDefault] = useState<EligibilityRules | null>(null);
  const [resetting, setResetting] = useState(false);

  useEffect(() => {
    let live = true;
    Promise.all([api.fetchEligibilityRules(), api.fetchCommitteeDefaultRules()])
      .then(([mine, def]) => {
        if (!live) return;
        setDraft(mine.rules);
        setIsDefault(mine.isDefault);
        setCommitteeDefault(def);
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

  async function reset() {
    if (resetting) return;
    setResetting(true);
    const response = await api.resetEligibilityRules();
    setResetting(false);
    if (!response.ok) {
      props.onError((await readProblem(response)) ?? "Could not reset to the committee default.");
      return;
    }
    // Server returns the now-effective (default) rules; adopt them and drop divergence.
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
            ) : (
              <DivergencePanel
                mine={draft}
                committeeDefault={committeeDefault}
                onReset={reset}
                resetting={resetting}
              />
            )}
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
              <h3>Screening checks</h3>
              <p className="rules-hint">
                Uncheck a check to disable it for your own list — it won't flag or exclude an
                applicant for you. Others' lists are unaffected.
              </p>
              <CheckGroup
                title="Deterministic rules"
                hint="Threshold checks decided at Sync from the form data."
                checks={DETERMINISTIC_CHECKS}
                draft={draft}
                setDraft={setDraft}
              />
              <CheckGroup
                title="AI screening checks"
                hint="Decided at Screen — the AI reads the application (pets are judged from what it extracts)."
                checks={AI_CHECKS}
                draft={draft}
                setDraft={setDraft}
              />
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

// The numeric/boolean rule fields, with member-facing labels, for the divergence diff.
const RULE_FIELDS: { key: keyof EligibilityRules; label: string }[] = [
  { key: "incomeMin", label: "Income minimum" },
  { key: "incomeMax", label: "Income maximum" },
  { key: "minAdultAge", label: "Min adult age" },
  { key: "maxChildAge", label: "Max child age" },
  { key: "minChildren", label: "Min children per unit" },
  { key: "maxChildren", label: "Max children per unit" },
  { key: "maxDogs", label: "Max dogs" },
  { key: "maxCats", label: "Max cats" },
  { key: "allowOtherPets", label: "Allow other pets" },
];

function fmt(v: number | boolean | string[]): string {
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "none";
  return String(v);
}

// The lazy "compared to committee default" diff (M15 1f): field-by-field, mine → default,
// ONLY for fields that differ, computed on read from the member's rules vs the CURRENT
// default. Purely informational, so "Reset" is never scary — it shows exactly what will
// change. Compares the live draft (not just the saved rules) so it reflects unsaved edits too.
function DivergencePanel(props: {
  mine: EligibilityRules;
  committeeDefault: EligibilityRules | null;
  onReset: () => void;
  resetting: boolean;
}): ReactNode {
  const { mine, committeeDefault, onReset, resetting } = props;
  const diffs = committeeDefault
    ? [
        ...RULE_FIELDS.filter((f) => mine[f.key] !== committeeDefault[f.key]).map((f) => ({
          label: f.label,
          mine: fmt(mine[f.key] as number | boolean),
          def: fmt(committeeDefault[f.key] as number | boolean),
        })),
        // disabledChecks is a list — compare as sets, show if they differ.
        ...(sameChecks(mine.disabledChecks, committeeDefault.disabledChecks)
          ? []
          : [
              {
                label: "Disabled checks",
                mine: fmt([...mine.disabledChecks].sort()),
                def: fmt([...committeeDefault.disabledChecks].sort()),
              },
            ]),
      ]
    : [];

  return (
    <div className="divergence-panel">
      <div className="divergence-head">
        <p className="panel-hint">
          These are your own rules, forked from the committee default.
          {committeeDefault && diffs.length === 0
            ? " They currently match the default."
            : " Reset drops your copy and follows the committee default again."}
        </p>
        <button type="button" className="secondary-button" onClick={onReset} disabled={resetting}>
          {resetting ? "Resetting" : "Reset to committee default"}
        </button>
      </div>
      {diffs.length > 0 ? (
        <table className="divergence-diff">
          <thead>
            <tr>
              <th>Rule</th>
              <th>Yours</th>
              <th>Committee default</th>
            </tr>
          </thead>
          <tbody>
            {diffs.map((d) => (
              <tr key={d.label}>
                <td>{d.label}</td>
                <td className="divergence-mine">{d.mine}</td>
                <td className="divergence-default">{d.def}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  );
}

function sameChecks(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const setB = new Set(b);
  return a.every((x) => setB.has(x));
}

// One labeled group of check toggles. Both groups edit the SAME flat draft.disabledChecks
// list — a check is ON when it is NOT in the list; unchecking adds its id. The
// deterministic/AI split is presentational (see AI_CHECKS / DETERMINISTIC_CHECKS).
function CheckGroup(props: {
  title: string;
  hint: string;
  checks: readonly { id: string; label: string }[];
  draft: EligibilityRules;
  setDraft: (next: EligibilityRules) => void;
}): ReactNode {
  const { title, hint, checks, draft, setDraft } = props;
  return (
    <div className="check-group">
      <h4>{title}</h4>
      <p className="rules-hint">{hint}</p>
      <div className="rules-grid">
        {[...checks].sort((a, b) => a.label.localeCompare(b.label)).map((check) => (
          <label key={check.id} className="checkbox-label rule-toggle">
            <input
              type="checkbox"
              checked={!draft.disabledChecks.includes(check.id)}
              onChange={(event) => {
                const disabled = event.target.checked
                  ? draft.disabledChecks.filter((c) => c !== check.id)
                  : [...draft.disabledChecks, check.id];
                setDraft({ ...draft, disabledChecks: disabled });
              }}
            />
            <span>{check.label}</span>
          </label>
        ))}
      </div>
    </div>
  );
}
