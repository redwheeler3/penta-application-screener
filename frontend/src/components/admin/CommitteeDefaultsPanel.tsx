import { type ReactNode, type SyntheticEvent } from "react";

import * as api from "../../api/settings";
import { ELIGIBILITY_GENERAL_NUMERIC_FIELDS } from "../../constants";
import { useFetchResource } from "../../hooks/useFetchResource";
import { useEligibilityRules } from "../../hooks/useEligibilityRules";
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
  const rules = useEligibilityRules({
    openingId: props.openingId,
    kind: "committee-default",
    onError: props.onError,
    onUpdated: props.onEligibilityChanged,
  });
  const { draft, setDraft, saving, savedTick } = rules;

  function save(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    void rules.save();
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
      {rules.state === "error" ? (
        <RetryLoadError
          message="Couldn't load the committee default rules."
          onRetry={rules.reload}
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
            <button className="primary-button" type="submit" disabled={rules.busy}>
              {saving ? "Saving…" : savedTick ? "Saved" : "Save committee defaults"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
