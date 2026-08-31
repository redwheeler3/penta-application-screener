import { type ReactNode, type SyntheticEvent, useEffect, useState } from "react";

import * as api from "../../api/settings";
import { ELIGIBILITY_GENERAL_NUMERIC_FIELDS } from "../../constants";
import { readProblem } from "../../api/problems";
import { useFetchResource } from "../../hooks/useFetchResource";
import type { EligibilityRules } from "../../types";
import { CheckGroup } from "./CheckToggles";
import { EmploymentRequirementField } from "./EmploymentRequirementField";
import { NumberInput } from "../shared/NumberInput";
import { PetLimitsFields } from "./PetLimitsFields";
import { RetryLoadError } from "../shared/RetryLoadError";

export function CommitteeDefaultsPanel(props: {
  openingId: number;
  onError: (message: string) => void;
  onEligibilityChanged: () => void;
}): ReactNode {
  const checks = useFetchResource(api.fetchEligibilityCheckCatalog);
  const [draft, setDraft] = useState<EligibilityRules | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [loadVersion, setLoadVersion] = useState(0);
  const [saving, setSaving] = useState(false);
  const [savedTick, setSavedTick] = useState(false);

  useEffect(() => {
    let live = true;
    setLoadError(false);
    api
      .fetchCommitteeDefaultRules(props.openingId)
      .then((rules) => live && setDraft(rules))
      .catch(() => {
        if (!live) return;
        setLoadError(true);
        props.onError("Could not load the committee default rules.");
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadVersion, props.openingId]);

  async function save(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft || saving) return;
    setSaving(true);
    const response = await api.saveCommitteeDefaultRules(props.openingId, draft);
    setSaving(false);
    if (!response.ok) {
      props.onError(
        (await readProblem(response)) ?? "The committee default rules could not be saved.",
      );
      return;
    }
    setDraft(await response.json());
    props.onEligibilityChanged();
    setSavedTick(true);
    setTimeout(() => setSavedTick(false), 2000);
  }

  const set = (patch: Partial<EligibilityRules>) =>
    draft && setDraft({ ...draft, ...patch });
  const toggle = (id: string, on: boolean) =>
    draft &&
    setDraft({
      ...draft,
      disabledChecks: on
        ? draft.disabledChecks.filter((check) => check !== id)
        : [...draft.disabledChecks, id],
    });

  return (
    <div className="settings-panel-body">
      <div className="settings-subtab-head">
        <h3>Committee default</h3>
        <p className="panel-hint">
          The shared eligibility baseline every member follows until they personalize their own
          rules. Changing it does not affect members who've already diverged.
        </p>
      </div>
      {loadError ? (
        <RetryLoadError
          message="Couldn't load the committee default rules."
          onRetry={() => setLoadVersion((version) => version + 1)}
        />
      ) : !draft ? (
        <p className="panel-hint">Loading…</p>
      ) : (
        <form className="settings-form" onSubmit={save}>
          {ELIGIBILITY_GENERAL_NUMERIC_FIELDS.map((field) => (
            <label key={field.key}>
              <span>{field.label}</span>
              <NumberInput
                min={field.min}
                max={field.max}
                value={draft[field.key] as number}
                onChange={(value) =>
                  set({ [field.key]: value ?? 0 } as Partial<EligibilityRules>)
                }
              />
            </label>
          ))}
          <PetLimitsFields value={draft} onChange={set} />
          <EmploymentRequirementField
            value={draft.employmentRequirement}
            onChange={(employmentRequirement) => set({ employmentRequirement })}
          />
          <div className="rules-section">
            <h4>Screening checks</h4>
            <p className="rules-hint">Unchecked checks are off in the committee default.</p>
            {checks.state === "error" ? (
              <RetryLoadError
                message="Couldn't load the screening checks."
                onRetry={checks.reload}
              />
            ) : checks.data ? (
              <>
                <CheckGroup
                  title="Deterministic rules"
                  checks={checks.data.deterministic}
                  disabledChecks={draft.disabledChecks}
                  onToggle={toggle}
                />
                <CheckGroup
                  title="AI screening checks"
                  checks={checks.data.ai}
                  disabledChecks={draft.disabledChecks}
                  onToggle={toggle}
                />
              </>
            ) : (
              <p className="rules-hint">Loading screening checks…</p>
            )}
          </div>
          <div className="settings-actions">
            <button className="primary-button" type="submit" disabled={saving}>
              {saving ? "Saving…" : savedTick ? "Saved" : "Save committee defaults"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
