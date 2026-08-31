import { type ReactNode, useEffect, useState } from "react";
import { ELIGIBILITY_GENERAL_NUMERIC_FIELDS, ELIGIBILITY_NUMERIC_FIELDS } from "../../constants";
import * as api from "../../api/settings";
import { readProblem } from "../../api/problems";
import { CheckGroup } from "./CheckToggles";
import { EmploymentRequirementField } from "./EmploymentRequirementField";
import { NumberInput } from "../shared/NumberInput";
import { PetLimitsFields } from "./PetLimitsFields";
import type { EligibilityRules } from "../../types";
import { RetryLoadError } from "../shared/RetryLoadError";
import { useFetchResource } from "../../hooks/useFetchResource";

// A member's own screening rules: the numeric eligibility thresholds plus which rules
// run. Self-contained — it fetches its rules on mount (like AccessPanel), edits a local
// draft, and saves through PUT /eligibility-rules. Every member sees this tab.
//
// A member starts on the shared committee default and only gets their own rules once
// they save; `isDefault` tracks that so we can hint that saving forks off the default.
export function EligibilitySettingsPanel(props: {
  openingId: number;
  onError: (message: string) => void;
  onRulesUpdated: () => void;
}): ReactNode {
  const [draft, setDraft] = useState<EligibilityRules | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [loadVersion, setLoadVersion] = useState(0);
  const [isDefault, setIsDefault] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savedTick, setSavedTick] = useState(false);
  // The current committee default, for the "compared to committee default" divergence diff
  // Computed on read from the member override and current default; no diff is stored.
  const [committeeDefault, setCommitteeDefault] = useState<EligibilityRules | null>(null);
  const [resetting, setResetting] = useState(false);
  const checks = useFetchResource(api.fetchEligibilityCheckCatalog);

  useEffect(() => {
    let live = true;
    setLoadError(false);
    Promise.all([
      api.fetchEligibilityRules(props.openingId),
      api.fetchCommitteeDefaultRules(props.openingId),
    ])
      .then(([mine, def]) => {
        if (!live) return;
        setDraft(mine.rules);
        setIsDefault(mine.isDefault);
        setCommitteeDefault(def);
      })
      .catch(() => {
        if (!live) return;
        setLoadError(true); // show an inline error instead of a perpetual "Loading…"
        props.onError("Could not load your eligibility rules.");
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadVersion, props.openingId]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!draft || saving) return;
    setSaving(true);
    const response = await api.saveEligibilityRules(props.openingId, draft);
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
    props.onRulesUpdated();
    // Transient "Saved" confirmation, matching CommitteeDefaultsPanel.
    setSavedTick(true);
    setTimeout(() => setSavedTick(false), 2000);
  }

  async function reset() {
    if (resetting) return;
    setResetting(true);
    const response = await api.resetEligibilityRules(props.openingId);
    setResetting(false);
    if (!response.ok) {
      props.onError((await readProblem(response)) ?? "Could not reset to the committee default.");
      return;
    }
    // Server returns the now-effective (default) rules; adopt them and drop divergence.
    const payload: { rules: EligibilityRules; isDefault: boolean } = await response.json();
    setDraft(payload.rules);
    setIsDefault(payload.isDefault);
    props.onRulesUpdated();
  }

  // Flip a check on/off in this member's own disabled set. Guarded on `draft` (the render
  // below only calls it inside the non-null branch).
  function toggleCheck(id: string, on: boolean) {
    if (!draft) return;
    const disabledChecks = on
      ? draft.disabledChecks.filter((c) => c !== id)
      : [...draft.disabledChecks, id];
    setDraft({ ...draft, disabledChecks });
  }

  return (
    <div className="settings-panel-body">
        {loadError ? (
          <RetryLoadError
            message="Couldn't load your eligibility rules."
            onRetry={() => setLoadVersion((version) => version + 1)}
          />
        ) : !draft ? (
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
            {ELIGIBILITY_GENERAL_NUMERIC_FIELDS.map((f) => (
              <label key={f.key}>
                <span>{f.label}</span>
                <NumberInput
                  min={f.min}
                  max={f.max}
                  value={draft[f.key] as number}
                  onChange={(v) => setDraft({ ...draft, [f.key]: v ?? 0 })}
                />
              </label>
            ))}
            <PetLimitsFields
              value={draft}
              onChange={(patch) => setDraft({ ...draft, ...patch })}
            />
            <EmploymentRequirementField
              value={draft.employmentRequirement}
              onChange={(employmentRequirement) =>
                setDraft({ ...draft, employmentRequirement })
              }
            />
            <div className="rules-section">
              <h4>Screening checks</h4>
              <p className="rules-hint">
                Uncheck a check to disable it for your own list — it won't flag or exclude an
                applicant for you. Others' lists are unaffected.
              </p>
              {checks.state === "error" ? (
                <RetryLoadError message="Couldn't load the screening checks." onRetry={checks.reload} />
              ) : checks.data ? (
                <>
                  <CheckGroup
                    title="Deterministic rules"
                    hint="Threshold checks decided directly from application fields."
                    checks={checks.data.deterministic}
                    disabledChecks={draft.disabledChecks}
                    onToggle={toggleCheck}
                  />
                  <CheckGroup
                    title="AI screening checks"
                    hint="Decided at Screen — the AI reads the application (pets are judged from what it extracts)."
                    checks={checks.data.ai}
                    disabledChecks={draft.disabledChecks}
                    onToggle={toggleCheck}
                  />
                </>
              ) : (
                <p className="rules-hint">Loading screening checks…</p>
              )}
            </div>
            <div className="settings-actions">
              <button className="primary-button" type="submit" disabled={saving}>
                {saving ? "Saving…" : savedTick ? "Saved" : "Save eligibility rules"}
              </button>
            </div>
          </form>
        )}
    </div>
  );
}

// The numeric/boolean rule fields, with member-facing labels, for the divergence diff:
// the shared numeric thresholds plus the one boolean (allowOtherPets), which the form
// renders as a checkbox but the diff still compares.
const RULE_FIELDS: { key: keyof EligibilityRules; label: string }[] = [
  ...ELIGIBILITY_NUMERIC_FIELDS.map(({ key, label }) => ({ key, label })),
  { key: "employmentRequirement", label: "Employment requirement" },
  { key: "allowOtherPets", label: "Allow other pets" },
];

function fmt(v: number | boolean | string | string[]): string {
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "none";
  return String(v);
}

// The "compared to committee default" diff: field-by-field, mine → default,
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
          mine: fmt(mine[f.key] as number | boolean | string),
          def: fmt(committeeDefault[f.key] as number | boolean | string),
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
